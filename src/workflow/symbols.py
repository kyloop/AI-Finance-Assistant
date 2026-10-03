"""Company and ticker mentions: find them in a message and resolve them to Yahoo symbols.

The bundled instrument list is small, so a company the router has never heard of ("Palantir") is looked up on Yahoo instead of being
treated as an ordinary word. With an LLM the mentions are extracted by the model; without one, by phrasing cues such as "news on X",
"X stock" and "price of X"."""
from __future__ import annotations

import difflib
import json
import re

from src.core.llm import ask_llm, current_llm
from src.core.market_service import resolve_symbol

from . import history as H

MENTION_SYSTEM = (
    "Find the publicly traded companies, ETFs or ticker symbols that the latest message to a finance assistant is about. Use the name "
    "the user wrote, but correct an obvious misspelling to the real company name (\"nvdia\" -> \"NVIDIA\"). If the message names a "
    "company at all, list that name even if you don't recognise it; never swap it for a company from earlier. A ticker symbol in capitals "
    "(\"NU\", \"AAPL\") is a company, however short. Use the recent "
    "conversation only when the message names no company and points back at one (\"them\", \"it\", \"that company\", \"the same "
    "sector\", or a follow-up such as \"grab the recent news\"); then name only the company discussed most recently, unless the "
    "message compares (\"which stock did better?\", \"compare them\"): then name every company the last answer covered. Do not list countries, people, "
    "central banks or general topics. Reply with ONLY JSON: {\"mentions\": [\"Palantir\"]}; use an empty list if there are none.")
_CAPS = re.compile(r"\b[A-Z]{2,5}\b")
_SINGULAR = re.compile(r"\b(it|its|that|this)\b", re.I)
_PLURAL = re.compile(r"\b(they|them|their|these|those|both|all|each)\b", re.I)
_COMPARES = re.compile(r"\b(which|better|worse|best|worst|compare\w*|versus|vs|outperform\w*|both|either)\b", re.I)
COMPARES = _COMPARES
_REFERS_BACK = re.compile(r"\b(they|them|their|it|its|that|this|those|these|same|there)\b", re.I)
_NOT_COMPANIES = set("""the a an my our this that these those it its they them market markets stock stocks share shares today tonight
week month year news headline headlines latest recent update updates price prices quote quotes what whats how why when who where
january february march april may june july august september october november december monday tuesday wednesday thursday friday
fed federal reserve white house wall street ai etf etfs ipo ceo cfo us usa s&p nasdaq dow gdp cpi pce
chip chips semiconductor semiconductors oil gas gold silver copper tech technology bank banks energy healthcare tariff tariffs rates inflation
earnings economy economic recession crypto sector sectors export exports ira roth apr apy eps roi ytd sec""".split())
_CUE = re.compile(r"\b(?:news|headlines?|latest|updates?|price|prices|quote|stock|shares?|happening|going on|said|reported)\s+"
                  r"(?:on|about|for|of|with|at)\s+(?:the\s+)?([A-Za-z][^\s,.?!;:]*(?:\s+[^\s,.?!;:]+){0,3})", re.I)
_BEFORE = re.compile(r"\b([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,2})\s+(?:stock|shares|share price|news|headlines?)\b")
_TICKER_WORD = re.compile(r"\b(?:ticker|symbol)(?:\s+symbol)?(?:\s+(?:is|of|for))?\s+\$?([A-Za-z]{1,5})\b", re.I)      # "the company with ticker SDEV"
_ACRONYMS = set("""reit reits fdic cd cds dca hsa fsa nav fire roe pe peg ebitda sipc finra irs ytd mtd qtd ach ira roth ssa fica cola
llc inc corp ltd ok usd eur gbp jpy""".split())
_cache: dict[tuple, list[dict]] = {}


def clear_cache() -> None:
    _cache.clear()


def _clean(name: str) -> str | None:
    name = re.sub(r"['’]s$", "", name.strip(" '\"“”.,"))
    words = name.split()
    return name if words and not all(w.lower() in _NOT_COMPANIES for w in words) and len(name) > 1 else None


def keyword_mentions(text: str) -> list[str]:
    """Names found by phrasing cues: after "news on / price of / latest about…" (lower case allowed, one word, then further capitalised
    words) and capitalised names before "stock / shares / news"."""
    found = []
    for m in _CUE.finditer(text):
        words = m.group(1).split()
        name = [words[0]]
        for w in words[1:]:                                    # a company name continues only through capitalised words
            if w[:1].isupper() and w.lower() not in _NOT_COMPANIES:
                name.append(w)
            else:
                break
        found.append(" ".join(name))
    found += [m.group(1) for m in _BEFORE.finditer(text)]
    return list(dict.fromkeys(c for c in map(_clean, found + ticker_mentions(text)) if c))


