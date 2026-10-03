"""Market data with DB-backed TTL cache and a provider fallback chain (FR-M2/M4/M5).
Draft: the only concrete provider is the bundled sample data; yfinance / Alpha Vantage plug in via PROVIDERS."""
from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import MarketCache

from .config import DATA_DIR, get_config

with open(DATA_DIR / "mock_market" / "instruments.json") as f:
    INSTRUMENTS: dict = json.load(f)


log = logging.getLogger(__name__)


class SymbolNotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _intraday_series(symbol: str) -> tuple[list[dict], float]:
    """Deterministic 1-minute sample bars for today (seeded by symbol+date), growing with the clock.
    The last bar ticks every 10 s so a live-refreshing UI visibly moves. Returns (bars, prev_close)."""
    info = INSTRUMENTS.get(symbol)
    if not info:
        raise SymbolNotFound(symbol)
    now = datetime.now()
    prev_close = info["price"]
    rng = random.Random(f"{symbol}{now:%Y%m%d}")
    day_pct = rng.uniform(-0.02, 0.02)
    n = max(30, min(390, (now.hour * 60 + now.minute) - (9 * 60 + 30) + 1))   # minutes since 09:30, clamped
    price = prev_close * (1 + rng.uniform(-0.004, 0.004))
    drift = day_pct / 390
    bars = []
    for i in range(n):
        price *= 1 + drift + rng.gauss(0, 0.0006)
        minute = 9 * 60 + 30 + i
        bars.append({"t": f"{minute // 60:02d}:{minute % 60:02d}", "close": round(price, 2), "volume": rng.randint(20_000, 400_000)})
    tick = random.Random(f"{symbol}{int(now.timestamp() // 10)}").gauss(0, 0.0004)
    bars[-1]["close"] = round(bars[-1]["close"] * (1 + tick), 2)
    return bars, prev_close


def _sample_quote(symbol: str, **_) -> dict:
    bars, prev_close = _intraday_series(symbol)
    price = bars[-1]["close"]
    return {"symbol": symbol, "name": INSTRUMENTS[symbol]["name"], "price": price, "prev_close": prev_close,
            "change": round(price - prev_close, 2), "change_pct": round(price / prev_close - 1, 4),
            "volume": sum(b["volume"] for b in bars),
            "day_high": max(b["close"] for b in bars), "day_low": min(b["close"] for b in bars)}


def _sample_intraday(symbol: str, **_) -> dict:
    bars, prev_close = _intraday_series(symbol)
    return {"symbol": symbol, "prev_close": prev_close, "points": bars}


