"""What a market or news question is about: the companies and markets it names, its topic, and what it rules out.

The bundled instrument list is small, so a company the router has never heard of ("Palantir") is looked up on Yahoo instead of being
treated as an ordinary word, and a market ("forex", "gold", "Europe vs USD") in the market directory (src/rag/markets.py). With an
LLM one call finds all of it (`SUBJECT_SYSTEM`), and an empty answer is final: "any news about forex?" names no company, so no
phrasing cue may turn "forex" or "Any" into one (but an empty answer given with the conversation is checked once against the
message alone, unless the message points back at it). Without an LLM (or when its reply is unusable), phrasing cues such as "news on X",
"X stock" and "price of X" find the companies and `markets.in_text` the markets."""
from __future__ import annotations

import difflib
import json
import re

from src.core.llm import ask_llm, current_llm
from src.core.market_service import resolve_symbol
from src.rag import markets as MK

from . import history as H

SUBJECT_SYSTEM = (
    "Find what the latest message to a finance assistant is about. Reply with ONLY JSON: "
    "{\"companies\": [], \"markets\": [], \"topic\": null, \"excluded\": []}.\n"
    "companies: the publicly traded companies, ETFs or ticker symbols it names. Use the name "
    "the user wrote, but correct an obvious misspelling to the real company name (\"nvdia\" -> \"NVIDIA\"). If the message names a "
    "company at all, list that name even if you don't recognise it; never swap it for a company from earlier. A ticker symbol in capitals "
    "(\"NU\", \"AAPL\") is a company, however short. Use the recent "
    "conversation only when the message names no company or market and points back at one (\"them\", \"it\", \"that company\", \"the same "
    "sector\", or a follow-up such as \"grab the recent news\"); then name only the company discussed most recently, unless the "
    "message compares (\"which stock did better?\", \"compare them\"): then name every company the last answer covered. Do not list "
    "countries, people, central banks, markets or general topics here.\n"
    "markets: markets that are not a company, in plain words: currencies and currency pairs (\"forex\", \"EUR/USD\", \"Japanese yen\", "
    "\"US dollar index\"), crypto (\"crypto\", \"Bitcoin\"), commodities (\"gold\", \"crude oil\"), interest rates and bonds "
    "(\"10-year Treasury yield\", \"bonds\"), stock indices (\"S&P 500\", \"Nikkei\", \"the US stock market\") and sectors "
    "(\"tech sector\", \"communication services\", \"retail sector\", \"bank stocks\", \"healthcare\", \"energy stocks\"): a sector is a "
    "market, never a company and never only a topic. \"technology sector news\" names the market \"technology sector\". \"Europe vs USD\" means \"EUR/USD\". \"The market\" or \"markets\" on their own mean \"the US stock market\" "
    "when the message asks about its state (how it is doing, an update, overview, recap or insights); a concept or strategy that mentions the market (\"market cap\", \"timing the market\") names no market. "
    "List only markets the message itself names or points back at, never ones that merely appear in earlier answers.\n"
    "topic: what the news or question is about beyond those companies and markets as a short phrase (\"contracts\", \"rate cuts\", "
    "\"chip export restrictions\"); null when it just wants the latest news or figures (\"any news about forex?\", \"summarize today's "
    "news\", \"how is gold doing?\"). Time words (\"today\", \"earlier\", \"this week\") are not a topic.\n"
    "excluded: companies or markets the user says they don't want (\"not looking for DHSB news\" -> [\"DHSB\"], \"other than Apple\"); "
    "never list those under companies or markets.\n"
    "Use empty lists when there are none.")
