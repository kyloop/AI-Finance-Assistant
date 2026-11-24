"""Market tools for the market agent: a small set of typed functions over market_service, never raw yfinance.

Each tool reads through `get_market_data`, so the cache (TTL per endpoint in config.yaml), the stale-cache and sample-data
fallbacks and the offline tests all apply. Each returns `{symbol: {section: {...}}}` with sections `quote`, `period`,
`profile` or `fund` for one symbol, `sector` (a sector against the S&P 500, under its fund's symbol) or `overview` (the
indices and every sector ranked, under OVERVIEW_KEY), or `error`; every figure computed in Python and labelled with its
source and time. The LLM only
picks tools and arguments (TOOL_SPECS, in the OpenAI function format that LangChain's `bind_tools` accepts for every
provider); `run_tool` validates them. `describe_lines` turns the figures into the agent's text deterministically."""
from __future__ import annotations

import difflib
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.core import market_boards as B
from src.core.market_service import NotAFund, SymbolNotFound, get_market_data

MAX_SYMBOLS = 3                            # per tool call
HISTORY_MAX_DAYS = 2520                    # ~10 years of trading days, the most the history endpoint serves
YEAR_DAYS = 400                            # covers a full year both as trading days (Yahoo) and calendar days (sample data)
SYMBOL_OK = re.compile(r"^[A-Z0-9.\-=^]{1,15}$")


class ToolError(ValueError):
    """A tool was called with arguments it can't use; the message goes back to the model."""


# ---------------------------------------------------------------- periods
_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20}
_PERIOD = re.compile(r"(?=\b(?:last|past|previous|over|in|for)\s+(?:the\s+)?(?:(\d+|" + "|".join(_NUM_WORDS) + r")\s*-?\s*)?"
                     r"([a-z]+)\b)", re.I)        # a lookahead, so "for the past 5 yrs" is also tried from "past"
_UNITS = {"decade": 3652.5, "year": 365.25, "month": 30.44, "week": 7, "day": 1}
_UNIT_ABBR = {"y": "year", "yr": "year", "yrs": "year", "m": "month", "mo": "month", "mos": "month", "mon": "month", "mons": "month",
              "mth": "month", "mths": "month", "w": "week", "wk": "week", "wks": "week", "d": "day", "dy": "day", "dys": "day"}
_ABBR_NEEDS_NUMBER = {"y", "m", "w", "d", "mon", "mons"}       # "last mon" is more likely Monday; "last 3 mon" is months
_YTD = re.compile(r"\b(ytd|year[- ]to[- ]date|this year)\b", re.I)
_SINCE = re.compile(r"\bsince\s+((?:19|20)\d\d)\b", re.I)


def _unit(word: str, numbered: bool) -> str | None:
    """year / month / week / day / decade for a unit as typed: "yrs", "mo", "10y", or a misspelling such as "yaers" or "monts"."""
    w = word.lower()
    if w in _UNIT_ABBR:
        return _UNIT_ABBR[w] if numbered or w not in _ABBR_NEEDS_NUMBER else None
    base = w[:-1] if w.endswith("s") and w[:-1] in _UNITS else w
    if base in _UNITS:
        return base
    if len(w) < 4:
        return None
    close = [u for u in difflib.get_close_matches(w, [*_UNITS, *(u + "s" for u in _UNITS)], n=3, cutoff=0.75) if abs(len(u) - len(w)) <= 1]
    return close[0].rstrip("s") if close else None          # the length check keeps "weekend" from reading as "weeks"


def asked_period(text: str) -> tuple[date, str] | None:
    """The look-back a text asks about ("last 10 yrs", "past year", "YTD", "since 2015"): (start date, label)."""
    today = datetime.now(timezone.utc).date()
    if _YTD.search(text):
        return date(today.year, 1, 1), "year to date"
    if m := _SINCE.search(text):
        return date(int(m[1]), 1, 1), f"since {m[1]}"
    for m in _PERIOD.finditer(text):
        if unit := _unit(m[2], numbered=bool(m[1] and m[1].isdigit())):
            break
    else:
        return None
    n = int(m[1]) if m[1] and m[1].isdigit() else _NUM_WORDS.get((m[1] or "one").lower(), 1)
    if unit == "decade":
        n, unit = n * 10, "year"
    return today - timedelta(days=round(_UNITS[unit] * n)), f"last {n} {unit}s" if n != 1 else f"last {unit}"


def parse_period(text: str) -> tuple[date, str] | None:
    """A period as a tool argument: "10y", "6 months", "last year", "ytd", "since 2015"."""
    t = str(text or "").strip()
    return (asked_period(t) or asked_period(f"last {t}")) if t else None


# ---------------------------------------------------------------- figures
def market_open(now: datetime | None = None) -> bool:
    """US regular trading hours (9:30-16:00 New York, weekdays; holidays not counted)."""
    ny = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    return ny.weekday() < 5 and (9, 30) <= (ny.hour, ny.minute) < (16, 0)


