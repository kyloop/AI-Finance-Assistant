"""Market data for the portfolio report (Portfolio tab and Portfolio agent): prices, instrument metadata, price history and
dividends, all through the cached market service. The maths is in calculators.py."""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .calculators import portfolio_performance
from .config import get_config
from .market_service import INSTRUMENTS, NotAFund, SymbolNotFound, get_market_data

CASH = {"name": "Cash", "price": 1.0, "prev_close": 1.0, "asset_type": "cash", "sector": "Cash", "expense_ratio": 0}
SAMPLE_INFO = {"provider": "sample", "fetched_at": "", "freshness": "sample"}
_FRESHNESS_RANK = {"sample": 0, "stale": 1, "cached": 2, "live": 3}
_INTERNATIONAL = re.compile(r"foreign|international|emerging|world|global|europe|asia|pacific|china|japan|india|latin america", re.I)
# Yahoo's sector names -> the bundled instruments' names, where they mean the same thing, so one portfolio doesn't show both
_SECTOR_ALIASES = {"financial services": "Financials", "real estate": "Real Estate", "consumer cyclical": "Consumer",
                   "consumer defensive": "Consumer"}


def _sector(name: str | None) -> str:
    name = (name or "Other").strip()
    return _SECTOR_ALIASES.get(name.lower(), name.capitalize())


def _fund_info(fund: dict) -> dict:
    """analyze_portfolio's instrument fields from a fund profile: what it mostly holds decides the asset type."""
    classes = {c["name"]: c["weight"] for c in fund.get("asset_classes") or []}
    main = max(classes, key=classes.get) if classes else "Stocks"
    category = fund.get("category") or ""
    sectors: dict[str, float] = {}
    for s in fund.get("sector_weights") or []:
        sectors[_sector(s["name"])] = sectors.get(_sector(s["name"]), 0) + s["weight"]
    if main == "Bonds":
        asset_type, sectors = "bond_etf", {"Bonds": 1.0}
    elif main == "Cash":
        asset_type, sectors = "cash", {"Cash": 1.0}
    elif "real estate" in category.lower():
        asset_type, sectors = "real_estate", {"Real Estate": 1.0}
    elif _INTERNATIONAL.search(category):
        asset_type = "intl_etf"
    else:
        asset_type = "thematic_etf" if max(sectors.values(), default=0) > 0.5 else "stock_etf"
    return {"asset_type": asset_type, "sector_breakdown": sectors or {"Other": 1.0},
            "expense_ratio": (fund.get("operations") or {}).get("expense_ratio") or 0}


def _metadata(db: Session, symbol: str) -> dict | None:
    """Asset type, sectors and fees: the bundled record if there is one, else the fund profile, else the stock profile."""
    if symbol in INSTRUMENTS:
        return {k: v for k, v in INSTRUMENTS[symbol].items() if k != "price"}
    try:
        return _fund_info(get_market_data(db, "fund", symbol)["data"])
    except NotAFund:
        pass
    except SymbolNotFound:
        return None
    try:
        stock = get_market_data(db, "stock", symbol)["data"]
    except SymbolNotFound:                                  # an index, a currency…: not something a portfolio analysis can classify
        return None
    return {"asset_type": "stock", "sector": _sector(stock.get("sector")), "expense_ratio": 0}


def _is_cash(symbol: str) -> bool:
    return symbol == "CASH" or INSTRUMENTS.get(symbol, {}).get("asset_type") == "cash"


