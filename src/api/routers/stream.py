"""WebSocket endpoint for live prices. Protocol (JSON):
  client -> {"action": "subscribe" | "unsubscribe", "symbols": ["AAPL", ...]}
  server -> {"type": "subscribed", "symbols": [...], "rejected": [...]}
            {"type": "tick", "symbol", "price", "change", "change_pct", "volume", "ts", ...}
            {"type": "status", "state": "connecting" | "connected" | "reconnecting" | "idle"}
            {"type": "error", "message": "..."}"""
import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.core.live_stream import MAX_SYMBOLS_PER_CLIENT, hub, normalize_symbol

router = APIRouter(tags=["market"], prefix="/market")


@router.websocket("/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    q = hub.register()
    sender = asyncio.create_task(_pump(ws, q))
    try:
        await ws.send_json({"type": "status", "state": hub.state})
        while True:
            try:
                msg = json.loads(await ws.receive_text())
                action, raw = msg["action"], msg.get("symbols", [])
                if action not in ("subscribe", "unsubscribe") or not isinstance(raw, list):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                await ws.send_json({"type": "error", "message": 'Expected {"action": "subscribe"|"unsubscribe", "symbols": [...]}'})
                continue
            symbols = [s for s in (normalize_symbol(str(r)) for r in raw) if s]
            rejected = [str(r) for r in raw if normalize_symbol(str(r)) is None]
            if action == "subscribe":
                added = await hub.subscribe(q, symbols)
                rejected += [s for s in symbols if s not in added and s not in hub._clients[q]]   # over the per-client cap
                await ws.send_json({"type": "subscribed", "symbols": sorted(hub._clients[q]), "rejected": rejected, "max": MAX_SYMBOLS_PER_CLIENT})
            else:
                await hub.unsubscribe(q, symbols)
                await ws.send_json({"type": "subscribed", "symbols": sorted(hub._clients[q]), "rejected": rejected, "max": MAX_SYMBOLS_PER_CLIENT})
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender
        await hub.unregister(q)


async def _pump(ws: WebSocket, q: asyncio.Queue):
    while True:
        await ws.send_json(await q.get())