def quote_data(env: dict) -> dict:
    q = env["data"]
    return {"name": q["name"], "price": q["price"], "prev_close": q.get("prev_close"), "change": q.get("change"),
            "change_pct": q.get("change_pct"), "volume": q.get("volume"), "day_high": q.get("day_high"), "day_low": q.get("day_low"),
            "as_of": env["fetched_at"], "source": env["provider"], "freshness": env["freshness"]}


def period_stats(env: dict, start: date) -> dict | None:
    """Start, end, return, high, low and average daily volume of the daily closes from `start`; None if the data doesn't reach into it."""
    pts = [p for p in env["data"]["points"] if p["date"] >= start.isoformat()]
    if len(pts) < 2:
        return None
    first, last = pts[0], pts[-1]
    total = last["close"] / first["close"] - 1
    years = (date.fromisoformat(last["date"]) - date.fromisoformat(first["date"])).days / 365.25
    hi, lo = max(pts, key=lambda p: p["close"]), min(pts, key=lambda p: p["close"])
    vols = [p["volume"] for p in pts if p.get("volume")]
    return {"start_date": first["date"], "start_price": first["close"], "end_date": last["date"], "end_price": last["close"],
            "return": round(total, 4),
            "annualised": round((1 + total) ** (1 / years) - 1, 4) if years >= 1 and first["close"] > 0 and last["close"] > 0 else None,
            "high": hi["close"], "high_date": hi["date"], "low": lo["close"], "low_date": lo["date"],
            "avg_volume": round(sum(vols) / len(vols)) if vols else None,
            "partial": (date.fromisoformat(first["date"]) - start).days > 10,       # the data starts later than asked
            **_meta(env)}


def merge_market(a: dict | None, b: dict | None) -> dict:
    """Reducer for {symbol: {section: {...}}}: sections are merged per symbol, so a quote and a period's stats for TSLA end up together."""
    out = {s: dict(v) for s, v in (a or {}).items()}
    for sym, sections in (b or {}).items():
        out.setdefault(sym, {}).update(sections)
    return out


# ---------------------------------------------------------------- tools
def _symbols(raw) -> list[str]:
    syms = [str(s).strip().upper().lstrip("$") for s in (raw if isinstance(raw, list) else [raw]) if s]
    ok = [s for s in dict.fromkeys(syms) if SYMBOL_OK.match(s)]
    if not ok:
        raise ToolError("give one or more ticker symbols, e.g. [\"TSLA\"]")
    return ok[:MAX_SYMBOLS]


def get_quote(db, symbols: list[str]) -> dict:
    """Latest price, change vs previous close, volume traded today and the day's range."""
    out = {}
    for s in _symbols(symbols):
        try:
            out[s] = {"quote": quote_data(get_market_data(db, "quote", s))}
        except SymbolNotFound:
            out[s] = {"error": {"message": "no data for this symbol"}}
    return out


def performance(db, symbols: list[str], start: date, label: str) -> dict:
    days = YEAR_DAYS if (datetime.now(timezone.utc).date() - start).days <= 366 else HISTORY_MAX_DAYS
    out = {}
    for s in _symbols(symbols):
        try:
            env = get_market_data(db, "history", s, days=days)
        except SymbolNotFound:
            out[s] = {"error": {"message": "no price history for this symbol"}}
            continue
        if st := period_stats(env, start):
            named = {"name": env["data"]["name"]} if env["data"].get("name") else {}     # history has no name; the quote's is used
            out[s] = {"period": {**named, "label": label, "start": start.isoformat(), **st}}
    return out


def get_performance(db, symbols: list[str], period: str) -> dict:
    """Return, annualised return, high/low and average daily volume over a period."""
    p = parse_period(period)
    if p is None:
        raise ToolError(f"unknown period {period!r}; use e.g. \"1y\", \"6 months\", \"10y\", \"ytd\" or \"since 2015\"")
    return performance(db, symbols, *p)


def get_company_profile(db, symbol: str) -> dict:
    """Sector, industry, valuation (P/E, market cap...), next earnings date, recent EPS surprises and yearly dividends."""
    s = _symbols(symbol)[0]
    try:
        env = get_market_data(db, "stock", s)
    except NotAFund as e:
        return {s: {"error": {"message": f"{s} is {e.kind}; it has no company profile"}}}
    except SymbolNotFound:
        return {s: {"error": {"message": "no data for this symbol"}}}
    p = env["data"]
    earn = p.get("earnings") or {}
    profile = {"name": p.get("name"), "sector": p.get("sector"), "industry": p.get("industry"),
               **(p.get("valuation") or {}),
               "next_earnings": (earn.get("next") or {}).get("date"),
               "eps_history": [{k: h.get(k) for k in ("quarter", "eps_estimate", "eps_actual", "surprise")} for h in (earn.get("history") or [])[:4]],
               "dividends_by_year": ((p.get("actions") or {}).get("dividends_by_year") or [])[-5:], **_meta(env)}
    return {s: {"profile": {k: v for k, v in profile.items() if v not in (None, [], {})}}}