def portfolio_instruments(db: Session | None, tickers: list[str]) -> tuple[dict, dict]:
    """ticker -> instrument info for analyze_portfolio, priced with the current quote, plus the data_info of the least fresh
    quote. Cash ("CASH" or a bundled money-market fund) is always $1. A ticker nobody can price is left out, so the analysis
    reports it as skipped. Without a database (no market service) the bundled sample prices are used."""
    instruments, envelopes = {}, []
    for t in dict.fromkeys(x.upper() for x in tickers):
        if _is_cash(t):
            instruments[t] = CASH | {"name": INSTRUMENTS.get(t, CASH)["name"]}
        elif db is None:
            if t in INSTRUMENTS:
                instruments[t] = INSTRUMENTS[t]
        else:
            try:
                env = get_market_data(db, "quote", t)
            except SymbolNotFound:
                continue
            meta = _metadata(db, t)
            if meta is None:
                continue
            q = env["data"]
            instruments[t] = {"name": q["name"], **meta, "price": q["price"], "prev_close": q.get("prev_close")}
            envelopes.append(env)
    if not envelopes:
        return instruments, dict(SAMPLE_INFO)
    worst = min(envelopes, key=lambda e: _FRESHNESS_RANK.get(e["freshness"], 0))
    return instruments, {k: worst[k] for k in ("provider", "fetched_at", "freshness")}


_HISTORY_DAYS = (250, 750, 1250, 2520)       # the history endpoint's default (about a year), then about 3, 5 and 10 years of trading days


def _history_days(earliest: str, today: date) -> int:
    """Enough daily bars to reach back to the earliest purchase, from a few fixed sizes so the cache is shared."""
    needed = (today - date.fromisoformat(earliest)).days * 0.72 + 10
    return next((d for d in _HISTORY_DAYS if d >= needed), _HISTORY_DAYS[-1])


def _closes(db: Session, symbol: str, days: int) -> dict[str, float] | None:
    params = {} if days == _HISTORY_DAYS[0] else {"days": days}          # the default shares the Market tab's cached history
    try:
        points = get_market_data(db, "history", symbol, **params)["data"]["points"]
    except SymbolNotFound:
        return None
    return {p["date"]: p["close"] for p in points}


def portfolio_history(db: Session, holdings: list[dict], today: date | None = None) -> dict:
    """Return, risk and benchmark figures for analyze_portfolio's holdings since each was bought (its purchase_date, or
    portfolio.default_purchase_date), from daily closes going back as far as the earliest purchase (10 years at most)."""
    cfg = get_config()["portfolio"]
    default = cfg["default_purchase_date"]
    days = _history_days(min(h.get("purchase_date") or default for h in holdings), today or date.today())
    series = {h["ticker"]: closes for h in holdings if not _is_cash(h["ticker"]) and (closes := _closes(db, h["ticker"], days))}
    perf = portfolio_performance(holdings, series, _closes(db, cfg["benchmark"], days), cfg["risk_free_rate"], cfg["trading_days"], default)
    perf["benchmark"] = {"symbol": cfg["benchmark"], "name": INSTRUMENTS.get(cfg["benchmark"], {}).get("name", cfg["benchmark"])}
    perf["risk_free_rate"] = cfg["risk_free_rate"]
    return perf


def portfolio_dividends(db: Session, holdings: list[dict], today: date | None = None) -> dict:
    """Dividends the current shares would have received over the last 12 months, by month and by holding."""
    since = ((today or date.today()) - timedelta(days=365)).isoformat()
    by_month: dict[str, float] = {}
    by_holding = []
    for h in holdings:
        if _is_cash(h["ticker"]):
            continue
        try:
            paid = get_market_data(db, "stock", h["ticker"])["data"]["actions"]["dividends"]
        except SymbolNotFound:
            continue
        amount = 0.0
        for d in paid:
            if d.get("date") and d.get("amount") and d["date"] >= since:
                by_month[d["date"][:7]] = by_month.get(d["date"][:7], 0) + d["amount"] * h["shares"]
                amount += d["amount"] * h["shares"]
        if amount:
            by_holding.append({"ticker": h["ticker"], "name": h["name"], "amount": round(amount, 2), "yield": amount / h["value"]})
    total = sum(x["amount"] for x in by_holding)
    value = sum(h["value"] for h in holdings)
    return {"total": round(total, 2), "yield": total / value if value else 0,
            "by_month": [{"month": m, "amount": round(a, 2)} for m, a in sorted(by_month.items())],
            "by_holding": sorted(by_holding, key=lambda x: -x["amount"])}
