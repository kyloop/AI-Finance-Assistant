"""News index: Yahoo stories embedded in their own Qdrant collection so the News agent can answer topic and cross-ticker
questions ("what's been said about chip export restrictions this week?") and see further back than Yahoo's ~30 stories.

One point per story (title + summary); the point id is a hash of the story id, so re-fetching the same story never duplicates
it, it only adds the ticker to the story's `tickers`. Stories are added whenever news is fetched from Yahoo (`queue_ingest`,
registered as a market-service listener) and by a background poll of the tracked tickers; stories older than the retention
window are deleted. Everything runs inside the API process on the Qdrant client shared with the knowledge base."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from qdrant_client import QdrantClient, models

from .store import EMBEDDING_DIM, QDRANT_LOCK, QUERY_PREFIX, get_embedder

log = logging.getLogger(__name__)

_ready = False
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news-index")     # keeps embedding off the request path


def _cfg() -> dict:
    from src.core.config import get_config
    return get_config()["news_index"]


def _client() -> QdrantClient:
    from src.workflow.tools import _kb_client
    return _kb_client()


def story_point_id(story_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"news:{story_id}"))


def parse_published(value: str | None) -> float | None:
    """Yahoo's ISO timestamp (…Z) -> epoch seconds; None if missing or malformed."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else None
    except ValueError:
        return None


def _ensure_collection(client: QdrantClient) -> str:
    global _ready
    name = _cfg()["collection"]
    if not _ready:
        if not client.collection_exists(name):
            client.create_collection(name, vectors_config=models.VectorParams(size=EMBEDDING_DIM, distance=models.Distance.COSINE))
            with warnings.catch_warnings():                # local (embedded) Qdrant ignores payload indexes and warns
                warnings.simplefilter("ignore", UserWarning)
                client.create_payload_index(name, "tickers", models.PayloadSchemaType.KEYWORD)
                client.create_payload_index(name, "published_ts", models.PayloadSchemaType.FLOAT)
        _ready = True
    return name


def ingest(symbol: str, items: list[dict], client: QdrantClient | None = None) -> int:
    """Index the stories of a news fetch. `symbol` is the ticker they were fetched for (None, the market pseudo-symbol or an
    index adds no ticker). Returns how many stories were new."""
    ticker = symbol.upper() if symbol and not symbol.startswith("^") and symbol.upper() != "MARKET" else None
    now = time.time()
    cutoff = now - _cfg()["retention_days"] * 86400
    stories = {}
    for it in items:
        ts = parse_published(it.get("published"))
        if ts is None or ts < cutoff or not it.get("title"):
            continue
        stories[story_point_id(it["id"])] = (it, ts)
    if not stories:
        return 0
    client = client or _client()
    with QDRANT_LOCK:
        name = _ensure_collection(client)
        existing = {p.id: p.payload for p in client.retrieve(name, ids=list(stories), with_payload=True)}
        for pid, payload in existing.items():              # already indexed: only record the extra ticker
            if ticker and ticker not in payload.get("tickers", []):
                client.set_payload(name, {"tickers": sorted({*payload.get("tickers", []), ticker})}, points=[pid])
        fresh = [(pid, it, ts) for pid, (it, ts) in stories.items() if pid not in existing]
        if not fresh:
            return 0
        vectors = list(get_embedder().embed([f"{it['title']}\n{it.get('summary', '')}".strip() for _, it, _ in fresh]))
        client.upsert(name, points=[
            models.PointStruct(id=pid, vector=v.tolist(), payload={
                "story_id": it["id"], "title": it["title"], "summary": it.get("summary", ""), "publisher": it.get("publisher", ""),
                "url": it["url"], "published": it["published"], "published_ts": ts, "ingested_at": now,
                "tickers": [ticker] if ticker else []})
            for (pid, it, ts), v in zip(fresh, vectors)])
    log.info("news index: +%d stories (%s)", len(fresh), symbol or "market")
    return len(fresh)


def queue_ingest(symbol: str, items: list[dict]) -> None:
    """Market-service listener: index in the background so the news request isn't slowed (or broken) by the embedder or Qdrant."""
    def work():
        try:
            ingest(symbol, items)
        except Exception:  # noqa: BLE001 — indexing is best-effort
            log.exception("news index: ingest failed for %s", symbol)
    _pool.submit(work)


def prune(client: QdrantClient | None = None) -> None:
    """Delete stories older than the retention window."""
    client = client or _client()
    cutoff = time.time() - _cfg()["retention_days"] * 86400
    with QDRANT_LOCK:
        name = _ensure_collection(client)
        client.delete(name, points_selector=models.FilterSelector(filter=models.Filter(must=[
            models.FieldCondition(key="published_ts", range=models.Range(lt=cutoff))])))


def search(client: QdrantClient, query: str, *, tickers: list[str] | None = None, days: int = 7, k: int = 6) -> list[dict]:
    """Top-k stories published within `days` (and, if given, tagged with any of `tickers`), as payload dicts with a `score`."""
    with QDRANT_LOCK:
        name = _cfg()["collection"]
        if not client.collection_exists(name):
            return []
        must = [models.FieldCondition(key="published_ts", range=models.Range(gte=time.time() - days * 86400))]
        if tickers:
            must.append(models.FieldCondition(key="tickers", match=models.MatchAny(any=[t.upper() for t in tickers])))
        qvec = next(iter(get_embedder().embed([QUERY_PREFIX + query]))).tolist()
        hits = client.query_points(name, query=qvec, limit=k, query_filter=models.Filter(must=must), with_payload=True).points
    return [{"score": h.score, **h.payload} for h in hits]


# ---- background poll -----------------------------------------------------------------------------------------
def tracked_symbols(db) -> list[str]:
    """What the poll covers: the market feed, every portfolio holding, and any ticker whose quote or news was fetched recently
    (the Live-tab watchlist and Market-tab searches both go through those), most recently fetched first, capped."""
    from sqlalchemy import select

    from src.db.models import Holding, MarketCache
    cfg = _cfg()
    since = datetime.now(timezone.utc) - timedelta(days=cfg["recent_view_days"])
    held = [t for (t,) in db.execute(select(Holding.ticker).distinct())]
    viewed = [s for (s,) in db.execute(select(MarketCache.symbol).where(MarketCache.endpoint.in_(("quote", "news")),
                                                                         MarketCache.fetched_at >= since)
                                       .order_by(MarketCache.fetched_at.desc()))]
    wanted = list(dict.fromkeys(s.upper() for s in held + viewed if s and not s.startswith("^") and s.upper() != "MARKET"))
    return ["MARKET"] + wanted[:cfg["max_tracked_symbols"]]


def poll_once(session_factory=None) -> int:
    """Refresh the news of every tracked symbol (each fetch indexes through the market-service listener), then prune."""
    from src.core.market_service import get_market_data
    if session_factory is None:
        from src.db.session import SessionLocal as session_factory
    fetched = 0
    with session_factory() as db:
        for sym in tracked_symbols(db):
            try:
                get_market_data(db, "news", sym, refresh=True)
                fetched += 1
            except Exception:  # noqa: BLE001 — one bad ticker must not stop the poll
                log.warning("news poll: %s failed", sym)
            time.sleep(0.3)
    _pool.submit(lambda: None).result()                    # let queued indexing finish before pruning
    prune()
    return fetched


async def run_poller() -> None:
    """Poll forever (first pass right away); cancelled on shutdown. Errors are logged, never fatal."""
    while True:
        try:
            await asyncio.to_thread(poll_once)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("news poll failed")
        await asyncio.sleep(_cfg()["poll_seconds"])