def get_fund_profile(db, symbol: str) -> dict:
    """An ETF's or mutual fund's category, expense ratio, yield, size, top holdings and sector weights."""
    s = _symbols(symbol)[0]
    try:
        env = get_market_data(db, "fund", s)
    except NotAFund as e:
        return {s: {"error": {"message": f"{s} is {e.kind}, not a fund"}}}
    except SymbolNotFound:
        return {s: {"error": {"message": "no data for this symbol"}}}
    f = env["data"]
    fund = {"name": f.get("name"), "category": f.get("category"), "family": f.get("family"),
            "expense_ratio": (f.get("operations") or {}).get("expense_ratio"), "yield": f.get("yield"), "total_assets": f.get("total_assets"),
            "top_holdings": [{"symbol": h["symbol"], "weight": h["weight"]} for h in (f.get("top_holdings") or [])[:5]],
            "sector_weights": (f.get("sector_weights") or [])[:5], "asset_classes": f.get("asset_classes") or [], **_meta(env)}
    return {s: {"fund": {k: v for k, v in fund.items() if v not in (None, [], {})}}}


# ---------------------------------------------------------------- levels above one company
BENCHMARK = "^GSPC"                        # sectors are compared with the S&P 500, the market they are part of
OVERVIEW_KEY = "MARKET"                    # market_data key of the overview (markets.MARKET_FEED: "the US market")
OVERVIEW_INDICES = ["^GSPC", "^IXIC", "^DJI"]
SECTOR_HOLDINGS = 5
DEFAULT_PERIOD = "1 month"                 # a sector or the market "doing" well or badly is read over a month, unless asked otherwise


def _sector_market(raw) -> dict:
    """The sector a tool argument names ("XLK", "Technology sector", "tech stocks"), from markets.yaml's `sectors` group."""
    from src.rag import markets as MK
    m = MK.lookup(str(raw or "").strip().lstrip("$"), meaning=False)
    if not m or m["group"] != "sectors" or not m["symbol"]:
        raise ToolError(f"unknown sector {raw!r}; use a sector fund symbol: {sector_list()}")
    return m


def sector_list() -> str:
    from src.rag import markets as MK
    return ", ".join(f"{e['symbol']} ({e['name'].removesuffix(' sector')})" for e in MK.entries() if e["group"] == "sectors")


def _period_of(db, symbol: str, start: date, label: str) -> dict | None:
    return performance(db, [symbol], start, label).get(symbol, {}).get("period")


def _return_row(symbol: str, name: str, p: dict | None) -> dict:
    return {"symbol": symbol, "name": name, "return": p["return"] if p else None}


def sector_performance(db, symbol: str, start: date, label: str) -> dict:
    """A sector's return over a period, measured by its sector fund, against the S&P 500 over the same dates, and how its largest
    companies moved: Yahoo's list for the whole sector (yf.Sector), else the fund's top holdings (live data only either way)."""
    m = _sector_market(symbol)
    etf = m["symbol"]
    own = _period_of(db, etf, start, label)
    if own is None:
        return {etf: {"error": {"message": "no price history for this sector's fund"}}}
    bench = _period_of(db, BENCHMARK, start, label)
    top, of = largest_in_sector(db, etf)
    holdings = [{**_return_row(h["symbol"], h.get("name") or h["symbol"], _period_of(db, h["symbol"], start, label)), "weight": h.get("weight")}
                for h in top[:SECTOR_HOLDINGS] if SYMBOL_OK.match(str(h.get("symbol") or ""))]
    sector = {"name": m["name"], "fund": etf, "label": label, "start": start.isoformat(), "start_date": own["start_date"],
              "end_date": own["end_date"], "return": own["return"], "partial": own["partial"],
              "benchmark": _return_row(BENCHMARK, "S&P 500", bench) if bench else None,
              "vs_benchmark": round(own["return"] - bench["return"], 4) if bench else None,
              "holdings": holdings, "weights_of": of, **{k: own[k] for k in ("as_of", "source", "freshness")}}
    return {etf: {"sector": sector}}


def largest_in_sector(db, etf: str) -> tuple[list[dict], str]:
    """The sector's largest companies with their weight, and what the weight is a share of ("sector" or "fund")."""
    try:
        return B.sector_profile(db, etf)["data"]["top_companies"], "sector"
    except SymbolNotFound:
        pass
    try:
        return get_market_data(db, "fund", etf)["data"].get("top_holdings") or [], "fund"
    except (NotAFund, SymbolNotFound):
        return [], "fund"


def get_sector_performance(db, sector: str, period: str = DEFAULT_PERIOD) -> dict:
    """A US stock-market sector's return over a period (measured by its sector fund), against the S&P 500 over the same dates,
    and how its largest companies moved. Use for questions about a sector rather than one company."""
    p = parse_period(period)
    if p is None:
        raise ToolError(f"unknown period {period!r}; use e.g. \"1 month\", \"6 months\", \"1y\" or \"ytd\"")
    return sector_performance(db, sector, *p)


