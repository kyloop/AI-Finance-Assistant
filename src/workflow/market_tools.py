"""Market tools for the market agent: a small set of typed functions over market_service, never raw yfinance.

Each tool reads through `get_market_data`, so the cache (TTL per endpoint in config.yaml), the stale-cache and sample-data
fallbacks and the offline tests all apply. Each returns `{symbol: {section: {...}}}` with sections `quote`, `period`,
`profile` or `fund` (or `error`), every figure computed in Python and labelled with its source and time. The LLM only
picks tools and arguments (TOOL_SPECS, in the OpenAI function format that LangChain's `bind_tools` accepts for every
provider); `run_tool` validates them. `describe_lines` turns the figures into the agent's text deterministically."""
from __future__ import annotations

import difflib
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


TOOLS = {"get_quote": get_quote, "get_performance": get_performance,
         "get_company_profile": get_company_profile, "get_fund_profile": get_fund_profile}

_SYMBOLS_ARG = {"type": "array", "items": {"type": "string"}, "description": "ticker symbols, e.g. [\"TSLA\", \"SBUX\"] (at most 3)"}
_SYMBOL_ARG = {"type": "string", "description": "one ticker symbol, e.g. \"TSLA\""}
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
            rng = f", day range {_money(q['day_low'])}–{_money(q['day_high'])}" if q.get("day_low") and q.get("day_high") else ""
            chg = f", {_pct(q['change_pct'])} vs previous close" if q.get("change_pct") is not None else ""
            lines.append(f"- **{name}** ({sym}): {_money(q['price'])}{chg}{vol}{rng} ({tag}, {q['as_of'][11:16]} UTC)")
        if p := d.get("period"):
            short = f" (data available from {p['start_date']} only)" if p.get("partial") else ""
            line = (f"- **{name}**, {p['label']}{short}: {_money(p['start_price'])} on {p['start_date']} → {_money(p['end_price'])} on "
                    f"{p['end_date']}, total return **{p['return'] * 100:+.1f}%**")
            if p.get("annualised") is not None:
                line += f" (about {p['annualised'] * 100:+.1f}% a year annualised)"
            line += f"; high {_money(p['high'])} ({p['high_date']}), low {_money(p['low'])} ({p['low_date']})"
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
        if "error" in d and len(d) == 1:
            missing.append(sym)
    if missing:
        lines.append(f"_I don't have data for: {', '.join(missing)}._")
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
    return "\n".join(f"{sym} {sec}: " + " ".join(f"{k}={fmt(k, v)}" for k, v in fields.items() if k not in skip and v is not None)
                     for sym, d in data.items() if not sym.startswith("_")
                     for sec, fields in d.items() if isinstance(fields, dict) and sec != "error")
