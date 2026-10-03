"""Tools the agents call. Each is a plain function so it can be unit-tested and reused by the MCP server later."""
from __future__ import annotations

import logging
import re

from src.core.market_service import SymbolNotFound, get_market_data, industry_peers, resolve_symbol
from src.kb.wiki import (DisambiguationPage, PageNotFound, WikiClient, WikiUnavailable, count_words, truncate_words)

log = logging.getLogger(__name__)

_client: WikiClient | None = None
_cache: dict[tuple[str, int], dict | None] = {}
_STOP = {"the", "and", "for", "what", "how", "does", "are", "with", "that", "this", "from", "about", "between", "vs", "difference",
         "different", "work", "works", "mean", "means", "explain", "tell"}


def get_wiki_client() -> WikiClient:
    global _client
    if _client is None:
        _client = WikiClient(delay=0.3)
    return _client


def set_wiki_client(client) -> None:
    """Tests inject a fake; also clears the lookup cache."""
    global _client
    _client = client
    _cache.clear()


FINANCE_WORDS = ("financ", "invest", "money", "bank", "tax", "econom", "stock", "bond", "fund", "market", "loan", "credit", "debt",
                 "retire", "saving", "insurance", "pension", "interest", "dividend", "portfolio", "asset", "budget", "income", "wealth",
                 "inflation", "securit", "currency", "price", "mortgage", "equity", "trading", "account")


def _is_finance(title: str, lead: str) -> bool:
    """Topic gate: Wikipedia search happily returns albums and file formats for loosely-worded queries."""
    hay = f"{title} {lead[:700]}".lower()
    return sum(w in hay for w in FINANCE_WORDS) >= 2


def _relevant(query: str, title: str, lead: str) -> bool:
    words = {w for w in re.findall(r"[a-z0-9&']+", query.lower()) if len(w) > 2 and w not in _STOP}
    hay = f"{title} {lead[:400]}".lower()
    return not words or any(w in hay for w in words)


def wiki_search(query: str, max_words: int = 150) -> dict | None:
    """Look the topic up on Wikipedia. Returns {title, url, revision_id, extract, confidence} or None if nothing usable.
    Raises WikiUnavailable if Wikipedia can't be reached."""
    key = (query.strip().lower(), max_words)
    if key in _cache:
        return _cache[key]
    client = get_wiki_client()
    result = None
    for rank, title in enumerate(client.search(query, limit=3)):
        try:
            page = client.get_page(title)
        except (PageNotFound, DisambiguationPage):
            continue
        lead, *_ = page.text.split("\n\n## ", 1)
        if count_words(lead) < 40:                       # very short lead: include the first section too
            lead = page.text
        extract, _ = truncate_words(lead, max_words)
        if not _is_finance(page.title, lead) or not _relevant(query, page.title, lead):
            continue
        result = {"title": page.title, "url": page.url, "revision_id": page.revision_id, "extract": extract,
                  "confidence": "high" if rank == 0 else "medium"}
        break
    _cache[key] = result
    return result


def wiki_topic(topic: str, max_words: int = 150) -> dict | None:
    """Look up an article by title (an LLM-suggested topic). The exact title is fetched first, following redirects; only
    if it doesn't exist is Wikipedia searched, and then a result must share a word with the topic in its title, so
    "Home buying" can't come back as a company like "Opendoor". Same return shape as wiki_search."""
    key = ("topic:" + topic.strip().lower(), max_words)
    if key in _cache:
        return _cache[key]
    client = get_wiki_client()
    words = {w for w in re.findall(r"[a-z0-9]+", topic.lower()) if len(w) > 2}
    try:
        candidates = [(client.get_page(topic), "high")]
    except (PageNotFound, DisambiguationPage):
        candidates = []
        for title in client.search(topic, limit=3):
            if words & set(re.findall(r"[a-z0-9]+", title.lower())):
                try:
                    candidates.append((client.get_page(title), "medium"))
                except (PageNotFound, DisambiguationPage):
                    continue
    result = None
    for page, confidence in candidates:
        lead, *_ = page.text.split("\n\n## ", 1)
        if count_words(lead) < 40:
            lead = page.text
        if _is_finance(page.title, lead):
            extract, _ = truncate_words(lead, max_words)
            result = {"title": page.title, "url": page.url, "revision_id": page.revision_id, "extract": extract, "confidence": confidence}
            break
    _cache[key] = result
    return result