def sparkline(intraday_points: list[dict], points: int = 40) -> list[float]:
    """Downsampled intraday closes for list-row sparklines."""
    closes = [b["close"] for b in intraday_points]
    if not closes:
        return []
    step = max(1, len(closes) // points)
    out = closes[::step]
    return out[:-1] + [closes[-1]] if out[-1] != closes[-1] else out


def _sample_history(symbol: str, days: int = 250, **_) -> dict:
    info = INSTRUMENTS.get(symbol)
    if not info:
        raise SymbolNotFound(symbol)
    rng = random.Random(symbol)
    price, closes = info["price"] * 0.85, []
    for _i in range(days):
        price *= 1 + rng.gauss(0.0006, 0.011)
        closes.append(price)
    scale = info["price"] / closes[-1]
    today = _now().date()
    points = []
    for i, c in enumerate(closes):
        d = today - timedelta(days=days - 1 - i)
        window = lambda n: [x * scale for x in closes[max(0, i - n + 1): i + 1]]
        points.append({"date": d.isoformat(), "close": round(c * scale, 2),
                       "ma50": round(sum(window(50)) / len(window(50)), 2) if i >= 49 else None,
                       "ma200": round(sum(window(200)) / len(window(200)), 2) if i >= 199 else None,
                       "volume": rng.randint(20_000_000, 90_000_000) if info["asset_type"] == "index" else rng.randint(1_000_000, 60_000_000)})
    return {"symbol": symbol, "points": points}


# ---- yfinance (real data) -----------------------------------------------------------------------------------
class ProviderEmpty(Exception):
    """Provider returned nothing (unknown ticker *or* network trouble): fall through to the next provider."""


_names: dict[str, str] = {}


def _yf_ticker(symbol: str):
    import yfinance as yf          # lazy: tests and sample-only setups don't need the dependency
    return yf.Ticker(symbol)


def _yf_name(t, symbol: str) -> str:
    if symbol not in _names:
        try:
            _names[symbol] = t.info.get("shortName") or t.info.get("longName") or symbol
        except Exception:
            return symbol          # don't cache failures
    return _names[symbol]


def _yf_quote(symbol: str, **_) -> dict:
    t = _yf_ticker(symbol)
    try:
        fi = t.fast_info
        price, prev = float(fi["lastPrice"]), float(fi["previousClose"])
    except Exception as e:
        raise ProviderEmpty(symbol) from e
    return {"symbol": symbol, "name": _yf_name(t, symbol), "price": round(price, 2), "prev_close": round(prev, 2),
            "change": round(price - prev, 2), "change_pct": round(price / prev - 1, 4),
            "volume": int(fi["lastVolume"] or 0),
            "day_high": round(float(fi["dayHigh"]), 2), "day_low": round(float(fi["dayLow"]), 2)}


def _yf_intraday(symbol: str, **_) -> dict:
    t = _yf_ticker(symbol)
    df = t.history(period="1d", interval="1m")
    if df.empty:
        raise ProviderEmpty(symbol)
    try:
        prev = round(float(t.fast_info["previousClose"]), 2)
    except Exception:
        prev = round(float(df["Close"].iloc[0]), 2)
    pts = [{"t": ts.strftime("%H:%M"), "close": round(float(r.Close), 2), "volume": int(r.Volume)} for ts, r in df.iterrows()]
    return {"symbol": symbol, "prev_close": prev, "points": pts, "tz": str(df.index.tz)}


def _yf_history(symbol: str, days: int = 250, **_) -> dict:
    period = "2y" if days <= 250 else "5y" if days <= 1250 else "10y"   # 2y so the 200-day average is full across the last year
    df = _yf_ticker(symbol).history(period=period, interval="1d")
    if df.empty:
        raise ProviderEmpty(symbol)
    df["ma50"], df["ma200"] = df["Close"].rolling(50).mean(), df["Close"].rolling(200).mean()
    nz = lambda v: None if v != v else round(float(v), 2)          # NaN -> null
    pts = [{"date": ts.date().isoformat(), "close": round(float(r.Close), 2), "ma50": nz(r.ma50), "ma200": nz(r.ma200),
            "volume": int(r.Volume)} for ts, r in df.tail(days).iterrows()]
    return {"symbol": symbol, "points": pts}


MARKET_NEWS = "MARKET"                       # pseudo-symbol for general market news (no single stock picked)
_MARKET_NEWS_SOURCES = ["^GSPC", "^IXIC", "^DJI"]   # Yahoo has no market-wide feed; merge the major indices' news


def _news_item(raw: dict) -> dict | None:
    c = raw.get("content") or {}
    url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or c.get("previewUrl"))
    if not c.get("title") or not url:
        return None
    thumbs = (c.get("thumbnail") or {}).get("resolutions") or []
    small = next((r["url"] for r in thumbs if r.get("tag") == "170x128"), thumbs[0]["url"] if thumbs else None)
    return {"id": raw.get("id") or c.get("id") or url, "title": c["title"], "summary": c.get("summary") or c.get("description") or "",
            "publisher": (c.get("provider") or {}).get("displayName") or "", "url": url,
            "published": c.get("pubDate") or c.get("displayTime"), "thumbnail": small}


def _search_news_item(raw: dict) -> dict | None:
    """A story from Yahoo's search endpoint (flat shape, no summary), normalised like `_news_item`."""
    if not raw.get("title") or not raw.get("link"):
        return None
    ts = raw.get("providerPublishTime")
    thumbs = (raw.get("thumbnail") or {}).get("resolutions") or []
    return {"id": raw.get("uuid") or raw["link"], "title": raw["title"], "summary": "", "publisher": raw.get("publisher") or "",
            "url": raw["link"], "published": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None,
            "thumbnail": thumbs[-1].get("url") if thumbs else None}


def _search_news(symbol: str, count: int) -> list[dict]:
    """Second source for a symbol's headlines: Yahoo's search endpoint, used when the ticker news feed fails or is empty."""
    import yfinance as yf
    raw = yf.Search(symbol, max_results=1, news_count=count, lists_count=0, timeout=10).news
    return [i for i in map(_search_news_item, raw or []) if i]


def _yf_news(symbol: str, count: int = 30, **_) -> dict:
    sources = _MARKET_NEWS_SOURCES if symbol == MARKET_NEWS else [symbol]
    items: dict[str, dict] = {}
    for src in sources:
        found = []
        try:
            found = [i for i in map(_news_item, _yf_ticker(src).get_news(count=count)) if i]
        except Exception as e:  # noqa: BLE001 — try the search endpoint, but leave the reason in the log
            log.warning("yfinance news for %s failed: %s: %s", src, type(e).__name__, str(e)[:200])
        if not found:
            log.warning("yfinance news for %s returned no stories; trying Yahoo search", src)
            try:
                found = _search_news(src, count)
            except Exception as e:  # noqa: BLE001
                log.warning("Yahoo search news for %s failed: %s: %s", src, type(e).__name__, str(e)[:200])
        for item in found:
            items.setdefault(item["id"], item)
    if not items:
        raise ProviderEmpty(symbol)
    ordered = sorted(items.values(), key=lambda i: i["published"] or "", reverse=True)
    return {"symbol": symbol, "items": ordered[:count]}