def market_overview(db, start: date, label: str) -> dict:
    """The US stock market over a period: the main indices, and every sector ranked from best to worst return."""
    from src.rag import markets as MK
    names = {s: MK.entry(s)["name"] for s in OVERVIEW_INDICES} | {e["symbol"]: e["name"] for e in MK.entries() if e["group"] == "sectors"}
    periods = {s: _period_of(db, s, start, label) for s in names}
    got = [p for p in periods.values() if p]
    if not got:
        return {OVERVIEW_KEY: {"error": {"message": "no price history for the market"}}}
    sectors = [_return_row(s, names[s], periods[s]) for s in names if s not in OVERVIEW_INDICES]
    first = periods[BENCHMARK] or got[0]                       # dates and freshness: the S&P 500's, else whatever was found
    overview = {"name": "US stock market", "label": label, "start": start.isoformat(),
                "indices": [_return_row(s, names[s], periods[s]) for s in OVERVIEW_INDICES if periods[s]],
                "sectors": sorted((s for s in sectors if s["return"] is not None), key=lambda s: -s["return"]),
                "missing": [s["symbol"] for s in sectors if s["return"] is None],
                **{k: first[k] for k in ("start_date", "end_date", "as_of", "source", "freshness")}}
    return {OVERVIEW_KEY: {"overview": overview}}


def get_market_overview(db, period: str = DEFAULT_PERIOD) -> dict:
    """The US stock market as a whole over a period: the S&P 500, Nasdaq and Dow, and all 11 sectors ranked from best to worst.
    Use for "how is the market doing", market overviews and "which sectors did best"."""
    p = parse_period(period)
    if p is None:
        raise ToolError(f"unknown period {period!r}; use e.g. \"1 month\", \"6 months\", \"1y\" or \"ytd\"")
    return market_overview(db, *p)


# ---------------------------------------------------------------- Yahoo's sector, industry, screen and market-hours data
# Keyed in market_data by what they describe ("SECTOR:XLK", "INDUSTRY:semiconductors", "LARGEST"...), never by a company's ticker.
# The boards are market_boards' (the Live Market tab's charts), so chat and charts agree. Live data only: no sample fallback.
LIVE_ONLY = "this needs live data from Yahoo Finance, which isn't available right now"


def _range(period) -> str:
    r = str(period or "1M").upper().replace(" ", "")
    if r not in B.RANGES:
        raise ToolError(f"unknown period {period!r}; use one of {', '.join(B.RANGES)}")
    return r


def _board(kind: str, b: dict, title: str) -> dict:
    return {"board": {"kind": kind, "title": title, **{k: b.get(k) for k in ("label", "start_date", "end_date", "items", "missing", "as_of", "freshness")},
                      "source": "yfinance"}}


def get_sector_profile(db, sector: str) -> dict:
    """What a US sector is made of: its size and share of the whole market, its industries and their weights, its 10 largest
    companies (with analysts' consensus rating) and its largest ETFs. Use for "what's in the tech sector", "biggest bank stocks"."""
    m = _sector_market(sector)
    key = f"SECTOR:{m['symbol']}"
    try:
        env = B.sector_profile(db, m["symbol"])
    except SymbolNotFound:
        return {key: {"error": {"message": LIVE_ONLY}}}
    d = env["data"]
    ov = d["overview"]
    return {key: {"sector_profile": {"name": m["name"], "fund": m["symbol"], "companies_count": ov["companies_count"], "market_cap": ov["market_cap"],
                                     "market_weight": ov["market_weight"], "industries": [{"name": i["name"], "key": i["key"], "weight": i["weight"]} for i in d["industries"]],
                                     "top_companies": d["top_companies"][:10], "top_etfs": d["top_etfs"][:5], **_meta(env)}}}


def get_industry(db, industry: str) -> dict:
    """One industry (e.g. "semiconductors", "banks-regional", "software-infrastructure"; get_sector_profile lists a sector's): its
    size and share of its sector, its largest companies, and the best performing (year to date) and fastest growing ones in it."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(industry or "").lower()).strip("-")
    if not slug:
        raise ToolError("name an industry, e.g. \"semiconductors\"")
    key = f"INDUSTRY:{slug}"
    try:
        env = get_market_data(db, "industry", slug)
    except SymbolNotFound:
        return {key: {"error": {"message": f"no industry called {industry!r} (or {LIVE_ONLY}); get_sector_profile lists a sector's industries"}}}
    d = env["data"]
    ov = d["overview"]
    return {key: {"industry": {"name": d["name"], "sector": d["sector_name"], "companies_count": ov["companies_count"], "market_cap": ov["market_cap"],
                               "sector_weight": ov["market_weight"], "top_companies": d["top_companies"][:10],
                               "top_performing": d["top_performing"], "top_growth": d["top_growth"], **_meta(env)}}}


def get_industry_performance(db, sector: str, period: str = "1M") -> dict:
    """How each industry in a sector did over a period, best to worst, with its weight in the sector. Use for "which part of
    tech did best", "what dragged financials down"."""
    m, rng = _sector_market(sector), _range(period)
    key = f"INDUSTRIES:{m['symbol']}"
    try:
        return {key: _board("industries", B.industry_board(db, m["symbol"], rng), f"Industries in the {m['name'].lower()}")}
    except SymbolNotFound:
        return {key: {"error": {"message": LIVE_ONLY}}}


