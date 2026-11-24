"""Market directory: currencies, crypto, commodities, rates, indices and sectors as Yahoo symbols, from `src/data/markets.yaml`.

The ticker directory (tickers.py) only knows listed companies and ETFs, so "forex", "gold" or "Europe vs USD" found nothing there
(or a look-alike ETF). These entries share the `finnie_symbols` Qdrant collection with the companies, as `asset_type: market`
points (one per name and alias) and `market_group` points (one per group, so "forex" itself matches). Their ids are made from
"market:…" so they never overwrite a company point (the sector ETFs XLK, XLF… are both). They are written with an upsert, never by
rebuilding the collection: `python -m scripts.market_symbols` (dry run by default).

Lookup order in `lookup(text)`, each result a market (one symbol) or a group (forex, crypto…):
  1. exact            "USD---JPY", "yen", "dxy", "forex"    any symbol, name, alias or code, compared without case or punctuation
  2. misspelt         "etherium", "japanes yen"             character similarity to the names and aliases (5+ letters only)
  3. same meaning     "Europe vs USD"                       Qdrant search over the market points, min_score and a clear winner
`in_text(text)` finds the markets a message names without an LLM (basic mode)."""
from __future__ import annotations

import difflib
import logging
import re
import uuid
from functools import lru_cache
from pathlib import Path

import yaml

from src.core.config import ROOT

log = logging.getLogger(__name__)

MARKET, GROUP = "market", "market_group"
GROUP_QUOTES = 4                 # a group ("forex") is quoted by its first few symbols
# Names that are also everyday words: found by `in_text` only when capitalised mid-sentence (basic mode has no LLM to tell)
_EVERYDAY = {"stellar", "ripple", "tron", "ether", "brent", "the market", "utilities", "financials", "cable", "sterling", "rice",
             "sugar", "cotton", "corn", "coffee", "hogs", "cattle", "wheat", "silver", "copper", "oil", "gold"}
_COMMON_ANYWAY = {"gold", "oil", "silver", "copper"}     # ...except these, which in a finance question nearly always mean the market


def yaml_path() -> Path:
    return ROOT / "src" / "data" / "markets.yaml"


def norm(text: str) -> str:
    """"USD---JPY", "usd/jpy" and "USDJPY" all become "usdjpy"; "S&P 500" becomes "s&p500"."""
    return re.sub(r"[^a-z0-9&]", "", text.lower())


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> dict[str, dict]:
    """{group: {label, aliases, news, symbols: [{symbol, name, aliases, codes, news, etf, yahoo, region}]}}, with defaults filled in."""
    data = yaml.safe_load((path or yaml_path()).read_text())
    for g in data.values():
        g.setdefault("aliases", [])
        g.setdefault("news", [])
        for s in g["symbols"]:
            s.setdefault("aliases", [])
            s.setdefault("codes", [])
            s.setdefault("news", None)
            s.setdefault("etf", None)
            s.setdefault("yahoo", None)
            s.setdefault("region", None)
    return data


def sectors() -> list[dict]:
    """The 11 US sectors as {symbol (its SPDR fund), name, yahoo (yf.Sector key)}, in markets.yaml order."""
    return [{"symbol": e["symbol"], "name": e["name"], "yahoo": e["yahoo"]} for e in entries() if e["group"] == "sectors"]


def regions() -> list[dict]:
    """The main stock index of each country or area: {symbol, name, region}."""
    return [{"symbol": e["symbol"], "name": e["name"], "region": e["region"]} for e in entries() if e["region"]]


def entries(data: dict | None = None) -> list[dict]:
    """Every symbol as a flat record with its group."""
    data = data or load()
    return [{**s, "group": g} for g, grp in data.items() for s in grp["symbols"]]


def exact_table(data: dict | None = None) -> dict[str, dict]:
    """norm(text) -> {"symbol": …} or {"group": …} for every symbol, name, alias, code and group alias. Groups win nothing:
    a clash between two entries is a mistake in the YAML, reported by `clashes`."""
    data = data or load()
    table = {}
    for g, grp in data.items():
        for a in [g, grp["label"], *grp["aliases"]]:
            table.setdefault(norm(a), {"group": g})
        for s in grp["symbols"]:
            for a in [s["symbol"], s["name"], *s["aliases"], *s["codes"]]:
                table.setdefault(norm(a), {"symbol": s["symbol"], "group": g})
    return table