MENTION_SYSTEM = SUBJECT_SYSTEM
_CAPS = re.compile(r"\b[A-Z]{2,5}\b")
_SINGULAR = re.compile(r"\b(it|its|that|this)\b", re.I)
_PLURAL = re.compile(r"\b(they|them|their|these|those|both|all|each)\b", re.I)
_COMPARES = re.compile(r"\b(which|better|worse|best|worst|compare\w*|versus|vs|outperform\w*|both|either)\b", re.I)
COMPARES = _COMPARES
_REFERS_BACK = re.compile(r"\b(they|them|their|it|its|that|this|those|these|same|there)\b", re.I)
_NOT_COMPANIES = set("""the a an my our this that these those it its they them market markets stock stocks share shares today tonight
week month year news headline headlines latest recent update updates price prices quote quotes what whats how why when who where
day days morning afternoon evening night hour hours moment weekend quarter
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
# "not looking for DHSB news", "I don't want Tesla", "other than Apple": a company the user rules out. "no" is left out: "no Apple news?" asks for it.
_EXCLUDED = re.compile(r"(?:\b(?:not|except|excluding|other than|instead of|rather than|apart from|aside from|forget|skip|without|ignore)|n't)\s+"
                       r"(?:(?:looking|interested|asking|want\w*|need\w*|care|caring|about|for|in|on|into|the|any|more|news|headlines?|stories|regarding)\s+){0,4}"
                       r"\$?([A-Za-z][\w&.\-]*)", re.I)
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
    return list(dict.fromkeys(c for c in map(_clean, found + ticker_mentions(text) + lowercase_mentions(text)) if c))


# Without an LLM nothing capitalises "tesla": a lowercase name counts next to a cue ("tesla stock", "how's tesla doing")
# and only for the best-known companies, as many names are everyday words ("visa", "target", "gap").
LOWERCASE_RANK = 500
_STOCK_KINDS = set("""common preferred growth value dividend income penny meme blue first best top good great new any which single
individual foreign international domestic cheap safe defensive cyclical small large mid big one two few some each every company""".split())
_LOWER_BEFORE = re.compile(r"\b([a-z][a-z&.\-]{2,})\s+(?:stock|shares|share price|stock price)\b")
_LOWER_DOING = re.compile(r"\bho'?w'?(?:s|\s+is|\s+are)?\s+([a-z][a-z&.\-]{2,})(?:\s+(?:stock|shares))?\s+(?:doing|performing|trading)\b")


def lowercase_mentions(text: str) -> list[str]:
    """Tickers of well-known companies the message names in lower case next to a cue word: "ho'ws tesla stock doing?" → TSLA.
    Funds are left out (their names are generic words: "total", "growth")."""
    from src.rag.tickers import get_directory
    d, found = get_directory(), []
    for pattern in (_LOWER_BEFORE, _LOWER_DOING):
        for m in pattern.finditer(text):
            word = m.group(1)
            if word in _NOT_COMPANIES or word in _ACRONYMS or word in _STOCK_KINDS:     # "growth stock", "first stock"
                continue
            hits = [r for r in d.by_name(word) if r["asset_type"] != "etf"]
            if hits and hits[0]["rank"] < LOWERCASE_RANK:
                found.append(hits[0]["symbol"])
    return list(dict.fromkeys(found))


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


def excluded(text: str) -> set[str]:
    """Lower-case names and tickers the message rules out ("not looking for DHSB news" → {"dhsb"})."""
    return {m.group(1).lower().rstrip(".") for m in _EXCLUDED.finditer(text)}


def without_excluded(text: str) -> str:
    """The message with what it rules out removed, so "I'm not looking for DHSB news, just today's" is about today's news."""
    return _EXCLUDED.sub(" ", text)


def is_excluded(company: dict, ruled_out: set[str]) -> bool:
    words = {company.get("symbol", ""), company.get("mention", ""), (company.get("name") or "").split(" ")[0]}
    return bool(ruled_out) and any(w.lower().strip(",.") in ruled_out for w in words if w)


def _recent(history: list[dict] | None) -> list[dict]:
    return H.recent(history)


def _names(obj: dict, key: str) -> list[str]:
    vals = obj.get(key) or []
    return list(dict.fromkeys(c for c in (_clean(n) for n in vals if isinstance(n, str)) if c))[:3] if isinstance(vals, list) else []


def llm_subjects(text: str, history: list[dict] | None = None) -> dict | None:
    """{companies, markets, topic, excluded} from the model, names as written; None when it gave nothing usable."""
    recent = H.transcript(history)
    reply = ask_llm(SUBJECT_SYSTEM, (f"Recent conversation:\n{recent}\n\n" if recent else "") + f"Latest message: {text}") or ""
    start = reply.find("{")
    while start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(reply, start)
        except ValueError:
            start = reply.find("{", start + 1)
            continue
        if not isinstance(obj, dict):
            return None
        topic = obj.get("topic")
        raw = [n for n in (obj.get("companies") or obj.get("mentions") or []) if isinstance(n, str)]
        as_market = [n for n in raw if MK.lookup(n, meaning=False)]                  # "gold" listed as a company is a market
        companies = _names({"companies": [n for n in raw if n not in as_market]}, "companies")
        markets = [n.strip() for n in obj.get("markets") or [] if isinstance(n, str) and n.strip()]     # not `_clean`: "gold" is a market
        return {"companies": companies, "markets": list(dict.fromkeys([*markets, *as_market]))[:3],
                "topic": topic.strip() if isinstance(topic, str) and topic.strip() else "",
                "excluded": [n for n in obj.get("excluded") or [] if isinstance(n, str)]}
    return None


def llm_mentions(text: str, history: list[dict] | None = None) -> list[str]:
    return (llm_subjects(text, history) or {}).get("companies", [])


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


def _named_in(name: str, text: str) -> bool:
    """The message itself says this market: by any of its names, so "Communication Services Sector" isn't "sector" in "tech sector news"."""
    m = MK.lookup(name)
    return any(w.lower() in text.lower() for w in (MK.words(m) if m else [name]))


def _from_earlier(got: dict, text: str) -> bool:
    """The model's subjects aren't what the message says: none found, or some that can only have come from the conversation."""
    return (not got["companies"] and not got["markets"]) or not all(_in_text(n, text) for n in got["companies"]) \
        or not all(_named_in(n, text) for n in got["markets"])


def _most_recent(found: list[dict], history: list[dict] | None) -> dict:
    """Of several companies from the conversation, the one mentioned last (by ticker, name or the words the user wrote)."""
    log = " ".join(m["content"].lower() for m in _recent(history))
    def last(c: dict) -> int:
        words = {c["symbol"].lower(), c["mention"].lower(), c["name"].split()[0].lower().strip(",.")}
        return max((m.end() for w in words for m in re.finditer(rf"\b{re.escape(w)}\b", log)), default=-1)
    return max(found, key=last)


def subjects(text: str, use_llm: bool = True, history: list[dict] | None = None) -> dict:
    """What the message is about: {companies: [{symbol, name, mention}], markets: [markets.market / markets.group], levels, topic,
    excluded}. At most 3 companies and 3 markets; `levels` is what they cover (see `levels`). `topic` is the model's ("" = just the latest), or None without an LLM (the news agent then
    reads it from the words). `excluded` is lower-case names and symbols the user ruled out. `history` lets "them" / "the same sector"
    mean the company discussed earlier; without an LLM that works for the last question only."""
    use_llm = use_llm and current_llm() is not None
    key = (text, use_llm, tuple(m["content"] for m in _recent(history)))
    if key not in _cache:
        got = llm_subjects(text, history) if use_llm else None
        if (got is not None and _from_earlier(got, text) and _recent(history)
                and not _REFERS_BACK.search(text) and not _COMPARES.search(text)):
            # The earlier conversation can crowd out what the message itself names ("can you show Google news?" after a run of
            # Apple answers came back empty, "technology sector news" came back as the sector and index of the answer before).
            # A message that doesn't point back is read again on its own.
            alone = llm_subjects(text)
            if alone is not None and (alone["companies"] or alone["markets"]):
                got = alone
            elif own := MK.in_text(without_excluded(text)):        # the model missed it even so; the directory knows the name
                got = {**got, "companies": [], "markets": [m["name"] for m in own]}
        ruled_out = excluded(text) | {n.lower() for n in (got or {}).get("excluded", [])}
        plain = without_excluded(text)
        if got is not None:                                # the model answered: an empty list means none, not "try the cues"
            names, market_names = _grounded(got["companies"], text), got["markets"]
            markets = [m for m in (MK.lookup(n) for n in market_names) if m]
            if names or markets:                           # alongside what it took from the conversation, what the message itself names
                markets = [*MK.in_text(plain), *markets]
        else:
            names = keyword_mentions(plain)
            markets = MK.in_text(plain)
        moved = [m for m in (MK.lookup(n, meaning=False) for n in names) if m]       # "forex" or "gold" given as a company
        names = [n for n in names if not MK.lookup(n, meaning=False) and n.lower() not in ruled_out]
        markets = [m for m in [*markets, *moved] if not _ruled_out_market(m, ruled_out)]
        markets = list({m["key"]: m for m in markets}.values())[:3]
        if not names and not markets and got is None and _REFERS_BACK.search(text):
            names = next((n for n in (keyword_mentions(m["content"]) for m in reversed(_recent(history)) if m["role"] == "user") if n), [])
        if not names and not markets and _COMPARES.search(text):     # "which stock did better?": the tickers the last answer covered
            names = next((n for n in (ticker_mentions(m["content"]) for m in reversed(_recent(history)) if m["role"] == "assistant") if n), [])
        out = []
        for n in names[:3]:
            hit = resolve_symbol(n)
            if hit and all(hit["symbol"] != o["symbol"] for o in out) and not is_excluded({**hit, "mention": n}, ruled_out):
                out.append({**hit, "mention": n})
        if len(out) > 1 and not any(_in_text(o["mention"], text) for o in out) and _SINGULAR.search(text) and not _PLURAL.search(text):
            out = [_most_recent(out, history)]            # "its price" means one company: the one talked about last
        _cache[key] = {"companies": out, "markets": markets, "levels": levels(out, markets),
                       "topic": got["topic"] if got is not None else None, "excluded": ruled_out}
    return _cache[key]


def levels(companies: list[dict], markets: list[dict]) -> list[str]:
    """What the subjects cover, in markets.LEVELS order: ["sector"] for "the tech sector", ["company", "market"] for "NVDA vs the
    market". Decided here once, so the router, the market and news agents, replan and the saved context all read the same."""
    found = {"company"} if companies else set()
    found |= {m.get("level") or MK.level_of(m["group"]) for m in markets}
    return [lv for lv in MK.LEVELS if lv in found]


def _ruled_out_market(m: dict, ruled_out: set[str]) -> bool:
    return any(MK.norm(w) in {MK.norm(r) for r in ruled_out} for w in (m["key"], m["name"], m["group"]))


def resolve(text: str, use_llm: bool = True, history: list[dict] | None = None) -> list[dict]:
    """[{symbol, name, mention}] for the companies the message names, at most 3 (see `subjects`)."""
    return subjects(text, use_llm, history)["companies"]