def get_largest_companies(db, period: str = "1M") -> dict:
    """The 10 largest US-listed companies by market value and how each did over a period."""
    try:
        return {"LARGEST": _board("largest", B.largest_board(db, _range(period)), "Largest US-listed companies")}
    except SymbolNotFound:
        return {"LARGEST": {"error": {"message": LIVE_ONLY}}}


def get_region_performance(db, period: str = "1M") -> dict:
    """Stock markets around the world: each country's or area's main index (US, UK, Eurozone, Germany, Japan, China, India...)
    over a period, best to worst, in local currency. Use for "how is Europe / Asia doing", "which markets did best"."""
    return {"REGIONS": _board("regions", B.region_board(db, _range(period)), "Stock markets by region")}


def get_most_active(db) -> dict:
    """Today's 20 most traded US stocks by share volume, with price and change."""
    try:
        b = B.most_active(db)
    except SymbolNotFound:
        return {"MOST_ACTIVE": {"error": {"message": LIVE_ONLY}}}
    return {"MOST_ACTIVE": _board("most_active", b, b["title"])}


def get_market_status(db) -> dict:
    """Whether the US stock market is open or closed now, and today's trading hours."""
    try:
        env = get_market_data(db, "market_status", "US")
    except SymbolNotFound:
        return {"MARKET_STATUS": {"error": {"message": LIVE_ONLY}}}
    return {"MARKET_STATUS": {"status": {**env["data"], **_meta(env)}}}


TOOLS = {"get_quote": get_quote, "get_performance": get_performance,
         "get_company_profile": get_company_profile, "get_fund_profile": get_fund_profile,
         "get_sector_performance": get_sector_performance, "get_market_overview": get_market_overview,
         "get_sector_profile": get_sector_profile, "get_industry_performance": get_industry_performance, "get_industry": get_industry,
         "get_largest_companies": get_largest_companies, "get_region_performance": get_region_performance,
         "get_most_active": get_most_active, "get_market_status": get_market_status}

_SYMBOLS_ARG = {"type": "array", "items": {"type": "string"}, "description": "ticker symbols, e.g. [\"TSLA\", \"SBUX\"] (at most 3)"}
_SYMBOL_ARG = {"type": "string", "description": "one ticker symbol, e.g. \"TSLA\""}
_PERIOD_ARG = {"type": "string", "description": "e.g. \"1 month\" (the default), \"6 months\", \"1y\", \"ytd\""}
_RANGE_ARG = {"type": "string", "enum": list(B.RANGES), "description": "1D (today), 1M (the default), 3M, YTD or 1Y"}
_SECTOR_ARG = {"type": "string", "description": f"the sector's fund symbol, one of {sector_list()}"}
TOOL_SPECS = [
    {"type": "function", "function": {"name": "get_quote", "description": get_quote.__doc__,
                                      "parameters": {"type": "object", "properties": {"symbols": _SYMBOLS_ARG}, "required": ["symbols"]}}},
    {"type": "function", "function": {"name": "get_performance", "description": get_performance.__doc__,
                                      "parameters": {"type": "object", "properties": {
                                          "symbols": _SYMBOLS_ARG,
                                          "period": {"type": "string", "description": "e.g. \"1 month\", \"1y\", \"5 years\", \"10y\", \"ytd\", \"since 2015\""}},
                                          "required": ["symbols", "period"]}}},
    {"type": "function", "function": {"name": "get_company_profile", "description": get_company_profile.__doc__,
                                      "parameters": {"type": "object", "properties": {"symbol": _SYMBOL_ARG}, "required": ["symbol"]}}},
    {"type": "function", "function": {"name": "get_fund_profile", "description": get_fund_profile.__doc__,
                                      "parameters": {"type": "object", "properties": {"symbol": _SYMBOL_ARG}, "required": ["symbol"]}}},
    {"type": "function", "function": {"name": "get_sector_performance", "description": get_sector_performance.__doc__,
                                      "parameters": {"type": "object", "properties": {
                                          "sector": _SECTOR_ARG, "period": _PERIOD_ARG}, "required": ["sector"]}}},
    {"type": "function", "function": {"name": "get_market_overview", "description": get_market_overview.__doc__,
                                      "parameters": {"type": "object", "properties": {"period": _PERIOD_ARG}, "required": []}}},
    {"type": "function", "function": {"name": "get_sector_profile", "description": get_sector_profile.__doc__,
                                      "parameters": {"type": "object", "properties": {"sector": _SECTOR_ARG}, "required": ["sector"]}}},
    {"type": "function", "function": {"name": "get_industry_performance", "description": get_industry_performance.__doc__,
                                      "parameters": {"type": "object", "properties": {"sector": _SECTOR_ARG, "period": _RANGE_ARG},
                                                     "required": ["sector"]}}},
    {"type": "function", "function": {"name": "get_industry", "description": get_industry.__doc__,
                                      "parameters": {"type": "object", "properties": {"industry": {"type": "string", "description": "Yahoo's industry key or name, e.g. \"semiconductors\""}},
                                                     "required": ["industry"]}}},
    {"type": "function", "function": {"name": "get_largest_companies", "description": get_largest_companies.__doc__,
                                      "parameters": {"type": "object", "properties": {"period": _RANGE_ARG}, "required": []}}},
    {"type": "function", "function": {"name": "get_region_performance", "description": get_region_performance.__doc__,
                                      "parameters": {"type": "object", "properties": {"period": _RANGE_ARG}, "required": []}}},
    {"type": "function", "function": {"name": "get_most_active", "description": get_most_active.__doc__,
                                      "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_market_status", "description": get_market_status.__doc__,
                                      "parameters": {"type": "object", "properties": {}, "required": []}}},
]


