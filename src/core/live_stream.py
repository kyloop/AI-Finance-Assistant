"""Live price streaming: one shared upstream yfinance WebSocket fanned out to any number of client queues.
The hub opens the upstream connection only while someone is subscribed, reference-counts symbols across clients,
and reconnects with backoff. Ticks are normalised to the same shape/units as market_service quotes."""
from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)

SYMBOL_RE = re.compile(r"^[A-Z0-9.\-=^]{1,15}$")
MAX_SYMBOLS_PER_CLIENT = 20
CLIENT_QUEUE_SIZE = 200
BACKOFF_START, BACKOFF_MAX = 1.0, 30.0


def normalize_symbol(raw: str) -> str | None:
    s = raw.strip().upper()
    return s if SYMBOL_RE.match(s) else None


def normalize_tick(msg: dict) -> dict | None:
    """Yahoo pricing message -> {symbol, price, change, change_pct (fraction), volume, ts, market_hours, ...}."""
    if "id" not in msg or "price" not in msg:
        return None
    ts_ms = int(msg.get("time") or 0)
    tick = {
        "type": "tick",
        "symbol": msg["id"],
        "price": round(float(msg["price"]), 4),
        "change": round(float(msg["change"]), 4) if "change" in msg else None,
        "change_pct": round(float(msg["change_percent"]) / 100, 6) if "change_percent" in msg else None,
        "volume": int(msg["day_volume"]) if msg.get("day_volume") else None,
        "ts": (datetime.fromtimestamp(ts_ms / 1000, timezone.utc) if ts_ms else datetime.now(timezone.utc)).isoformat(),
        "market_hours": msg.get("market_hours"),   # 0 pre, 1 regular, 2 post, 3 extended (Yahoo codes)
    }
    for src, dst in (("day_high", "day_high"), ("day_low", "day_low"), ("open_price", "open")):
        if src in msg:
            tick[dst] = round(float(msg[src]), 4)
    return tick


def _yahoo_socket():
    import yfinance as yf          # lazy: keeps the API importable (and tests offline) without the live dependency
    return yf.AsyncWebSocket(verbose=False)


class LiveHub:
    def __init__(self, socket_factory: Callable[[], Any] = _yahoo_socket):
        self._factory = socket_factory
        self._clients: dict[asyncio.Queue, set[str]] = {}
        self._refs: Counter[str] = Counter()
        self._latest: dict[str, dict] = {}
        self._ws: Any = None
        self._task: asyncio.Task | None = None
        self.state = "idle"             # idle | connecting | connected | reconnecting

    # ---- client side -----------------------------------------------------------------------------------
    def register(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE_SIZE)
        self._clients[q] = set()
        return q

    async def unregister(self, q: asyncio.Queue) -> None:
        await self.unsubscribe(q, list(self._clients.get(q, ())))
        self._clients.pop(q, None)
        if not self._clients and self._task:
            await self.stop()

    async def subscribe(self, q: asyncio.Queue, symbols: list[str]) -> list[str]:
        """Returns symbols actually added (invalid/duplicate/over-cap ones are skipped)."""
        mine, added = self._clients[q], []
        for s in symbols:
            if s in mine or len(mine) >= MAX_SYMBOLS_PER_CLIENT:
                continue
            mine.add(s)
            self._refs[s] += 1
            added.append(s)
            if s in self._latest:       # instant first paint from the last known tick
                self._put(q, self._latest[s])
        new_upstream = [s for s in added if self._refs[s] == 1]
        if new_upstream:
            await self._upstream("subscribe", new_upstream)
        if added and not self._task:
            self._task = asyncio.create_task(self._run())
        return added

    async def unsubscribe(self, q: asyncio.Queue, symbols: list[str]) -> None:
        mine, gone = self._clients.get(q, set()), []
        for s in symbols:
            if s in mine:
                mine.discard(s)
                self._refs[s] -= 1
                if self._refs[s] <= 0:
                    del self._refs[s]
                    self._latest.pop(s, None)
                    gone.append(s)
        if gone:
            await self._upstream("unsubscribe", gone)

    # ---- upstream side ---------------------------------------------------------------------------------
    async def _upstream(self, op: str, symbols: list[str]) -> None:
        if self._ws is None:            # not connected yet: _run subscribes to everything in _refs on connect
            return
        try:
            await getattr(self._ws, op)(symbols)
        except Exception:
            # don't close from here: yfinance's listen() would spin on a closed socket; its heartbeat resubscribes
            log.warning("upstream %s failed", op, exc_info=True)

    async def _run(self) -> None:
        backoff = BACKOFF_START
        while self._clients:
            self._set_state("connecting" if backoff == BACKOFF_START else "reconnecting")
            ws = self._factory()
            try:
                async with ws:
                    self._ws = ws
                    if self._refs:
                        await ws.subscribe(list(self._refs))
                    self._set_state("connected")
                    backoff = BACKOFF_START
                    await ws.listen(self._on_message)
                    if asyncio.current_task().cancelling():     # yfinance's listen() swallows cancellation
                        raise asyncio.CancelledError
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("live stream dropped", exc_info=True)
            finally:
                self._ws = None
            if not self._clients:
                break
            self._set_state("reconnecting")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
        self._set_state("idle")

    def _on_message(self, msg: dict) -> None:
        tick = normalize_tick(msg)
        if not tick or tick["symbol"] not in self._refs:
            return
        # Yahoo sends partial updates (e.g. no change fields): merge onto the last tick so clients get full rows
        merged = {**self._latest.get(tick["symbol"], {}), **{k: v for k, v in tick.items() if v is not None}}
        self._latest[tick["symbol"]] = merged
        for q, syms in list(self._clients.items()):
            if tick["symbol"] in syms:
                self._put(q, merged)

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            for q in list(self._clients):
                self._put(q, {"type": "status", "state": state})

    @staticmethod
    def _put(q: asyncio.Queue, item: dict) -> None:
        if q.full():                    # slow client: drop the oldest rather than block the shared feed
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(item)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._ws = None
        self.state = "idle"


hub = LiveHub()
