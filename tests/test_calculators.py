import pytest

from src.core.calculators import analyze_portfolio, portfolio_performance, project_goal
from src.core.market_service import INSTRUMENTS


def test_single_stock_is_flagged_and_scores_low():
    r = analyze_portfolio([{"ticker": "NVDA", "shares": 10}], INSTRUMENTS)
    assert r["diversification_score"] < 25
    assert any("NVDA" in w for w in r["warnings"])
    assert r["risk_label"] == "High"


def test_etf_look_through_counts_toward_sector():
    r = analyze_portfolio([{"ticker": "QQQ", "shares": 10}], INSTRUMENTS)
    tech = next(s for s in r["sectors"] if s["name"] == "Technology")
    assert tech["weight"] == pytest.approx(0.60)


def test_unknown_ticker_skipped_and_empty_portfolio():
    r = analyze_portfolio([{"ticker": "ZZZZ", "shares": 1}, {"ticker": "VTI", "shares": 1}], INSTRUMENTS)
    assert r["skipped"] == ["ZZZZ"] and not r["empty"]
    assert analyze_portfolio([], INSTRUMENTS)["empty"]


def test_missing_cost_basis_skips_gain_loss_only():
    r = analyze_portfolio([{"ticker": "VTI", "shares": 1}], INSTRUMENTS)
    assert r["holdings"][0]["gain_loss"] is None and r["total_value"] == 288.0


def test_goal_projection_hits_target_with_required_contribution():
    p = project_goal(100_000, 10, 5_000, 0, 0.06)
    hit = project_goal(100_000, 10, 5_000, p["required_monthly"], 0.06)
    assert hit["on_track"] and not p["on_track"]
    assert len(p["series"]) == 11


def test_goal_zero_horizon_rejected():
    with pytest.raises(ValueError):
        project_goal(1000, 0, 0, 10, 0.05)


# ------------------------------------------------------------------ portfolio report
def test_day_change_movers_and_geography():
    instruments = {"AAA": {"name": "A", "price": 110.0, "prev_close": 100.0, "asset_type": "stock", "sector": "Technology"},
                   "BBB": {"name": "B", "price": 45.0, "prev_close": 50.0, "asset_type": "intl_etf"},
                   "CCC": {"name": "C", "price": 10.0, "asset_type": "bond_etf"}}
    r = analyze_portfolio([{"ticker": "AAA", "shares": 10, "cost_basis": 55.0}, {"ticker": "BBB", "shares": 10, "cost_basis": 90.0},
                           {"ticker": "CCC", "shares": 10}], instruments)
    assert r["day_change"] == 50.0 and r["day_change_pct"] == pytest.approx(50 / 1500)       # +100 and -50; CCC has no previous close
    assert r["total_gain_loss"] == 100.0 and r["total_return_pct"] == pytest.approx(100 / 1450)
    assert r["movers"]["basis"] == "total"
    assert [m["ticker"] for m in r["movers"]["winners"]] == ["AAA"] and [m["ticker"] for m in r["movers"]["losers"]] == ["BBB"]
    assert {g["name"]: round(g["weight"], 4) for g in r["geography"]} == {"US stocks": 0.6667, "International stocks": 0.2727, "Bonds": 0.0606}
    no_basis = analyze_portfolio([{"ticker": "AAA", "shares": 1}, {"ticker": "BBB", "shares": 1}], instruments)
    assert no_basis["movers"]["basis"] == "day" and no_basis["movers"]["losers"][0]["change"] == -5.0


def _dates(n):
    from datetime import date, timedelta
    return [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]


def test_portfolio_performance_on_a_known_series():
    dates = _dates(40)
    closes = [100.0] * 10 + [120.0] * 10 + [90.0] * 10 + [110.0] * 10            # peak 120, trough 90
    holdings = [{"ticker": "AAA", "shares": 10, "value": 1100.0, "asset_class": "Individual stocks"},
                {"ticker": "CASH", "shares": 1000, "value": 1000.0, "asset_class": "Cash"},
                {"ticker": "NOHIST", "shares": 1, "value": 5.0, "asset_class": "Individual stocks"}]
    p = portfolio_performance(holdings, {"AAA": dict(zip(dates, closes))}, dict(zip(dates, [50.0] * 39 + [55.0])))
    assert p["excluded"] == ["NOHIST"] and p["days"] == 40 and (p["start"], p["end"]) == (dates[0], dates[-1])
    assert p["points"][0] == {"date": dates[0], "value": 2000.0, "benchmark": 2000.0}             # cash counts at a constant $1,000
    assert p["period_return"] == pytest.approx(0.05) and p["benchmark_return"] == pytest.approx(0.10)
    assert p["excess_return"] == pytest.approx(-0.05)
    assert p["max_drawdown"] == pytest.approx(1900 / 2200 - 1)
    assert p["annualized_return"] == pytest.approx(1.05 ** (365 / 39) - 1)
    assert p["volatility"] > 0 and p["sharpe"] is not None and p["sortino"] is not None