def run_tool(db, name: str, args: dict) -> tuple[dict, str]:
    """Run a tool the model asked for: (data, trace note). Bad names or arguments give an `error` the model and trace can see."""
    fn = TOOLS.get(name)
    if fn is None:
        return {"_error": f"unknown tool {name!r}"}, f"{name} → unknown tool"
    try:
        data = fn(db, **(args or {}))
    except (ToolError, TypeError) as e:
        return {"_error": str(e)}, f"{name}({_args(args)}) → rejected ({e})"
    fresh = {sec.get("freshness") for d in data.values() for sec in d.values() if isinstance(sec, dict)} - {None}
    return data, f"{name}({_args(args)}) → {', '.join(sorted(fresh)) or 'no data'}"


def _args(args: dict) -> str:
    return ", ".join(", ".join(v) if isinstance(v, list) else str(v) for v in (args or {}).values())


def _meta(env: dict) -> dict:
    return {"as_of": env["fetched_at"], "source": env["provider"], "freshness": env["freshness"]}


# ---------------------------------------------------------------- text
def _money(x) -> str:
    return f"${x:,.2f}" if isinstance(x, (int, float)) else "n/a"


def price(sym: str, x) -> str:
    """A price in its unit: a currency rate as a plain number (EUR/USD 1.1218, USD/JPY 151.37), a Treasury yield as a percentage,
    an index in points, anything else in dollars."""
    if not isinstance(x, (int, float)):
        return "n/a"
    from src.rag.markets import entry
    e = entry(sym)
    group = e["group"] if e else None
    if group == "forex":
        return f"{x:,.4f}" if abs(x) < 10 else f"{x:,.2f}"
    if group == "rates":
        return f"{x:.2f}%"
    if group in ("us_indices", "world_indices") and not sym.endswith("=F"):
        return f"{x:,.2f} points"
    return f"${x:,.4f}" if abs(x) < 1 else _money(x)


def big(x) -> str:
    """84_200_000 -> "84.2M"; 1.2e12 -> "1.2T"."""
    if not isinstance(x, (int, float)):
        return "n/a"
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= div:
            return f"{x / div:,.1f}{unit}"
    return f"{x:,.0f}"


def _pct(x, signed: bool = True) -> str:
    return f"{x * 100:+.2f}%" if signed else f"{x * 100:.2f}%"


def _name(d: dict, sym: str) -> str:
    return next((sec["name"] for sec in d.values() if isinstance(sec, dict) and sec.get("name")), sym)