def _sample_news(symbol: str, **_) -> dict:
    return {"symbol": symbol, "items": []}      # no bundled headlines: the UI shows "no news" rather than invented stories


# ---- funds and ETFs (yfinance `funds_data`) -------------------------------------------------------------------
class NotAFund(SymbolNotFound):
    """The symbol exists but is a stock, index… with no fund data (so the UI can say so instead of "not found")."""
    def __init__(self, symbol: str, kind: str):
        super().__init__(symbol)
        self.kind = kind


ASSET_CLASSES = {"stockPosition": "Stocks", "bondPosition": "Bonds", "cashPosition": "Cash", "preferredPosition": "Preferred",
                 "convertiblePosition": "Convertible", "otherPosition": "Other"}
SECTORS = {"technology": "Technology", "financial_services": "Financial services", "healthcare": "Healthcare",
           "consumer_cyclical": "Consumer cyclical", "communication_services": "Communication services", "industrials": "Industrials",
           "consumer_defensive": "Consumer defensive", "energy": "Energy", "utilities": "Utilities", "realestate": "Real estate",
           "basic_materials": "Basic materials"}
RATINGS = {"aaa": "AAA", "aa": "AA", "a": "A", "bbb": "BBB", "bb": "BB", "b": "B", "below_b": "Below B", "other": "Other / not rated"}
_KIND = {"EQUITY": "a stock", "INDEX": "an index", "CRYPTOCURRENCY": "a cryptocurrency", "CURRENCY": "a currency", "FUTURE": "a future"}


def _num(v) -> float | None:
    """A float, or None for missing / NaN / pandas NA."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _frame(df, row: str, col: int) -> float | None:
    try:
        return _num(df.loc[row].iloc[col])
    except Exception:  # noqa: BLE001 — a missing row or column is just a missing value
        return None


def _ratio(v: float | None) -> float | None:
    """Yahoo's fund P/E, P/B, P/S and P/CF arrive inverted (VOO's "Price/Earnings" is 0.040: 1/0.040 = 24.8, the S&P 500's
    P/E; P/B 0.189 -> 5.3). Flip them back; 0 means no equity holdings (a bond fund)."""
    return round(1 / v, 1) if v else None


def _fund_payload(symbol: str, name: str, quote_type: str, fd, info: dict) -> dict:
    """Normalise yfinance's FundsData. Each field is read on its own: Yahoo leaves many empty (bond funds have no sector
    weights, mutual funds' top holdings can fail to parse), and one missing piece must not lose the rest."""
    def get(attr):
        try:
            return getattr(fd, attr)
        except Exception:  # noqa: BLE001
            return None
    overview, ops, eq, bond = get("fund_overview") or {}, get("fund_operations"), get("equity_holdings"), get("bond_holdings")
    classes, sectors, ratings, top = get("asset_classes") or {}, get("sector_weightings") or {}, get("bond_ratings") or {}, get("top_holdings")
    holdings = []
    if top is not None and not top.empty:
        holdings = [{"symbol": str(sym), "name": str(r.get("Name") or sym), "weight": _num(r.get("Holding Percent"))} for sym, r in top.iterrows()]
    median_cap = _frame(eq, "Median Market Cap", 0)
    growth = _frame(eq, "3 Year Earnings Growth", 0)
    return {
        "symbol": symbol, "name": name, "quote_type": quote_type, "description": get("description") or "",
        "category": overview.get("categoryName") or info.get("category"), "family": overview.get("family") or info.get("fundFamily"),
        "legal_type": overview.get("legalType"),
        # fund_operations' "Total Net Assets" is unreliable (VOO's equals its median market cap; BND's is 0), so use `info`.
        # It covers every share class of the fund (VOO and the VFIAX mutual fund report the same figure).
        "total_assets": _num(info.get("totalAssets")), "yield": _num(info.get("yield")),
        "operations": {"expense_ratio": _frame(ops, "Annual Report Expense Ratio", 0), "category_expense_ratio": _frame(ops, "Annual Report Expense Ratio", 1),
                       # exactly 0 means "not reported" (QQQ comes back 0, though index rebalancing always trades a little)
                       "turnover": _frame(ops, "Annual Holdings Turnover", 0) or None, "category_turnover": _frame(ops, "Annual Holdings Turnover", 1)},
        "asset_classes": [{"name": label, "weight": round(w, 4)} for key, label in ASSET_CLASSES.items() if (w := _num(classes.get(key)) or 0) > 0.0005],
        "top_holdings": holdings,
        "sector_weights": sorted(({"name": SECTORS.get(k, k.replace("_", " ").capitalize()), "weight": round(w, 4)}
                                  for k, v in sectors.items() if (w := _num(v) or 0) > 0), key=lambda s: -s["weight"]),
        "equity": {"pe": _ratio(_frame(eq, "Price/Earnings", 0)), "pb": _ratio(_frame(eq, "Price/Book", 0)),
                   "ps": _ratio(_frame(eq, "Price/Sales", 0)), "pcf": _ratio(_frame(eq, "Price/Cashflow", 0)),
                   "category_pe": _ratio(_frame(eq, "Price/Earnings", 1)), "category_pb": _ratio(_frame(eq, "Price/Book", 1)),
                   "median_market_cap": median_cap * 1e6 if median_cap else None,            # reported in $ millions
                   "earnings_growth_3y": growth / 100 if growth is not None else None},      # reported in percent
        "bond": {"duration": _frame(bond, "Duration", 0), "maturity": _frame(bond, "Maturity", 0), "credit_quality": _frame(bond, "Credit Quality", 0),
                 "category_duration": _frame(bond, "Duration", 1), "category_maturity": _frame(bond, "Maturity", 1)},
        # "us_government" is the share in government bonds, not a rating bucket (BND: AA 72.5% *and* government 51.8%)
        "bond_ratings": [{"name": label, "weight": round(w, 4)} for key, label in RATINGS.items() if (w := _num(ratings.get(key)) or 0) > 0],
        "government_share": _num(ratings.get("us_government")) or None,
    }