_kb_searcher = None          # tests inject a fake; None = the Qdrant knowledge base (src/rag)


def set_kb_searcher(fn) -> None:
    """Tests inject `fn(query, k) -> list[hit]`; None restores the real knowledge-base search."""
    global _kb_searcher
    _kb_searcher = fn


def kb_search(query: str, k: int | None = None) -> list[dict]:
    """Top-k knowledge-base chunks for the question (mds/rag-data-design.md), each a payload dict with `score`.
    Returns [] when the index hasn't been built; raises if Qdrant itself fails."""
    if _kb_searcher is not None:
        return _kb_searcher(query, k)
    from src.core.config import get_config
    from src.rag.store import search
    cfg = get_config()["rag"]
    client = _kb_client()
    if not client.collection_exists(cfg["collection"]):
        return []
    return search(client, cfg["collection"], query, k=k or cfg["top_k"])


_qdrant = None


def _kb_client():
    """One client per process (shared with the news index): the local (embedded) Qdrant store can only be opened by one client at a time."""
    global _qdrant
    if _qdrant is None:
        import atexit

        from src.core.config import get_config
        from src.rag.store import QDRANT_LOCK, get_client
        with QDRANT_LOCK:
            if _qdrant is None:
                _qdrant = get_client(get_config()["rag"])
                atexit.register(_qdrant.close)       # close before interpreter teardown (avoids a noisy __del__)
    return _qdrant


_news_searcher = None        # tests inject a fake; None = the Qdrant news collection (src/rag/news.py)


def set_news_searcher(fn) -> None:
    """Tests inject `fn(query, tickers, days, k) -> list[story]`; None restores the real news search."""
    global _news_searcher
    _news_searcher = fn


def news_search(query: str, tickers: list[str] | None = None, days: int | None = None, k: int | None = None) -> list[dict]:
    """Top-k indexed news stories for the query, newest window first filtered by `days` and `tickers`; each a payload dict with
    `score`. Returns [] when nothing has been indexed yet; raises if Qdrant itself fails."""
    from src.core.config import get_config
    cfg = get_config()["news_index"]
    days, k = days or cfg["default_days"], k or cfg["top_k"]
    if _news_searcher is not None:
        return _news_searcher(query, tickers, days, k)
    from src.rag import news
    return news.search(_kb_client(), query, tickers=tickers, days=days, k=k)


_news_indexer = None          # tests inject fn(symbol, items) -> int; None = index into Qdrant now


def set_news_indexer(fn) -> None:
    global _news_indexer
    _news_indexer = fn


def news_index_now(symbol: str, items: list[dict]) -> int:
    """Index freshly fetched stories right away (the background listener would be too late for a question asked now). Returns how many were new."""
    if _news_indexer is not None:
        return _news_indexer(symbol, items)
    from src.rag import news
    return news.ingest(symbol, items, client=_kb_client())


def news_latest(db, symbol: str | None) -> dict:
    """Live (5-minute cached) Yahoo headlines for one ticker, or the general market feed when `symbol` is None. Returns the
    market-service envelope; raises SymbolNotFound if there is no feed."""
    from src.core.market_service import MARKET_NEWS
    return get_market_data(db, "news", symbol or MARKET_NEWS)


def market_quotes(db, symbols: list[str]) -> tuple[list[dict], list[str]]:
    """Quotes as market-service envelopes, plus the symbols we don't have."""
    found, missing = [], []
    for sym in symbols:
        try:
            found.append(get_market_data(db, "quote", sym))
        except SymbolNotFound:
            missing.append(sym)
    return found, missing


__all__ = ["wiki_search", "wiki_topic", "kb_search", "news_search", "news_latest", "news_index_now", "resolve_symbol", "industry_peers", "market_quotes", "set_wiki_client", "set_kb_searcher", "set_news_searcher", "set_news_indexer", "get_wiki_client", "WikiUnavailable"]