def describe_lines(data: dict) -> list[str]:
    """The figures as answer lines, in a fixed order per symbol (quote, period, profile, fund), then what had no data."""
    lines, missing = [], []
    for sym, d in data.items():
        if sym.startswith("_"):
            continue
        name = _name(d, sym)
        if q := d.get("quote"):
            tag = {"sample": "sample data", "live": "live", "cached": "cached", "stale": "stale"}.get(q["freshness"], q["freshness"])
            so_far = " so far today" if market_open() and q["freshness"] in ("live", "cached") else ""
            vol = f", volume {big(q['volume'])}{so_far}" if q.get("volume") else ""
            rng = f", day range {price(sym, q['day_low'])}–{price(sym, q['day_high'])}" if q.get("day_low") and q.get("day_high") else ""
            chg = f", {_pct(q['change_pct'])} vs previous close" if q.get("change_pct") is not None else ""
            lines.append(f"- **{name}** ({sym}): {price(sym, q['price'])}{chg}{vol}{rng} ({tag}, {q['as_of'][11:16]} UTC)")
        if p := d.get("period"):
            short = f" (data available from {p['start_date']} only)" if p.get("partial") else ""
            line = (f"- **{name}**, {p['label']}{short}: {price(sym, p['start_price'])} on {p['start_date']} → {price(sym, p['end_price'])} on "
                    f"{p['end_date']}, total return **{p['return'] * 100:+.1f}%**")
            if p.get("annualised") is not None:
                line += f" (about {p['annualised'] * 100:+.1f}% a year annualised)"
            line += f"; high {price(sym, p['high'])} ({p['high_date']}), low {price(sym, p['low'])} ({p['low_date']})"
            if p.get("avg_volume"):
                line += f"; average daily volume {big(p['avg_volume'])}"
            lines.append(line + ". Closing prices are adjusted for splits and dividends.")
        if pr := d.get("profile"):
            bits = [f"{k.replace('_', ' ')} {pr[k]}" for k in ("sector", "industry") if pr.get(k)]
            for k, label in (("trailing_pe", "P/E (trailing)"), ("forward_pe", "P/E (forward)"), ("price_to_book", "price/book"), ("beta", "beta")):
                if isinstance(pr.get(k), (int, float)):
                    bits.append(f"{label} {pr[k]:.2f}")
            if pr.get("market_cap"):
                bits.append(f"market cap ${big(pr['market_cap'])}")
            if pr.get("shares_outstanding"):
                bits.append(f"shares outstanding {big(pr['shares_outstanding'])}")
            if isinstance(pr.get("dividend_yield"), (int, float)):
                bits.append(f"dividend yield {_pct(pr['dividend_yield'], signed=False)}")
            if pr.get("fifty_two_week_low") and pr.get("fifty_two_week_high"):
                bits.append(f"52-week range {_money(pr['fifty_two_week_low'])}–{_money(pr['fifty_two_week_high'])}")
            if pr.get("average_volume"):
                bits.append(f"average volume {big(pr['average_volume'])}")
            if pr.get("next_earnings"):
                bits.append(f"next earnings {pr['next_earnings']}")
            if pr.get("dividends_by_year"):
                bits.append("dividends per share by year: " + ", ".join(f"{x['year']} {_money(x['amount'])}" for x in pr["dividends_by_year"]))
            lines.append(f"- **{name}** ({sym}) profile: " + ("; ".join(bits) or "no details available") + ".")
        if f := d.get("fund"):
            bits = [f"category {f['category']}"] if f.get("category") else []
            if isinstance(f.get("expense_ratio"), (int, float)):
                bits.append(f"expense ratio {_pct(f['expense_ratio'], signed=False)}")
            if isinstance(f.get("yield"), (int, float)):
                bits.append(f"yield {_pct(f['yield'], signed=False)}")
            if f.get("total_assets"):
                bits.append(f"total assets ${big(f['total_assets'])}")
            if f.get("top_holdings"):
                bits.append("top holdings " + ", ".join(f"{h['symbol']} {_pct(h['weight'], signed=False)}" for h in f["top_holdings"] if h.get("weight")))
            if f.get("sector_weights"):
                bits.append("largest sectors " + ", ".join(f"{s['name']} {_pct(s['weight'], signed=False)}" for s in f["sector_weights"]))
            lines.append(f"- **{name}** ({sym}) fund: " + ("; ".join(bits) or "no details available") + ".")
        if s := d.get("sector"):
            lines += sector_lines(s)
        if o := d.get("overview"):
            lines += overview_lines(o)
        for sec, write in YAHOO_LINES.items():
            if sec in d:
                lines += write(d[sec])
        if "error" in d and len(d) == 1:
            if is_subject_key(sym):
                lines.append(f"_{sym.split(':')[0].replace('_', ' ').capitalize()}: {d['error']['message']}._")
            else:
                missing.append(sym)
    if missing:
        lines.append(f"_I don't have data for: {', '.join(missing)}._")
    return lines


SUBJECT_KEYS = {OVERVIEW_KEY, "LARGEST", "REGIONS", "MOST_ACTIVE", "MARKET_STATUS"}


def is_subject_key(key: str) -> bool:
    """A market_data key that names a market subject (the overview, a sector's profile, an industry...), not a ticker."""
    return key in SUBJECT_KEYS or key.split(":")[0] in ("SECTOR", "INDUSTRY", "INDUSTRIES")


def _share(x) -> str:
    return f"{x * 100:.1f}%" if isinstance(x, (int, float)) else "n/a"


def board_lines(b: dict) -> list[str]:
    """A board (industries, largest companies, regions, most active) as one ranked line, like the Live Market tab's chart."""
    def item(i: dict) -> str:
        if b["kind"] == "industries":
            return f"{i['name']} {_ret(i['return'])} ({_share(i.get('weight'))} of the sector)"
        if b["kind"] == "largest":
            return f"{i['name']} ({i['symbol']}, ${big(i.get('market_cap'))}) {_ret(i['return'])}"
        if b["kind"] == "regions":
            return f"{i['region']} ({i['name']}) {_ret(i['return'])}"
        return f"{i['name']} ({i['symbol']}): {big(i.get('volume'))} shares, {_ret(i.get('change_pct'))}"
    order = {"industries": "best to worst", "regions": "best to worst, in local currency", "largest": "by market value",
             "most_active": "by shares traded"}[b["kind"]]
    lines = [f"- **{b['title']}**, {b['label']}{_dates(b)} ({order}): " + "; ".join(item(i) for i in b.get("items") or []) + "."]
    if b.get("missing"):
        lines.append(f"_No figures for: {', '.join(b['missing'])}._")
    return lines


def sector_profile_lines(p: dict) -> list[str]:
    lines = [f"- **{p['name']}** (fund {p['fund']}): {p.get('companies_count') or 'n/a'} companies worth ${big(p.get('market_cap'))}, "
             f"{_share(p.get('market_weight'))} of the US stock market."]
    if p.get("industries"):
        lines.append("- Its industries by weight: " + ", ".join(f"{i['name']} {_share(i['weight'])}" for i in p["industries"]) + ".")
    if p.get("top_companies"):
        lines.append("- Its largest companies: " + ", ".join(f"{c['name']} ({c['symbol']}, {_share(c['weight'])}"
                                                          + (f", analysts: {c['rating']}" if c.get("rating") else "") + ")" for c in p["top_companies"]) + ".")
    if p.get("top_etfs"):
        lines.append("- Its largest ETFs: " + ", ".join(f"{e['name']} ({e['symbol']})" for e in p["top_etfs"]) + ".")
    return lines