def _yf_fund(symbol: str, **_) -> dict:
    t = _yf_ticker(symbol)
    try:
        fd = t.funds_data
        quote_type = fd.quote_type()
    except Exception as e:
        try:
            kind = (t.info or {}).get("quoteType")
        except Exception:
            kind = None
        if kind and kind not in ("ETF", "MUTUALFUND"):
            raise NotAFund(symbol, _KIND.get(kind, kind.lower())) from e
        raise ProviderEmpty(symbol) from e                      # unknown ticker or network trouble: next provider
    try:
        info = t.info or {}
    except Exception:  # noqa: BLE001 — fund data without the asset total is still worth showing
        info = {}
    return _fund_payload(symbol, info.get("longName") or info.get("shortName") or symbol, quote_type, fd, info)


_SAMPLE_FUND_CLASS = {"stock_etf": "Stocks", "thematic_etf": "Stocks", "intl_etf": "Stocks", "real_estate": "Stocks",
                      "bond_etf": "Bonds", "cash": "Cash"}          # bundled asset_type -> what the fund holds (SPAXX is a money-market fund)


def _sample_fund(symbol: str, **_) -> dict:
    """The bundled ETFs: name, expense ratio and sector split only (no holdings or valuation)."""
    info = INSTRUMENTS[symbol]
    held = _SAMPLE_FUND_CLASS.get(info["asset_type"])
    if held is None:
        raise NotAFund(symbol, "an index" if info["asset_type"] == "index" else "a stock")
    return {"symbol": symbol, "name": info["name"], "quote_type": "MUTUALFUND" if held == "Cash" else "ETF", "description": "",
            "category": None, "family": None, "legal_type": None, "total_assets": None, "yield": None,
            "operations": {"expense_ratio": info.get("expense_ratio"), "category_expense_ratio": None, "turnover": None, "category_turnover": None},
            "asset_classes": [{"name": held, "weight": 1.0}], "top_holdings": [],
            "sector_weights": [] if held != "Stocks" else sorted(({"name": k, "weight": v} for k, v in (info.get("sector_breakdown") or {}).items()), key=lambda s: -s["weight"]),
            "equity": {}, "bond": {}, "bond_ratings": [], "government_share": None}


# ---- stocks: corporate actions, financial statements, earnings and estimates (Research tab › Stock research) -----
# The key lines of each statement, in reading order (Yahoo returns 40-70 raw rows; a beginner needs these).
STATEMENT_ROWS = {
    "income": ["Total Revenue", "Cost Of Revenue", "Gross Profit", "Operating Expense", "Operating Income", "Pretax Income",
               "Tax Provision", "Net Income", "EBITDA", "Diluted EPS", "Diluted Average Shares"],
    "balance": ["Total Assets", "Current Assets", "Cash And Cash Equivalents", "Total Liabilities Net Minority Interest",
                "Current Liabilities", "Total Debt", "Net Debt", "Stockholders Equity", "Retained Earnings", "Working Capital",
                "Ordinary Shares Number"],
    "cash_flow": ["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow", "Investing Cash Flow", "Financing Cash Flow",
                  "Cash Dividends Paid", "Repurchase Of Capital Stock", "End Cash Position"],
}
PERIOD_LABELS = {"0q": "Current quarter", "+1q": "Next quarter", "0y": "Current year", "+1y": "Next year", "LTG": "Long-term growth"}