def clashes(data: dict | None = None) -> list[tuple[str, list[str]]]:
    """Normalised texts that more than one entry claims (each must lead to one place)."""
    data = data or load()
    seen: dict[str, set[str]] = {}
    for g, grp in data.items():
        for a in [g, grp["label"], *grp["aliases"]]:
            seen.setdefault(norm(a), set()).add(f"group:{g}")
        for s in grp["symbols"]:
            for a in [s["symbol"], s["name"], *s["aliases"], *s["codes"]]:
                seen.setdefault(norm(a), set()).add(s["symbol"])
    return sorted((k, sorted(v)) for k, v in seen.items() if len(v) > 1)


def point_id(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "market:" + ":".join(parts)))


def points(data: dict | None = None) -> list[dict]:
    """The Qdrant points as {id, text, payload}; `text` is what gets embedded. One per symbol name and readable alias (codes are
    exact-match only), and one per group made of its label and aliases."""
    data = data or load()
    out = []
    for g, grp in data.items():
        out.append({"id": point_id("group", g), "text": ", ".join([grp["label"], *grp["aliases"]]),
                    "payload": {"asset_type": GROUP, "group": g, "name": grp["label"], "news": grp["news"]}})
        for s in grp["symbols"]:
            base = {"asset_type": MARKET, "group": g, "symbol": s["symbol"], "name": s["name"], "news": s["news"], "etf": s["etf"]}
            texts = list({norm(t): t for t in reversed([s["name"], *s["aliases"]])}.values())[::-1]     # "Bitcoin"/"bitcoin": one point
            out += [{"id": point_id(s["symbol"], norm(t)), "text": t, "payload": {**base, "alias": t}} for t in texts]
    return out


def entry(symbol: str) -> dict | None:
    return next((e for e in entries() if e["symbol"] == symbol), None)


def market(symbol: str) -> dict:
    """A symbol as a subject: {kind, key, symbol, name, group, quotes, news}. `news` is the Yahoo search terms for its headlines
    (its own term, else its ETF); `quotes` the symbols to price."""
    e = entry(symbol)
    news = [e["news"]] if e["news"] else [e["etf"]] if e["etf"] else []
    return {"kind": MARKET, "key": symbol, "symbol": symbol, "name": e["name"], "group": e["group"], "quotes": [symbol], "news": news}


def group(key: str) -> dict:
    g = load()[key]
    return {"kind": GROUP, "key": f"group:{key}", "symbol": None, "name": g["label"], "group": key,
            "quotes": [s["symbol"] for s in g["symbols"][:GROUP_QUOTES]], "news": list(g["news"])}


def words(subject: dict) -> list[str]:
    """Every name the user may have used for a market or group ("forex", "fx", "currencies"): part of the subject, not a topic."""
    if subject["kind"] == GROUP:
        g = load()[subject["group"]]
        return [subject["group"], g["label"], *g["aliases"]]
    e = entry(subject["symbol"])
    return [e["symbol"], e["name"], *e["aliases"], *e["codes"]]


def _subject(hit: dict) -> dict:
    return market(hit["symbol"]) if hit.get("symbol") else group(hit["group"])


def lookup_exact(text: str) -> dict | None:
    hit = exact_table().get(norm(text))
    return _subject(hit) if hit else None


def _close(text: str) -> dict | None:
    key = norm(text)
    if len(key) < 5:
        return None
    table = exact_table()
    found = difflib.get_close_matches(key, [k for k in table if len(k) >= 5], n=1, cutoff=0.85)
    return _subject(table[found[0]]) if found else None


_searcher = None                 # tests inject fn(query, k) -> [payload + score]; None = the Qdrant collection


def set_market_searcher(fn) -> None:
    global _searcher
    _searcher = fn


def _search(query: str, k: int) -> list[dict]:
    if _searcher:
        return _searcher(query, k)
    from qdrant_client import models

    from src.core.config import get_config
    from src.workflow.tools import _kb_client

    from .store import QDRANT_LOCK, get_embedder
    qvec = next(iter(get_embedder().embed([query]))).tolist()
    only = models.Filter(must=[models.FieldCondition(key="asset_type", match=models.MatchAny(any=[MARKET, GROUP]))])
    with QDRANT_LOCK:
        hits = _kb_client().query_points(get_config()["symbols_index"]["collection"], query=qvec, query_filter=only, limit=k,
                                         with_payload=True).points
    return [{**h.payload, "score": h.score} for h in hits]