def industry_lines(p: dict) -> list[str]:
    lines = [f"- **{p['name']}** industry ({p['sector']} sector): {p.get('companies_count') or 'n/a'} companies worth ${big(p.get('market_cap'))}, "
             f"{_share(p.get('sector_weight'))} of its sector."]
    if p.get("top_companies"):
        lines.append("- Largest companies: " + ", ".join(f"{c['name']} ({c['symbol']}, {_share(c['weight'])})" for c in p["top_companies"]) + ".")
    if p.get("top_performing"):
        lines.append("- Best performing this year: " + ", ".join(f"{c['name']} ({c['symbol']}) {_ret(c.get('ytd_return'))}" for c in p["top_performing"]) + ".")
    if p.get("top_growth"):
        lines.append("- Fastest expected earnings growth: " + ", ".join(f"{c['name']} ({c['symbol']}, growth estimate {_ret(c.get('growth_estimate'))})"
                                                                         for c in p["top_growth"]) + ".")
    return lines


def status_lines(s: dict) -> list[str]:
    hours = f" Regular hours today: {s['open'][11:16]}–{s['close'][11:16]} UTC." if s.get("open") and s.get("close") else ""
    return [f"- **{s.get('name') or 'US markets'}**: {s.get('message') or s.get('status')}.{hours}"]


YAHOO_LINES = {"board": board_lines, "sector_profile": sector_profile_lines, "industry": industry_lines, "status": status_lines}


def _ret(x) -> str:
    return f"{x * 100:+.1f}%" if isinstance(x, (int, float)) else "n/a"


def _dates(sec: dict) -> str:
    return f" ({sec['start_date']} to {sec['end_date']})" if sec.get("start_date") and sec.get("end_date") else ""


def sector_lines(s: dict) -> list[str]:
    """"Technology sector, last month: -3.6%, against +0.9% for the S&P 500 (4.5 points behind)", then its largest holdings' moves."""
    short = " (data available for part of the period only)" if s.get("partial") else ""
    line = f"- **{s['name']}**, {s['label']}{_dates(s)}{short}: **{_ret(s['return'])}**"
    if (b := s.get("benchmark")) and isinstance(s.get("vs_benchmark"), (int, float)):
        gap = s["vs_benchmark"] * 100
        line += f", against {_ret(b['return'])} for the {b['name']} over the same dates ({abs(gap):.1f} percentage points {'ahead' if gap >= 0 else 'behind'})"
    lines = [line + f". Measured by the {s['fund']} sector fund, which holds the sector's companies."]
    moved = [h for h in s.get("holdings") or [] if h.get("return") is not None]
    if moved:
        lines.append(f"- Largest companies in the {s['name'].lower()}, same period: "
                     + ", ".join(f"{h['name']} ({h['symbol']}" + (f", {_pct(h['weight'], signed=False)} of the {s.get('weights_of', 'fund')}" if h.get("weight") else "")
                                 + f") {_ret(h['return'])}" for h in moved) + ".")
    return lines


def overview_lines(o: dict) -> list[str]:
    """The market overview: the indices on one line, the sectors ranked best to worst on the next."""
    lines = []
    if o.get("indices"):
        lines.append(f"- **{o['name']}**, {o['label']}{_dates(o)}: " + ", ".join(f"{i['name']} **{_ret(i['return'])}**" for i in o["indices"]) + ".")
    if o.get("sectors"):
        lines.append(f"- Sectors, best to worst over the {o['label']}: "
                     + ", ".join(f"{s['name'].removesuffix(' sector')} {_ret(s['return'])}" for s in o["sectors"]) + ".")
    if o.get("missing"):
        lines.append(f"_No figures for: {', '.join(o['missing'])}._")
    return lines


def data_block(data: dict) -> str:
    """The figures as compact `SYMBOL section: key=value` lines for an LLM prompt, with percentages and volumes readable."""
    def fmt(k, v):
        if isinstance(v, float) and (k in ("change_pct", "return", "annualised", "expense_ratio", "yield", "dividend_yield") or k.endswith("_pct")):
            return _pct(v)
        if isinstance(v, (int, float)) and ("volume" in k or k in ("market_cap", "total_assets")):
            return big(v)
        return v
    skip = {"source", "name", "partial"}
    readable = {"sector": sector_lines, "overview": overview_lines, **YAHOO_LINES}     # nested figures: the same sentences as the answer text
    return "\n".join(f"{sym} {sec}: " + (" ".join(l.removeprefix("- ") for l in readable[sec](fields)) if sec in readable else
                                         " ".join(f"{k}={fmt(k, v)}" for k, v in fields.items() if k not in skip and v is not None))
                     for sym, d in data.items() if not sym.startswith("_")
                     for sec, fields in d.items() if isinstance(fields, dict) and sec != "error")
