"""Deterministic finance math (never done by the LLM — spec §3.3)."""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from datetime import date

RISK_SCORE = {"cash": 1, "bond_etf": 2, "real_estate": 3, "intl_etf": 4, "stock_etf": 4, "thematic_etf": 5, "stock": 5}
ASSET_CLASS = {
    "stock": "Individual stocks", "stock_etf": "Stock ETFs", "thematic_etf": "Stock ETFs", "intl_etf": "International",
    "bond_etf": "Bonds", "cash": "Cash", "real_estate": "Real estate",
}
TOLERANCE_MAX_RISK = {"conservative": 2.5, "moderate": 3.75, "aggressive": 5.0}
# Approximate: funds don't report a country split, and an individual stock is counted as US wherever the company is based.
GEOGRAPHY = {"stock": "US stocks", "stock_etf": "US stocks", "thematic_etf": "US stocks", "real_estate": "US stocks",
             "intl_etf": "International stocks", "bond_etf": "Bonds", "cash": "Cash"}
MIN_HISTORY_DAYS = 30       # fewer trading days than this: no annualized return, volatility or ratios


def _movers(rows: list[dict]) -> dict:
    """Top 3 winners and losers: by return on cost basis when any holding has one, otherwise by today's move."""
    basis = "total" if any(r["gain_loss_pct"] is not None for r in rows) else "day"
    pct, amount = ("gain_loss_pct", "gain_loss") if basis == "total" else ("day_change_pct", "day_change")
    ranked = sorted((r for r in rows if r[pct] is not None), key=lambda r: -r[pct])
    item = lambda r: {"ticker": r["ticker"], "name": r["name"], "change_pct": r[pct], "change": round(r[amount], 2)}  # noqa: E731
    return {"basis": basis, "winners": [item(r) for r in ranked if r[pct] > 0][:3],
            "losers": [item(r) for r in reversed(ranked) if r[pct] < 0][:3]}


