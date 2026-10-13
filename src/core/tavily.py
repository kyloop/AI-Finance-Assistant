"""Tavily web search: Research's last resort, after the knowledge base and Wikipedia have nothing that answers the question.

Only the (proofread) question is sent, never the conversation or the portfolio. Results are page extracts with their URLs;
Tavily's own generated answer is not requested, so every sentence can be traced to a source and checked by the verifier.
Needs TAVILY_API_KEY in .env and `tavily.enabled` in config.yaml; without them `web_search_enabled()` is False and Research
behaves as before. Tests inject a fake with `set_web_searcher` and never reach the network."""
from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

from src.core.config import get_config

API_URL = "https://api.tavily.com/search"
MAX_QUERY_CHARS = 400


class WebSearchUnavailable(Exception):
    """Network trouble, a timeout, a bad key or an exhausted plan: Research says it found nothing rather than failing."""


_searcher = None                   # tests: fn(query) -> list of {title, url, content, score}


def set_web_searcher(fn) -> None:
    """Tests inject `fn(query) -> [{title, url, content, score}]`; None restores the real API."""
    global _searcher
    _searcher = fn


def _cfg() -> dict:
    return get_config().get("tavily") or {}


def web_search_enabled() -> bool:
    return bool(_cfg().get("enabled", True)) and (_searcher is not None or bool(os.environ.get("TAVILY_API_KEY")))


def _fetch(query: str, transport: httpx.BaseTransport | None = None) -> list[dict]:
    cfg = _cfg()
    body = {"query": query, "search_depth": cfg.get("search_depth", "basic"), "max_results": int(cfg.get("max_results", 5)),
            "topic": "general", "include_answer": False, "include_raw_content": False,
            "exclude_domains": list(cfg.get("exclude_domains") or [])}
    headers = {"Authorization": f"Bearer {os.environ.get('TAVILY_API_KEY', '')}"}
    try:
        with httpx.Client(timeout=float(cfg.get("timeout_seconds", 15)), transport=transport) as http:
            r = http.post(API_URL, json=body, headers=headers)
    except httpx.HTTPError as e:
        raise WebSearchUnavailable(type(e).__name__) from e
    if r.status_code == 401:
        raise WebSearchUnavailable("API key rejected (check TAVILY_API_KEY)")
    if r.status_code in (429, 432, 433):
        raise WebSearchUnavailable("rate or plan limit reached")
    if r.status_code != 200:
        raise WebSearchUnavailable(f"HTTP {r.status_code}")
    try:
        return r.json().get("results") or []
    except ValueError as e:
        raise WebSearchUnavailable("unreadable response") from e


def domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


def web_search(query: str, transport: httpx.BaseTransport | None = None) -> list[dict]:
    """Up to `tavily.max_results` results at or above `tavily.min_score`, best first, each {title, url, domain, content, score}.
    Raises WebSearchUnavailable."""
    q = " ".join(str(query).split())[:MAX_QUERY_CHARS]
    raw = _searcher(q) if _searcher is not None else _fetch(q, transport)
    cfg = _cfg()
    floor, excluded = float(cfg.get("min_score", 0.3)), {d.lower() for d in cfg.get("exclude_domains") or []}
    out = []
    for r in sorted(raw, key=lambda r: -(r.get("score") or 0)):
        url, content = str(r.get("url") or ""), " ".join(str(r.get("content") or "").split())
        d = domain(url)
        if not url.startswith(("https://", "http://")) or not content or (r.get("score") or 0) < floor:
            continue
        if any(d == x or d.endswith("." + x) for x in excluded):              # also enforced here, not only by Tavily
            continue
        out.append({"title": str(r.get("title") or d).strip(), "url": url, "domain": d, "content": content, "score": r.get("score") or 0})
    return out[:int(cfg.get("max_results", 5))]