def _date(v) -> str | None:
    try:
        return v.date().isoformat() if hasattr(v, "date") and callable(v.date) else v.isoformat() if hasattr(v, "isoformat") else str(v)
    except Exception:  # noqa: BLE001
        return None


def _statement(df) -> dict:
    """{periods: [ISO dates, newest first], rows: [{name, values}]} for the key lines present; empty if Yahoo has none."""
    if df is None or df.empty:
        return {"periods": [], "rows": []}
    names = [n for group in STATEMENT_ROWS.values() for n in group]
    return {"periods": [_date(c) for c in df.columns],
            "rows": [{"name": n, "values": [_num(v) for v in df.loc[n]]} for n in names if n in df.index]}


def _table(df, cols: dict[str, str], pct_cols: tuple = ()) -> list[dict]:
    """Rows of an estimates DataFrame (indexed by period 0q / +1q / 0y / +1y / LTG), renamed; pct_cols are fractions."""
    if df is None or df.empty:
        return []
    out = []
    for period, r in df.iterrows():
        row = {"period": PERIOD_LABELS.get(str(period), str(period))}
        for src, dst in cols.items():
            row[dst] = _num(r.get(src)) if src in r else None
        out.append(row)
    return out


def _stock_payload(symbol: str, t, info: dict, quote_type: str) -> dict:
    """Everything the Stock research sub-tab shows, JSON-ready. The ~15 Yahoo requests run in parallel (one after another
    took ~12 s for AAPL) and each on its own: Yahoo leaves many empty (funds have no statements or estimates) and one
    failure must not lose the rest."""
    import pandas as pd
    company = quote_type == "EQUITY"
    five_years_ago = (_now() - timedelta(days=5 * 365)).date().isoformat()
    calls = {"dividends": lambda: t.dividends, "splits": lambda: t.splits, "capital_gains": lambda: t.capital_gains,
             "shares": lambda: t.get_shares_full(start=five_years_ago)}
    if company:
        calls |= {a: (lambda a=a: getattr(t, a)) for a in (
            "income_stmt", "quarterly_income_stmt", "ttm_income_stmt", "balance_sheet", "quarterly_balance_sheet",
            "cash_flow", "quarterly_cash_flow", "ttm_cash_flow", "calendar", "earnings_history", "earnings_estimate",
            "revenue_estimate", "eps_trend", "eps_revisions", "growth_estimates")}
        calls["earnings_dates"] = lambda: t.get_earnings_dates(limit=12)

    def fetch(item):
        name, fn = item
        try:
            return name, fn()
        except Exception as e:  # noqa: BLE001
            log.info("yfinance %s for %s: %s", name, symbol, type(e).__name__)
            return name, None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        raw = dict(pool.map(fetch, calls.items()))
    get = lambda name, default=None: default if raw.get(name) is None else raw[name]      # noqa: E731
    empty = pd.Series(dtype=float)
    divs, splits, gains = get("dividends", empty), get("splits", empty), get("capital_gains", empty)
    yearly = divs.groupby(divs.index.year).sum() if not divs.empty else empty
    shares = get("shares", empty)
    if not shares.empty:                               # many reports a day; keep the last one of each quarter
        shares = shares[~shares.index.duplicated(keep="last")]
        shares = shares.groupby(shares.index.tz_localize(None).to_period("Q")).last()
    dates = get("earnings_dates")
    dates = dates.head(12) if dates is not None else None              # get_earnings_dates ignores `limit` (25 rows for AAPL)
    cal = get("calendar", {})
    next_dates = cal.get("Earnings Date") or []
    hist = get("earnings_history")
    return {
        "symbol": symbol, "name": info.get("longName") or info.get("shortName") or symbol, "quote_type": quote_type,
        "sector": info.get("sector"), "industry": info.get("industry"), "currency": info.get("financialCurrency") or info.get("currency"),
        # from `info`, already fetched; trailingAnnualDividendYield is a fraction (dividendYield's scale has changed between versions)
        "valuation": {k: _num(info.get(src)) for k, src in (("trailing_pe", "trailingPE"), ("forward_pe", "forwardPE"), ("market_cap", "marketCap"),
                                                             ("price_to_book", "priceToBook"), ("beta", "beta"),
                                                             ("dividend_yield", "trailingAnnualDividendYield"),
                                                             ("fifty_two_week_high", "fiftyTwoWeekHigh"), ("fifty_two_week_low", "fiftyTwoWeekLow"),
                                                             ("average_volume", "averageVolume"))},
        "actions": {
            "dividends": [{"date": _date(d), "amount": _num(v)} for d, v in divs.tail(12).items()][::-1],      # newest first
            "dividends_by_year": [{"year": int(y), "amount": round(float(v), 4)} for y, v in yearly.tail(10).items()],
            "splits": [{"date": _date(d), "ratio": _num(v)} for d, v in splits.items()][::-1],
            "capital_gains": [{"date": _date(d), "amount": _num(v)} for d, v in gains.tail(12).items()][::-1],
            "shares": [{"date": p.end_time.date().isoformat(), "shares": int(v)} for p, v in shares.items()],
        },
        "statements": {kind: {"annual": _statement(get(a)), "quarterly": _statement(get(q)), "ttm": _statement(get(m) if m else None)}
                       for kind, a, q, m in (("income", "income_stmt", "quarterly_income_stmt", "ttm_income_stmt"),
                                             ("balance", "balance_sheet", "quarterly_balance_sheet", None),       # no TTM balance sheet
                                             ("cash_flow", "cash_flow", "quarterly_cash_flow", "ttm_cash_flow"))},
        "earnings": {
            "next": {"date": _date(next_dates[0]) if next_dates else None, "eps_low": _num(cal.get("Earnings Low")),
                     "eps_avg": _num(cal.get("Earnings Average")), "eps_high": _num(cal.get("Earnings High")),
                     "revenue_low": _num(cal.get("Revenue Low")), "revenue_avg": _num(cal.get("Revenue Average")),
                     "revenue_high": _num(cal.get("Revenue High")),
                     "ex_dividend_date": _date(cal["Ex-Dividend Date"]) if cal.get("Ex-Dividend Date") else None,
                     "dividend_date": _date(cal["Dividend Date"]) if cal.get("Dividend Date") else None},
            # earnings_dates gives the surprise in percent; earnings_history as a fraction: both become fractions here
            "dates": [{"date": _date(d), "eps_estimate": _num(r.get("EPS Estimate")), "eps_reported": _num(r.get("Reported EPS")),
                       "surprise": (s / 100 if (s := _num(r.get("Surprise(%)"))) is not None else None)}
                      for d, r in (dates.iterrows() if dates is not None and not dates.empty else [])],
            "history": [{"quarter": _date(q), "eps_estimate": _num(r.get("epsEstimate")), "eps_actual": _num(r.get("epsActual")),
                         "surprise": _num(r.get("surprisePercent"))}
                        for q, r in (hist.iterrows() if hist is not None and not hist.empty else [])],
            "eps_estimate": _table(get("earnings_estimate"),
                                   {"avg": "avg", "low": "low", "high": "high", "yearAgoEps": "year_ago", "numberOfAnalysts": "analysts", "growth": "growth"}),
            "revenue_estimate": _table(get("revenue_estimate"),
                                       {"avg": "avg", "low": "low", "high": "high", "yearAgoRevenue": "year_ago", "numberOfAnalysts": "analysts", "growth": "growth"}),
            "eps_trend": _table(get("eps_trend"),
                                {"current": "current", "7daysAgo": "d7", "30daysAgo": "d30", "60daysAgo": "d60", "90daysAgo": "d90"}),
            "eps_revisions": _table(get("eps_revisions"),            # Yahoo mixes "Days"/"days"
                                    {"upLast7days": "up_7d", "upLast30days": "up_30d", "downLast7Days": "down_7d", "downLast30days": "down_30d"}),
            "growth": _table(get("growth_estimates"), {"stockTrend": "stock", "indexTrend": "index"}),
        },
    }