def lookup(text: str, meaning: bool = True) -> dict | None:
    """The market or group `text` names, or None. The meaning search answers only when one market is clearly best: every hit
    within `score_margin` of the best must be the same symbol or group."""
    found = lookup_exact(text) or _close(text)
    if found or not meaning or len(norm(text)) < 4:
        return found
    try:
        hits = _search(text, 5)
    except Exception:  # noqa: BLE001 — the index may be unreachable; a miss is fine
        log.warning("market name search unavailable", exc_info=True)
        return None
    from src.core.config import get_config
    cfg = get_config()["symbols_index"]
    if not hits or hits[0]["score"] < cfg["min_score"]:
        return None
    key = lambda h: h.get("symbol") or f"group:{h['group']}"                    # noqa: E731
    if any(key(h) != key(hits[0]) for h in hits[1:] if hits[0]["score"] - h["score"] <= cfg["score_margin"]):
        return None
    return _subject(hits[0])


@lru_cache(maxsize=1)
def _scan_pattern() -> re.Pattern:
    texts = {t for g, grp in load().items() for t in [grp["label"], *grp["aliases"]]}
    texts |= {t for e in entries() for t in [e["name"], *e["aliases"]]}
    texts = sorted((t for t in texts if len(t) >= 3), key=len, reverse=True)       # longest first: "oil stocks" before "oil"
    return re.compile(r"(?<![\w&])(" + "|".join(re.escape(t) for t in texts) + r")(?![\w&])", re.I)


_CODE = re.compile(r"(?<![\w$])([A-Z]{3,4})(?![\w])")


def in_text(text: str) -> list[dict]:
    """Markets a message names, found without an LLM: names and aliases as whole words (longest first), and codes written in
    capitals ("BTC", "DXY"). Everyday words ("sugar", "Stellar") count only when written with a capital mid-sentence."""
    out = []
    for m in _scan_pattern().finditer(text):
        word = m.group(1)
        if word.lower() in _EVERYDAY and word.lower() not in _COMMON_ANYWAY and not (word[:1].isupper() and m.start() > 0):
            continue
        out.append(lookup_exact(word))
    codes = {norm(c) for e in entries() for c in e["codes"]}
    out += [lookup_exact(m.group(1)) for m in _CODE.finditer(text) if m.group(1).lower() in codes]
    seen, uniq = set(), []
    for s in out:
        if s and s["key"] not in seen:
            seen.add(s["key"])
            uniq.append(s)
    return uniq


# ---- news: which stories belong to which market ----------------------------------------------------------------
MARKET_FEED = "MARKET"            # market_service's pseudo-symbol for the US market feed (^GSPC, ^IXIC, ^DJI)


@lru_cache(maxsize=1)
def _term_groups() -> dict[str, set[str]]:
    """Upper-cased Yahoo news term -> the groups whose headlines it fetches."""
    out: dict[str, set[str]] = {MARKET_FEED: {"us_indices"}}
    for g, grp in load().items():
        for t in [*grp["news"], *(e["news"] for e in grp["symbols"] if e["news"]), *(e["etf"] for e in grp["symbols"] if e["etf"])]:
            out.setdefault(t.upper(), set()).add(g)
    return out


def is_news_term(term: str) -> bool:
    return term.upper() in _term_groups()


def news_tags(term: str | None) -> list[str]:
    """Tags for the stories fetched with `term`, besides the term itself: "market:forex" for anything fetched for a forex market."""
    return sorted(f"market:{g}" for g in _term_groups().get((term or "").upper(), ()))


def search_tags(subject: dict) -> list[str]:
    """The story tags a news search filters on: a market's own news terms, or every story of a group."""
    return [f"market:{subject['group']}"] if subject["kind"] == GROUP else [t.upper() for t in subject["news"]]


def news_term_for(symbol: str) -> str | None:
    """What the background news poll fetches for a recently quoted or searched symbol: a market symbol's news term (None when it
    has no news), anything else unchanged."""
    e = entry(symbol) or entry(symbol.upper())
    if e is None:
        return symbol
    return e["news"] or e["etf"]