def analyze_portfolio(holdings: list[dict], instruments: dict, risk_tolerance: str = "moderate") -> dict:
    """holdings: [{ticker, shares, cost_basis?, purchase_date?}]; instruments: ticker -> info incl. price (and prev_close, for today's change)."""
    rows, skipped = [], []
    for h in holdings:
        t = h["ticker"].upper()
        info = instruments.get(t)
        if not info or info.get("asset_type") == "index":
            skipped.append(t)
            continue
        rows.append({"ticker": t, "name": info["name"], "shares": h["shares"], "price": info["price"],
                     "value": h["shares"] * info["price"], "cost_basis": h.get("cost_basis"), "purchase_date": h.get("purchase_date"), "info": info})
    total = sum(r["value"] for r in rows)
    if not rows or total <= 0:
        return {"empty": True, "total_value": 0, "holdings": [], "skipped": skipped, "warnings": []}

    for r in rows:
        r["weight"] = r["value"] / total
        cb = r["cost_basis"]
        r["gain_loss"] = (r["price"] - cb) * r["shares"] if cb is not None else None
        r["gain_loss_pct"] = (r["price"] / cb - 1) if cb else None
        prev = r["info"].get("prev_close")
        r["day_change"] = (r["price"] - prev) * r["shares"] if prev else None
        r["day_change_pct"] = (r["price"] / prev - 1) if prev else None

    alloc: dict[str, float] = {}
    sectors: dict[str, float] = {}
    geography: dict[str, float] = {}
    for r in rows:
        alloc[ASSET_CLASS[r["info"]["asset_type"]]] = alloc.get(ASSET_CLASS[r["info"]["asset_type"]], 0) + r["weight"]
        geography[GEOGRAPHY[r["info"]["asset_type"]]] = geography.get(GEOGRAPHY[r["info"]["asset_type"]], 0) + r["weight"]
        breakdown = r["info"].get("sector_breakdown") or {r["info"].get("sector", "Other"): 1.0}  # ETF look-through
        for s, w in breakdown.items():
            sectors[s] = sectors.get(s, 0) + r["weight"] * w

    annual_fee = sum(r["value"] * r["info"].get("expense_ratio", 0) for r in rows)
    eff_holdings = 1 / sum(r["weight"] ** 2 for r in rows)
    classes_present = {"US stocks" for r in rows if r["info"]["asset_type"] in ("stock", "stock_etf", "thematic_etf")} \
        | {"International" for r in rows if r["info"]["asset_type"] == "intl_etf"} \
        | {"Bonds" for r in rows if r["info"]["asset_type"] == "bond_etf"} \
        | {"Cash" for r in rows if r["info"]["asset_type"] == "cash"} \
        | {"Real estate" for r in rows if r["info"]["asset_type"] == "real_estate"}
    equity_sectors = {s: w for s, w in sectors.items() if s not in ("Bonds", "Cash", "Real Estate")}
    top_sector = max(equity_sectors.values(), default=0)
    score = (min(eff_holdings / 15, 1) * 40
             + len(classes_present) / 5 * 30
             + max(0, min(1, (1 - top_sector) / 0.75)) * 30)          # full at <=25%, zero at 100%
    risk = sum(r["weight"] * RISK_SCORE[r["info"]["asset_type"]] for r in rows)

    warnings = []
    for r in rows:
        if r["weight"] > 0.20:
            warnings.append(f"{r['ticker']} is {r['weight']:.0%} of your portfolio (single-holding concentration).")
        if r["info"].get("expense_ratio", 0) > 0.005:
            warnings.append(f"{r['ticker']} has a high expense ratio ({r['info']['expense_ratio']:.2%}).")
    for s, w in equity_sectors.items():
        if w > 0.40:
            warnings.append(f"{s} makes up {w:.0%} of your portfolio once fund holdings are included.")
    if risk > TOLERANCE_MAX_RISK.get(risk_tolerance, 3.75):
        warnings.append(f"Portfolio risk level ({risk:.1f}/5) is above your stated {risk_tolerance} tolerance.")
    if "International" not in classes_present:
        warnings.append("No international exposure.")
    if skipped:
        warnings.append(f"Unknown tickers skipped: {', '.join(skipped)}.")

    cost_total = sum(r["cost_basis"] * r["shares"] for r in rows if r["cost_basis"] is not None)
    priced_cb = [r for r in rows if r["cost_basis"] is not None]
    gain = sum(r["gain_loss"] for r in priced_cb) if priced_cb else None
    moved = [r for r in rows if r["day_change"] is not None]
    day_change = sum(r["day_change"] for r in moved) if moved else None
    prev_value = sum(r["value"] - r["day_change"] for r in moved)
    return {
        "empty": False,
        "total_value": round(total, 2),
        "total_gain_loss": round(gain, 2) if gain is not None else None,
        "total_cost": round(cost_total, 2) if priced_cb else None,
        "total_return_pct": gain / cost_total if gain is not None and cost_total else None,      # holdings with a cost basis only
        "day_change": round(day_change, 2) if day_change is not None else None,
        "day_change_pct": day_change / prev_value if moved and prev_value else None,
        "geography": [{"name": k, "weight": v} for k, v in sorted(geography.items(), key=lambda x: -x[1])],
        "movers": _movers(rows),
        "holdings": [{k: v for k, v in r.items() if k != "info"} | {"asset_class": ASSET_CLASS[r["info"]["asset_type"]]} for r in rows],
        "allocation": [{"name": k, "weight": v} for k, v in sorted(alloc.items(), key=lambda x: -x[1])],
        "sectors": [{"name": k, "weight": v} for k, v in sorted(sectors.items(), key=lambda x: -x[1])],
        "annual_fee": round(annual_fee, 2),
        "weighted_expense_ratio": annual_fee / total,
        "diversification_score": round(score),
        "effective_holdings": round(eff_holdings, 1),
        "risk_level": round(risk, 1),
        "risk_label": "Conservative" if risk < 2.5 else "Moderate" if risk < 3.75 else "High",
        "skipped": skipped,
        "warnings": warnings,
    }