def _yf_stock(symbol: str, **_) -> dict:
    t = _yf_ticker(symbol)
    try:
        info = t.info or {}
    except Exception as e:
        raise ProviderEmpty(symbol) from e
    kind = info.get("quoteType")
    if not kind:
        raise ProviderEmpty(symbol)
    if kind not in ("EQUITY", "ETF", "MUTUALFUND"):
        raise NotAFund(symbol, _KIND.get(kind, kind.lower()))           # an index or currency: nothing to research here
    return _stock_payload(symbol, t, info, kind)


def _sample_stock(symbol: str, **_) -> dict:
    """Offline: the bundled instruments have no statements, estimates or dividend history; say so rather than invent them."""
    info = INSTRUMENTS[symbol]
    if info["asset_type"] == "index":
        raise NotAFund(symbol, "an index")
    empty = {"periods": [], "rows": []}
    return {"symbol": symbol, "name": info["name"], "quote_type": "EQUITY" if info["asset_type"] == "stock" else "ETF",
            "sector": info.get("sector"), "industry": None, "currency": "USD", "valuation": {},
            "actions": {"dividends": [], "dividends_by_year": [], "splits": [], "capital_gains": [], "shares": []},
            "statements": {k: {"annual": empty, "quarterly": empty, "ttm": empty} for k in ("income", "balance", "cash_flow")},
            "earnings": {"next": {}, "dates": [], "history": [], "eps_estimate": [], "revenue_estimate": [], "eps_trend": [],
                         "eps_revisions": [], "growth": []}}