def ticker_mentions(text: str) -> list[str]:
    """Listed tickers the message names: after "ticker" / "symbol" (any case, any US listing), or written in capitals when the SEC ranks the
    company ("what about SDEV?"). Capitalised acronyms (REIT, FDIC) and all-capitals messages don't count. Checked against the ticker
    directory, so a made-up "ticker ZZZZ" finds nothing."""
    from src.rag.tickers import NO_RANK, get_directory
    d = get_directory()
    found = [m.group(1) for m in _TICKER_WORD.finditer(text) if d.exact(m.group(1))]
    if not text.isupper():
        for m in re.finditer(r"\$?\b([A-Z]{2,5})\b", text):
            r = d.exact(m.group(1))
            if r and r["rank"] < NO_RANK:
                found.append(m.group(1))
    return list(dict.fromkeys(t.upper() for t in found if t.lower() not in _NOT_COMPANIES | _ACRONYMS))


def _recent(history: list[dict] | None) -> list[dict]:
    return H.recent(history)


def llm_mentions(text: str, history: list[dict] | None = None) -> list[str]:
    recent = H.transcript(history)
    reply = ask_llm(MENTION_SYSTEM, (f"Recent conversation:\n{recent}\n\n" if recent else "") + f"Latest message: {text}") or ""
    start = reply.find("{")
    while start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(reply, start)
            names = obj.get("mentions", []) if isinstance(obj, dict) else []
            return list(dict.fromkeys(c for c in (_clean(n) for n in names if isinstance(n, str)) if c))[:3]
        except ValueError:
            start = reply.find("{", start + 1)
    return []


def _in_text(name: str, text: str) -> bool:
    """The user's message contains this name, allowing for a typo ("nvdia" for NVIDIA)."""
    words = re.findall(r"[a-z0-9&]+", text.lower())
    return name.lower() in text.lower() or any(difflib.get_close_matches(w, words, n=1, cutoff=0.75) for w in re.findall(r"[a-z0-9&]+", name.lower()) if len(w) >= 4)


def _grounded(names: list[str], text: str) -> list[str]:
    """Drop a company the model took from earlier in the conversation when the message itself names something else: either
    through a phrasing cue ("price of foobarbaz") or as a capitalised ticker ("what about NU?"). It must not quietly become
    the stock discussed before. Returns the mentions that really are in the message, or what the message names itself."""
    kept = [n for n in names if _in_text(n, text)]
    if len(kept) == len(names):
        return names
    named = keyword_mentions(text) or [t for t in _CAPS.findall(text) if t.lower() not in _NOT_COMPANIES]
    return kept or named if named else names


def _most_recent(found: list[dict], history: list[dict] | None) -> dict:
    """Of several companies from the conversation, the one mentioned last (by ticker, name or the words the user wrote)."""
    log = " ".join(m["content"].lower() for m in _recent(history))
    def last(c: dict) -> int:
        words = {c["symbol"].lower(), c["mention"].lower(), c["name"].split()[0].lower().strip(",.")}
        return max((m.end() for w in words for m in re.finditer(rf"\b{re.escape(w)}\b", log)), default=-1)
    return max(found, key=last)


def resolve(text: str, use_llm: bool = True, history: list[dict] | None = None) -> list[dict]:
    """[{symbol, name, mention}] for the companies the message names, at most 3. Looks each name up on Yahoo (see market_service.resolve_symbol).
    `history` lets "them" / "the same sector" mean the company discussed earlier; without an LLM that works for the last question only."""
    use_llm = use_llm and current_llm() is not None
    key = (text, use_llm, tuple(m["content"] for m in _recent(history)))
    if key not in _cache:
        names = (_grounded(llm_mentions(text, history), text) if use_llm else []) or keyword_mentions(text)
        if not names and not use_llm and _REFERS_BACK.search(text):
            names = next((n for n in (keyword_mentions(m["content"]) for m in reversed(_recent(history)) if m["role"] == "user") if n), [])
        if not names and _COMPARES.search(text):           # "which stock did better?": the tickers the last answer covered
            names = next((n for n in (ticker_mentions(m["content"]) for m in reversed(_recent(history)) if m["role"] == "assistant") if n), [])
        out = []
        for n in names[:3]:
            hit = resolve_symbol(n)
            if hit and all(hit["symbol"] != o["symbol"] for o in out):
                out.append({**hit, "mention": n})
        if len(out) > 1 and not any(_in_text(o["mention"], text) for o in out) and _SINGULAR.search(text) and not _PLURAL.search(text):
            out = [_most_recent(out, history)]            # "its price" means one company: the one talked about last
        _cache[key] = out
    return _cache[key]