def portfolio_performance(holdings: list[dict], series: dict[str, dict[str, float]], benchmark: dict[str, float] | None = None,
                          risk_free_rate: float = 0.04, trading_days: int = 252, default_start: str | None = None) -> dict:
    """Return and risk since the holdings were bought. holdings: analyze_portfolio rows; series: ticker -> {date: close};
    benchmark: {date: close}. Each holding counts in full from its purchase_date (default_start when it has none), or from its
    own first close when that is later or no date is given: a holding with a short history (a recent listing) does not hold
    the others back. Money arriving on a purchase date is not a gain: returns are time-weighted, and the benchmark line puts
    the same money into the index on the same dates. Cash has no series and counts at a constant value; any other holding
    without one is excluded."""
    counted = [h for h in holdings if h["ticker"] in series or h.get("asset_class") == "Cash"]
    excluded = [h["ticker"] for h in holdings if h not in counted]
    traded = set().union(*(series[h["ticker"]] for h in counted if h["ticker"] in series))
    if benchmark and len(traded & set(benchmark)) >= MIN_HISTORY_DAYS:
        traded &= set(benchmark)
    else:
        benchmark = None
    dates = sorted(traded)

    starts, clamped, pending = [], {}, []                # (holding, index of the first date it counts)
    for h in counted if dates else []:
        bought = h.get("purchase_date") or default_start
        listed = min(series[h["ticker"]]) if h["ticker"] in series else dates[0]
        k = bisect_left(dates, max(bought or listed, listed))
        if k == len(dates):
            pending.append(h["ticker"])                  # bought after the latest close: nothing to measure yet
            continue
        if bought and bought < listed:
            clamped[h["ticker"]] = dates[k]              # bought before its price history starts
        starts.append((h, k))
    first = min((k for _, k in starts), default=0)
    dates = dates[first:] if starts else []
    out = {"days": len(dates), "start": dates[0] if dates else None, "end": dates[-1] if dates else None, "points": [],
           "excluded": excluded, "pending": pending, "clamped": list(clamped), "clamped_from": clamped, "default_start": default_start,
           "assumed": [h["ticker"] for h, _ in starts if default_start and not h.get("purchase_date")],
           "period_return": None, "annualized_return": None, "volatility": None, "max_drawdown": None, "sharpe": None, "sortino": None,
           "benchmark_return": None, "excess_return": None}
    if not dates:
        return out

    closes = {}                                          # ticker -> {date: latest close up to it}, so a missing day carries the last one
    for t in {h["ticker"] for h, _ in starts if h["ticker"] in series}:
        own = sorted(series[t])
        closes[t] = {d: series[t][own[bisect_right(own, d) - 1]] for d in dates if d >= own[0]}
    amount = lambda h, d: h["shares"] * closes[h["ticker"]][d] if h["ticker"] in closes else h["value"]  # noqa: E731
    active, returns, units, value = [], [], 0.0, 0.0
    growth, peak, drawdown = 1.0, 1.0, 0.0               # growth of $1 held throughout, so purchases don't look like gains
    for k, d in enumerate(dates, start=first):
        if active:
            returns.append(sum(amount(h, d) for h in active) / value - 1)
            growth *= 1 + returns[-1]
            peak = max(peak, growth)
            drawdown = min(drawdown, growth / peak - 1)
        for h, start in starts:
            if start == k:
                active.append(h)
                units += amount(h, d) / benchmark[d] if benchmark else 0
        value = sum(amount(h, d) for h in active)
        out["points"].append({"date": d, "value": round(value, 2), "benchmark": round(units * benchmark[d], 2) if benchmark else None})
    if not returns:
        return out
    out |= {"period_return": growth - 1, "max_drawdown": drawdown}
    if benchmark:
        out["benchmark_return"] = benchmark[dates[-1]] / benchmark[dates[0]] - 1
        out["excess_return"] = out["period_return"] - out["benchmark_return"]
    if len(dates) < MIN_HISTORY_DAYS:                    # too few days for the annualized figures to mean anything
        return out
    span = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
    mean = sum(returns) / len(returns)
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
    daily_rf = risk_free_rate / trading_days
    downside = math.sqrt(sum(min(r - daily_rf, 0) ** 2 for r in returns) / len(returns))
    out |= {"annualized_return": growth ** (365 / span) - 1, "volatility": std * math.sqrt(trading_days),
            "sharpe": (mean - daily_rf) / std * math.sqrt(trading_days) if std else None,
            "sortino": (mean - daily_rf) / downside * math.sqrt(trading_days) if std and downside else None}
    return out


def project_goal(target: float, years: int, current: float, monthly: float, annual_return: float) -> dict:
    """Monthly-compounded projection plus the monthly contribution needed to hit `target`."""
    if years <= 0:
        raise ValueError("horizon must be at least 1 year")
    r = annual_return / 12
    n = years * 12

    def fv(pmt: float, months: int) -> float:
        growth = (1 + r) ** months
        return current * growth + (pmt * ((growth - 1) / r) if r else pmt * months)

    growth_n = (1 + r) ** n
    annuity = ((growth_n - 1) / r) if r else n
    required = max(0.0, (target - current * growth_n) / annuity)
    series = [{"year": y, "projected": round(fv(monthly, y * 12), 2),
               "contributed": round(current + monthly * y * 12, 2),
               "target": target} for y in range(years + 1)]
    projected = fv(monthly, n)
    return {"projected_value": round(projected, 2), "target": target, "on_track": projected >= target,
            "shortfall": round(max(0.0, target - projected), 2), "required_monthly": math.ceil(required * 100) / 100,
            "annual_return_assumption": annual_return, "series": series}


# ---------------------------------------------------------------- general calculators (the Calculator agent)
# Rates are percentages (6 means 6%). Each returns the result plus what's needed to show the working.
def _rate(pct: float, name: str = "rate") -> float:
    if not -50 <= pct <= 100:
        raise ValueError(f"{name} of {pct}% looks wrong; give it as a percentage, e.g. 6 for 6%")
    return pct / 100