# provider name -> {endpoint: fn}; ordered = fallback chain (real data first, bundled sample data last, per FR-M4).
PROVIDERS: dict[str, dict] = {
    "yfinance": {"quote": _yf_quote, "history": _yf_history, "intraday": _yf_intraday, "news": _yf_news, "fund": _yf_fund, "stock": _yf_stock},
    "sample": {"quote": _sample_quote, "history": _sample_history, "intraday": _sample_intraday, "news": _sample_news, "fund": _sample_fund, "stock": _sample_stock},
}


# ---- symbol lookup (company name -> ticker) -------------------------------------------------------------------
_symbol_resolver = None                  # tests inject fn(name) -> {symbol, name} | None
alias_store: tuple | None = None         # (get(key) -> hit | None, put(key, hit)): resolved names kept across restarts (the API registers the database)
_resolved: dict[str, dict | None] = {}


def set_symbol_resolver(fn) -> None:
    """Tests inject a fake resolver; None restores the real one. Also clears the lookup cache."""
    global _symbol_resolver
    _symbol_resolver = fn
    _resolved.clear()


def _name_matches(name: str, label: str) -> bool:
    """The company's name starts with what the user wrote ("Palantir" -> "Palantir Technologies Inc."; "The" and punctuation ignored).
    Containing the word is not enough: "chips" would match an ETF called "Amundi Global Memory Chips"."""
    norm = lambda t: re.sub(r"^the\s+", "", re.sub(r"[^\w&\s\-]", " ", t.lower()).strip()).split()      # noqa: E731
    n, label_words = norm(name), norm(label)
    return bool(n) and label_words[:len(n)] == n


def _bundled_resolve(name: str) -> dict | None:
    """Match against the bundled sample instruments (works offline)."""
    low = name.strip().lower()
    for sym, info in INSTRUMENTS.items():
        if not sym.startswith("^") and (sym.lower() == low or _name_matches(name, info["name"])):
            return {"symbol": sym, "name": info["name"]}
    return None


def _yf_resolve(name: str) -> dict | None:
    """Yahoo's symbol search. A hit counts only if it is a stock, ETF or index and its name starts with what the user wrote
    (or its symbol is exactly what they wrote), so "Trump" can't silently become an unrelated ticker."""
    import yfinance as yf
    for q in yf.Search(name, max_results=5, news_count=0, lists_count=0, timeout=10).quotes:
        if q.get("quoteType") not in ("EQUITY", "ETF", "INDEX"):
            continue
        label = f"{q.get('shortname', '')} {q.get('longname', '')}"
        if q["symbol"].lower() == name.strip().lower() or _name_matches(name, label):
            return {"symbol": q["symbol"], "name": q.get("shortname") or q.get("longname") or q["symbol"]}
    return None


def _local_resolve(name: str, fuzzy: bool) -> dict | None:
    """The bundled ticker directory (src/rag/tickers.py): every US-listed stock and ETF. `fuzzy=False` is an exact ticker or a company name
    that starts with `name`; `fuzzy=True` is a mistyped ticker or name, which is only a guess."""
    from src.rag import tickers
    return (tickers.lookup_fuzzy if fuzzy else tickers.lookup_exact)(name)


def resolve_symbol(name: str) -> dict | None:
    """Company name or ticker -> {symbol, name, match}, or None. Tries, in order: names saved from earlier lookups, the ticker directory
    (exact ticker or company name), Yahoo's symbol search, then guesses for typos ("NUU" -> NU, "nvdia" -> NVIDIA), and the bundled sample
    instruments when everything else fails. `match` is "ticker", "name" or "fuzzy"; a fuzzy hit also lists `alternatives`. Hits and clean
    misses are remembered for the process; a failed Yahoo lookup is not. Guesses are never saved."""
    key = name.strip().lower()
    if not key:
        return None
    if key in _resolved:
        return _resolved[key]
    if alias_store:
        try:
            saved = alias_store[0](key)
        except Exception:  # noqa: BLE001 — the saved names are a convenience
            saved = None
        if saved:
            _resolved[key] = saved
            return saved
    local = _symbol_resolver is None            # tests that inject a resolver stay off the directory and the index
    exact = _local_resolve(name, fuzzy=False) if local else None
    if exact:
        _resolved[key] = exact
        return exact
    yahoo_failed = False
    try:
        hit = (_symbol_resolver or _yf_resolve)(name)
    except Exception:  # noqa: BLE001 — network trouble: try the local guesses, and don't remember the failure
        hit, yahoo_failed = None, True
    if not hit and local:
        guess = _local_resolve(name, fuzzy=True)
        if guess:
            if not yahoo_failed:
                _resolved[key] = guess
            return guess
    hit = hit or (_bundled_resolve(name) if local or yahoo_failed else None)
    if not yahoo_failed:
        _resolved[key] = hit
        if hit and alias_store and local:
            try:
                alias_store[1](key, hit)
            except Exception:  # noqa: BLE001
                log.warning("could not save the symbol alias for %s", name)
    return hit