def test_portfolio_performance_needs_enough_history():
    dates = _dates(10)
    holdings = [{"ticker": "AAA", "shares": 1, "value": 1.0, "asset_class": "Individual stocks"}]
    p = portfolio_performance(holdings, {"AAA": dict.fromkeys(dates, 1.0)})
    assert p["days"] == 10 and len(p["points"]) == 10 and p["period_return"] == 0             # a short stretch still has a return…
    assert p["annualized_return"] is None and p["volatility"] is None and p["sharpe"] is None       # …but nothing annualized
    flat = portfolio_performance(holdings, {"AAA": dict.fromkeys(_dates(40), 1.0)})         # no movement: ratios are undefined, not a crash
    assert flat["volatility"] == 0 and flat["sharpe"] is None and flat["sortino"] is None and flat["benchmark_return"] is None


def test_performance_counts_each_holding_from_its_purchase_date():
    dates = _dates(40)
    a = dict(zip(dates, [100.0] * 20 + [110.0] * 20))                             # +10% on day 20
    b = dict(zip(dates, [50.0] * 30 + [55.0] * 10))                               # +10% on day 30
    bench = dict(zip(dates, [10.0] * 25 + [11.0] * 15))                           # +10% on day 25
    holdings = [{"ticker": "AAA", "shares": 10, "value": 1100.0, "asset_class": "Individual stocks", "purchase_date": dates[5]},
                {"ticker": "BBB", "shares": 20, "value": 1100.0, "asset_class": "Individual stocks", "purchase_date": dates[22]},
                {"ticker": "CCC", "shares": 1, "value": 9.0, "asset_class": "Individual stocks", "purchase_date": "2030-01-01"},
                {"ticker": "DDD", "shares": 1, "value": 9.0, "asset_class": "Individual stocks"}]
    p = portfolio_performance(holdings, {"AAA": a, "BBB": b, "CCC": a, "DDD": a}, bench, default_start="2020-01-01")
    assert p["start"] == dates[0] and p["clamped"] == ["DDD"] and p["assumed"] == ["DDD"] and p["pending"] == ["CCC"]
    by_date = {x["date"]: x for x in p["points"]}
    assert by_date[dates[4]]["value"] == 100.0 and by_date[dates[5]]["value"] == 1100.0          # AAA arrives: value jumps…
    assert by_date[dates[22]]["value"] == 110.0 + 1100.0 + 1000.0
    # …but a purchase is not a gain: +10% on everything held on day 20, then +10% on BBB's 1,000 of 2,210 on day 30
    assert p["period_return"] == pytest.approx(1.10 * (1 + 100 / 2210) - 1)
    assert p["benchmark_return"] == pytest.approx(0.10)
    # the same money in the index on the same dates: all 2,100 went in before its rise on day 25
    assert by_date[dates[-1]]["benchmark"] == pytest.approx(2100 * 1.1)

    late = portfolio_performance(holdings[:1], {"AAA": a}, bench)
    assert late["start"] == dates[5] and late["days"] == 35 and late["clamped"] == [] and late["assumed"] == []


def test_performance_is_not_held_back_by_a_recent_listing():
    dates = _dates(40)
    old = dict(zip(dates, [100.0] * 10 + [110.0] * 30))                           # +10% on day 10, before NEW has any price
    new = {d: 20.0 for d in dates[25:] if d != dates[30]}                         # listed on day 25, one close missing
    holdings = [{"ticker": "OLD", "shares": 1, "value": 110.0, "asset_class": "Individual stocks"},
                {"ticker": "NEW", "shares": 5, "value": 100.0, "asset_class": "Individual stocks"},
                {"ticker": "CASH", "shares": 50, "value": 50.0, "asset_class": "Cash"}]
    p = portfolio_performance(holdings, {"OLD": old, "NEW": new}, default_start=dates[2])
    assert p["start"] == dates[2] and p["assumed"] == ["OLD", "NEW", "CASH"]      # OLD and cash count from the default date…
    assert p["clamped"] == ["NEW"] and p["clamped_from"] == {"NEW": dates[25]}    # …NEW only from its first close
    by_date = {x["date"]: x["value"] for x in p["points"]}
    assert by_date[dates[2]] == 150.0 and by_date[dates[24]] == 160.0 and by_date[dates[25]] == 260.0
    assert by_date[dates[30]] == 260.0                                            # the missing close carries the last one
    assert p["period_return"] == pytest.approx(160 / 150 - 1)                     # NEW arriving is not a gain