def future_value(annual_rate: float, years: float, principal: float = 0.0, monthly_contribution: float = 0.0,
                 compounds_per_year: int | None = None) -> dict:
    """Value of a lump sum and/or regular monthly deposits after `years`. Compounds yearly for a lump sum alone,
    monthly when there are monthly deposits, unless told otherwise."""
    if years <= 0 or years > 100:
        raise ValueError("years must be between 0 and 100")
    if principal < 0 or monthly_contribution < 0 or (principal == 0 and monthly_contribution == 0):
        raise ValueError("need a starting amount and/or a monthly contribution")
    r = _rate(annual_rate)
    n = compounds_per_year or (12 if monthly_contribution else 1)

    def value_at(t: float) -> float:
        lump = principal * (1 + r / n) ** (n * t)
        months, rm = round(t * 12), (1 + r / n) ** (n / 12) - 1          # monthly rate equivalent to the compounding
        deposits = monthly_contribution * (((1 + rm) ** months - 1) / rm if rm else months)
        return lump + deposits

    fv = value_at(years)
    contributed = principal + monthly_contribution * round(years * 12)
    marks = sorted({y for y in (1, 5, 10, 20, 30) if y < years} | {years})
    return {"future_value": round(fv, 2), "contributed": round(contributed, 2), "growth": round(fv - contributed, 2),
            "compounds_per_year": n, "table": [(y, round(value_at(y), 2)) for y in marks]}


def present_value(future_amount: float, annual_rate: float, years: float, compounds_per_year: int = 1) -> dict:
    """What an amount received in `years` is worth today, discounted at `annual_rate`."""
    if future_amount <= 0 or years <= 0:
        raise ValueError("need a positive future amount and number of years")
    r = _rate(annual_rate)
    pv = future_amount / (1 + r / compounds_per_year) ** (compounds_per_year * years)
    return {"present_value": round(pv, 2), "discount": round(future_amount - pv, 2), "compounds_per_year": compounds_per_year}


def loan_payment(principal: float, annual_rate: float, years: float) -> dict:
    """Fixed monthly payment that repays a loan (e.g. a mortgage) over `years`."""
    if principal <= 0 or years <= 0:
        raise ValueError("need a positive loan amount and term")
    r, n = _rate(annual_rate) / 12, round(years * 12)
    pay = principal / n if r == 0 else principal * r / (1 - (1 + r) ** -n)
    return {"monthly_payment": round(pay, 2), "total_paid": round(pay * n, 2), "total_interest": round(pay * n - principal, 2), "months": n}


def doubling_time(annual_rate: float) -> dict:
    """Years to double at `annual_rate`: Rule of 72 estimate and the exact figure (yearly compounding)."""
    r = _rate(annual_rate)
    if r <= 0:
        raise ValueError("the rate must be above 0% for money to double")
    return {"rule_of_72": round(72 / annual_rate, 2), "exact": round(math.log(2) / math.log(1 + r), 2)}


def real_return(nominal_rate: float, inflation_rate: float) -> dict:
    """Return after inflation: exact (Fisher) and the quick nominal-minus-inflation estimate."""
    n, i = _rate(nominal_rate, "return"), _rate(inflation_rate, "inflation")
    return {"real_rate": round(((1 + n) / (1 + i) - 1) * 100, 3), "approximate": round(nominal_rate - inflation_rate, 3)}


def apy_from_apr(apr: float, compounds_per_year: int = 12) -> dict:
    """Annual percentage yield earned on a nominal rate compounded `compounds_per_year` times."""
    if compounds_per_year < 1:
        raise ValueError("compounds per year must be at least 1")
    return {"apy": round(((1 + _rate(apr) / compounds_per_year) ** compounds_per_year - 1) * 100, 3)}


def percent_change(amount: float, percent: float) -> dict:
    """An amount (a share price, a balance) after rising or falling by `percent` (negative for a fall)."""
    if amount <= 0:
        raise ValueError("need a positive starting amount")
    if percent <= -100:
        raise ValueError("a fall of 100% or more would leave nothing")
    change = amount * percent / 100
    return {"new_amount": round(amount + change, 4), "change": round(change, 4)}


def bond_current_yield(annual_coupon: float, price: float) -> dict:
    """Annual coupon income as a percentage of the bond's current price."""
    if annual_coupon < 0 or price <= 0:
        raise ValueError("need a coupon of 0 or more and a positive price")
    return {"current_yield": round(annual_coupon / price * 100, 3)}


def purchasing_power(amount: float, inflation_rate: float, years: float) -> dict:
    """What `amount` will buy after `years` of inflation, in today's money, and what the same goods will cost then."""
    if amount <= 0 or years <= 0:
        raise ValueError("need a positive amount and number of years")
    factor = (1 + _rate(inflation_rate, "inflation")) ** years
    return {"real_value": round(amount / factor, 2), "future_cost": round(amount * factor, 2),
            "lost_pct": round((1 - 1 / factor) * 100, 1)}