# ---- industry peers ("news from the same sector") ---------------------------------------------------------------
_peer_finder = None                      # tests inject fn(symbol) -> {sector, industry, peers: [{symbol, name}]} | None
_peers: dict[str, dict | None] = {}


def set_peer_finder(fn) -> None:
    """Tests inject a fake peer lookup; None restores the real one. Also clears the cache."""
    global _peer_finder
    _peer_finder = fn
    _peers.clear()


def _yf_peers(symbol: str) -> dict | None:
    """The company's Yahoo industry and the largest companies in it (None for funds and anything without an industry)."""
    import yfinance as yf
    info = yf.Ticker(symbol).info
    if not info.get("industryKey"):
        return None
    top = yf.Industry(info["industryKey"]).top_companies
    peers = [{"symbol": sym, "name": row["name"]} for sym, row in top.iterrows() if sym != symbol][:5]
    return {"sector": info.get("sector"), "industry": info.get("industry"), "peers": peers}


def _bundled_peers(symbol: str) -> dict | None:
    """Offline fallback: the other bundled stocks in the same sector."""
    sector = (INSTRUMENTS.get(symbol) or {}).get("sector")
    peers = [{"symbol": s, "name": i["name"]} for s, i in INSTRUMENTS.items() if s != symbol and i.get("sector") == sector and i.get("asset_type") == "stock"]
    return {"sector": sector, "industry": None, "peers": peers} if sector and peers else None


def industry_peers(symbol: str) -> dict | None:
    """{sector, industry, peers: [{symbol, name}]} for a stock, or None. Remembered for the process; a failed lookup is not."""
    symbol = symbol.upper()
    if symbol in _peers:
        return _peers[symbol]
    try:
        found = (_peer_finder or _yf_peers)(symbol)
    except Exception:  # noqa: BLE001 — Yahoo trouble: use the bundled list, and don't remember the failure
        return _bundled_peers(symbol) if _peer_finder is None else None
    _peers[symbol] = found
    return found


news_listeners: list = []      # callables fn(symbol, items) run after fresh Yahoo news is fetched (the API registers the news index)


def _notify_news(symbol: str, payload: dict) -> None:
    for fn in news_listeners:
        try:
            fn(symbol, payload["items"])
        except Exception:  # noqa: BLE001 — a listener must never break the fetch
            pass


# Agents answering one question run in parallel threads and may share the request's database session (market and portfolio
# both do); the cache reads and writes are serialised so they never use it at the same moment. Provider calls stay outside.
_cache_lock = threading.Lock()


def get_market_data(db: Session, endpoint: str, symbol: str, refresh: bool = False, **params) -> dict:
    """Returns {data, provider, fetched_at, freshness: live|cached|stale|sample}."""
    symbol = symbol.upper()
    market_cfg = get_config()["market"]
    ttl = market_cfg.get(f"{endpoint}_cache_ttl_seconds", market_cfg["cache_ttl_seconds"])     # e.g. news refreshes faster than quotes' default
    for provider, endpoints in PROVIDERS.items():
        key = hashlib.sha1(f"{provider}|{symbol}|{endpoint}|{json.dumps(params, sort_keys=True)}".encode()).hexdigest()
        with _cache_lock:
            row = db.get(MarketCache, key)
        if row and not refresh and _aware(row.expires_at) > _now():
            return _envelope(row.payload, provider, row.fetched_at, "cached", provider)
        try:
            payload = endpoints[endpoint](symbol, **params)
        except SymbolNotFound:
            raise
        except Exception:  # provider down -> try next, then stale cache
            if row:
                return _envelope(row.payload, provider, row.fetched_at, "stale", provider)
            continue
        now = _now()
        with _cache_lock:
            if row:
                row.payload, row.fetched_at, row.expires_at = payload, now, now + timedelta(seconds=ttl)
            else:
                db.add(MarketCache(key=key, provider=provider, symbol=symbol, endpoint=endpoint, payload=payload,
                                   fetched_at=now, expires_at=now + timedelta(seconds=ttl)))
            try:
                db.commit()
            except IntegrityError:        # another request (a parallel agent, the Live tab, the news poll) cached this key a moment ago
                db.rollback()
                other = db.get(MarketCache, key)
                if other is None:
                    raise
                return _envelope(other.payload, provider, other.fetched_at, "cached", provider)
        if endpoint == "news" and provider != "sample":
            _notify_news(symbol, payload)
        return _envelope(payload, provider, now, "live", provider)
    raise SymbolNotFound(symbol)


def _envelope(data: dict, provider: str, fetched_at: datetime, freshness: str, prov: str) -> dict:
    # "sample" provider is always labelled as sample data so the UI never implies it is real-time
    return {"data": data, "provider": provider, "fetched_at": _aware(fetched_at).isoformat(),
            "freshness": "sample" if prov == "sample" else freshness}
