"""News index: Yahoo stories embedded in their own Qdrant collection so the News agent can answer topic and cross-ticker
questions ("what's been said about chip export restrictions this week?") and see further back than Yahoo's ~30 stories.

One point per story (title + summary); the point id is a hash of the story id, so re-fetching the same story never duplicates
it, it only adds the ticker to the story's `tickers`. Stories are added whenever news is fetched from Yahoo (`queue_ingest`,
registered as a market-service listener) and by a background poll of the tracked tickers; stories older than the retention
window are deleted. Everything runs inside the API process on the Qdrant client shared with the knowledge base.

A Yahoo story comes with a headline only, so when one is shown in an answer its page is read (src/core/articles.py) and the
excerpt kept on the story as `article`/`article_fetched_at` for `article_ttl_days`, with the LLM's 2-3 sentence summary of it
as `article_summary`: reads ignore older excerpts and `prune` removes them, leaving the headline."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from qdrant_client import QdrantClient, models

from . import markets
from .store import EMBEDDING_DIM, QDRANT_LOCK, QUERY_PREFIX, get_embedder

log = logging.getLogger(__name__)

_ready = False
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news-index")     # keeps embedding off the request path


ARTICLE, ARTICLE_TS, ARTICLE_SUMMARY = "article", "article_fetched_at", "article_summary"
ARTICLE_FETCHERS = 6            # story pages read at once


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
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            client.create_payload_index(name, ARTICLE_TS, models.PayloadSchemaType.FLOAT)   # also on collections made before excerpts
        _ready = True
    return name


def ingest(symbol: str, items: list[dict], client: QdrantClient | None = None) -> int:
    """Index the stories of a news fetch. `symbol` is the ticker or market news term they were fetched for; each story is tagged
    with it (None, the market pseudo-symbol or an index that isn't a market news term adds none) and with its market groups
    ("market:forex"), so a search can be limited to one market. Returns how many stories were new."""
    term = bool(symbol) and markets.is_news_term(symbol)
    ticker = symbol.upper() if symbol and (term or not symbol.startswith("^")) and symbol.upper() != markets.MARKET_FEED else None
    tags = ([ticker] if ticker else []) + markets.news_tags(symbol)
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
        for pid, payload in existing.items():              # already indexed: only record the extra tags, and a missing thumbnail
            update = {}
            if not set(tags) <= set(payload.get("tickers", [])):
                update["tickers"] = sorted({*payload.get("tickers", []), *tags})
            if not payload.get("thumbnail") and stories[pid][0].get("thumbnail"):
                update["thumbnail"] = stories[pid][0]["thumbnail"]
            if update:
                client.set_payload(name, update, points=[pid])
        fresh = [(pid, it, ts) for pid, (it, ts) in stories.items() if pid not in existing]
        if not fresh:
            return 0
        vectors = list(get_embedder().embed([f"{it['title']}\n{it.get('summary', '')}".strip() for _, it, _ in fresh]))
        client.upsert(name, points=[
            models.PointStruct(id=pid, vector=v.tolist(), payload={
                "story_id": it["id"], "title": it["title"], "summary": it.get("summary", ""), "publisher": it.get("publisher", ""),
                "url": it["url"], "thumbnail": it.get("thumbnail"), "published": it["published"], "published_ts": ts, "ingested_at": now,
                "tickers": tags})
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
    """Delete stories older than the retention window, and article excerpts older than `article_ttl_days`."""
    client = client or _client()
    now = time.time()
    with QDRANT_LOCK:
        name = _ensure_collection(client)
        client.delete(name, points_selector=models.FilterSelector(filter=models.Filter(must=[
            models.FieldCondition(key="published_ts", range=models.Range(lt=now - _cfg()["retention_days"] * 86400))])))
        client.delete_payload(name, keys=[ARTICLE, ARTICLE_TS, ARTICLE_SUMMARY], points=models.FilterSelector(filter=models.Filter(must=[
            models.FieldCondition(key=ARTICLE_TS, range=models.Range(lt=now - _cfg()["article_ttl_days"] * 86400))])))


def _fresh_article(payload: dict, now: float) -> str | None:
    """The stored excerpt ('' = the page had none), or None when there is none younger than `article_ttl_days`."""
    ts = payload.get(ARTICLE_TS)
    return payload.get(ARTICLE) or "" if ts is not None and now - ts < _cfg()["article_ttl_days"] * 86400 else None


def articles(stories: list[dict], client: QdrantClient | None = None, fetch=None, summarize=None) -> dict[str, str]:
    """{story id: what the story says} for the Yahoo stories that came without a summary: `summarize(title, excerpt)`'s
    summary of the article (an LLM's 2-3 sentences) when given, else the article excerpt. Excerpts and summaries younger
    than `article_ttl_days` come from the index; the rest are read from the story pages and summarized, in parallel, and
    kept on the indexed story (a page with no text is kept as '' so it isn't read again until the excerpt would have
    expired; a story whose summary failed is read and summarized again next time)."""
    from src.core import articles as A
    fetch = fetch or (lambda url: A.fetch_article(url, _cfg()["article_chars"]))
    want = {s.get("story_id") or s["id"]: s for s in stories if not s.get("summary") and A.is_yahoo(s.get("url"))}
    if not want:
        return {}
    now, found, summaries = time.time(), {}, {}

    def take(sid: str, payload: dict) -> None:
        # with a summarizer, an excerpt kept without a summary (read before summaries, or its summary failed) is read
        # again: excerpts were shorter then, and the summary should digest the article as `article_chars` allows now
        if (text := _fresh_article(payload, now)) is not None and (not summarize or not text or payload.get(ARTICLE_SUMMARY)):
            found[sid] = text
            if payload.get(ARTICLE_SUMMARY):
                summaries[sid] = payload[ARTICLE_SUMMARY]

    for sid, s in want.items():                            # a search hit carries its payload, excerpt included
        take(sid, s)
    client = client or _client()
    ids = {story_point_id(sid): sid for sid in want if sid not in found or (summarize and sid not in summaries)}
    indexed = set()
    if ids:
        with QDRANT_LOCK:
            name = _ensure_collection(client)
            for p in client.retrieve(name, ids=list(ids), with_payload=[ARTICLE, ARTICLE_TS, ARTICLE_SUMMARY]):
                indexed.add(p.id)
                take(ids[p.id], p.payload or {})
    todo = [sid for sid in want if sid not in found]
    brief = [sid for sid in want if summarize and sid not in summaries]

    def work(sid: str) -> tuple[str | None, str | None]:
        text = fetch(want[sid]["url"]) if sid in todo else None
        excerpt = found.get(sid, "") if text is None else text
        return text, (summarize(want[sid].get("title") or "", excerpt) or None) if excerpt and summarize else None

    if jobs := [sid for sid in want if sid in todo or sid in brief]:
        with ThreadPoolExecutor(max_workers=ARTICLE_FETCHERS, thread_name_prefix="news-article") as pool:
            done = dict(zip(jobs, pool.map(work, jobs)))
        read = {sid: text for sid, (text, _) in done.items() if text is not None}
        written = {sid: summary for sid, (_, summary) in done.items() if summary}
        found.update(read)
        summaries.update(written)
        with QDRANT_LOCK:
            name = _ensure_collection(client)
            for sid in set(read) | set(written):
                if story_point_id(sid) not in indexed:     # a story not indexed yet is read again next time
                    continue
                payload = {ARTICLE: read[sid], ARTICLE_TS: now} if sid in read else {}
                client.set_payload(name, payload | ({ARTICLE_SUMMARY: written[sid]} if sid in written else {}),
                                   points=[story_point_id(sid)])
        if read:
            log.info("news index: read %d story pages (%d with text)", len(read), sum(1 for t in read.values() if t))
    return {sid: summaries.get(sid) or text for sid, text in found.items() if text}


def search(client: QdrantClient, query: str, *, tickers: list[str] | None = None, days: int = 7, k: int = 6) -> list[dict]:
    """Top-k stories published within `days` (and, if given, tagged with any of `tickers`), as payload dicts with a `score`."""
    with QDRANT_LOCK:
        name = _cfg()["collection"]
        if not client.collection_exists(name):
            return []
        must = [models.FieldCondition(key="published_ts", range=models.Range(gte=time.time() - days * 86400))]
        if tickers:
            tags = [t if t.startswith("market:") else t.upper() for t in tickers]
            must.append(models.FieldCondition(key="tickers", match=models.MatchAny(any=tags)))
        qvec = next(iter(get_embedder().embed([QUERY_PREFIX + query]))).tolist()
        hits = client.query_points(name, query=qvec, limit=k, query_filter=models.Filter(must=must), with_payload=True).points
    return [{"score": h.score, **h.payload} for h in hits]


def recent(client: QdrantClient, tickers: list[str], days: int, limit: int = 200) -> list[dict]:
    """Every indexed story tagged with any of `tickers` and published within `days`, newest first (no ranking by meaning):
    the stories behind "the last 10 days of AAPL news", which reach further back than Yahoo's ~30 latest headlines."""
    with QDRANT_LOCK:
        name = _cfg()["collection"]
        if not client.collection_exists(name):
            return []
        tags = [t if t.startswith("market:") else t.upper() for t in tickers]
        flt = models.Filter(must=[models.FieldCondition(key="published_ts", range=models.Range(gte=time.time() - days * 86400)),
                                  models.FieldCondition(key="tickers", match=models.MatchAny(any=tags))])
        points, _ = client.scroll(name, scroll_filter=flt, limit=limit, with_payload=True, with_vectors=False)
    return sorted((p.payload for p in points), key=lambda s: s.get("published_ts") or 0, reverse=True)


# ---- background poll -----------------------------------------------------------------------------------------
def tracked_symbols(db) -> list[str]:
    """What the poll covers: the market feed, every portfolio holding, and any ticker whose quote or news was fetched recently
    (the Live Market watchlist and look-ups and chat questions all go through those), most recently fetched first, capped.
    A market someone asked about is polled by its news term ("DXY" for DX-Y.NYB, "^TNX"), or not at all when it has none."""
    from sqlalchemy import select

    from src.db.models import Holding, MarketCache
    from src.db.session import market_cache_session
    cfg = _cfg()
    since = datetime.now(timezone.utc) - timedelta(days=cfg["recent_view_days"])
    held = [t for (t,) in db.execute(select(Holding.ticker).distinct())]
    with market_cache_session(db) as cache:
        viewed = [s for (s,) in cache.execute(select(MarketCache.symbol).where(MarketCache.endpoint.in_(("quote", "news")),
                                                                                MarketCache.fetched_at >= since)
                                              .order_by(MarketCache.fetched_at.desc()))]
    from src.core.market_service import _MARKET_NEWS_SOURCES
    feed = {markets.MARKET_FEED, *_MARKET_NEWS_SOURCES}                   # already covered by the market feed
    terms = [markets.news_term_for(s) for s in held + viewed if s]
    wanted = list(dict.fromkeys(t.upper() for t in terms if t and (markets.is_news_term(t) or not t.startswith("^")) and t.upper() not in feed))
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
