"""Portfolio report data for tickers outside the bundled sample set, with the market service faked (no Yahoo calls)."""
from datetime import date

import pytest

from src.core import portfolio_data as P
from src.core.calculators import analyze_portfolio
from src.core.market_service import NotAFund, SymbolNotFound

FUNDS = {
    "XLK": {"category": "Technology", "asset_classes": [{"name": "Stocks", "weight": 0.99}], "operations": {"expense_ratio": 0.0009},
            "sector_weights": [{"name": "Technology", "weight": 0.9}, {"name": "Communication services", "weight": 0.1}]},
    "SCHF": {"category": "Foreign Large Blend", "asset_classes": [{"name": "Stocks", "weight": 0.98}], "operations": {"expense_ratio": None},
             "sector_weights": [{"name": "Financial services", "weight": 0.3}, {"name": "Consumer cyclical", "weight": 0.2},
                                {"name": "Consumer defensive", "weight": 0.1}, {"name": "Industrials", "weight": 0.4}]},
    "AGG": {"category": "Intermediate Core Bond", "asset_classes": [{"name": "Bonds", "weight": 0.97}, {"name": "Cash", "weight": 0.03}],
            "operations": {"expense_ratio": 0.0003}, "sector_weights": []},
}
STOCKS = {"KO": {"sector": "Consumer Defensive", "actions": {"dividends": [
    {"date": "2026-09-15", "amount": 0.5}, {"date": "2026-06-15", "amount": 0.5}, {"date": "2025-06-15", "amount": 0.4}, {"date": None, "amount": 1.0}]}}}
QUOTES = {"XLK": (200.0, "live"), "SCHF": (20.0, "cached"), "AGG": (100.0, "live"), "KO": (60.0, "live"), "^RUT": (2000.0, "live")}


@pytest.fixture
def market(monkeypatch):
    def fake(db, endpoint, symbol, **_):
        if endpoint == "quote":
            if symbol not in QUOTES:
                raise SymbolNotFound(symbol)
            price, freshness = QUOTES[symbol]
            data = {"symbol": symbol, "name": f"{symbol} name", "price": price, "prev_close": price - 1}
        elif endpoint == "fund":
            if symbol not in FUNDS:
                raise NotAFund(symbol, "a stock")
            data, freshness = FUNDS[symbol], "cached"
        else:
            if symbol not in STOCKS:
                raise NotAFund(symbol, "an index")
            data, freshness = STOCKS[symbol], "cached"
        return {"data": data, "provider": "yfinance", "fetched_at": "2026-10-02T12:00:00+00:00", "freshness": freshness}
    monkeypatch.setattr(P, "get_market_data", fake)


def test_instruments_are_classified_from_fund_and_stock_profiles(market):
    inst, info = P.portfolio_instruments(object(), ["xlk", "SCHF", "AGG", "KO", "^RUT", "NOPE", "CASH"])
    assert set(inst) == {"XLK", "SCHF", "AGG", "KO", "CASH"}                       # an index and an unknown ticker are left out
    assert inst["XLK"]["asset_type"] == "thematic_etf" and inst["XLK"]["expense_ratio"] == 0.0009 and inst["XLK"]["prev_close"] == 199.0
    assert inst["SCHF"]["asset_type"] == "intl_etf" and inst["SCHF"]["expense_ratio"] == 0
    assert inst["SCHF"]["sector_breakdown"] == {"Financials": 0.3, "Consumer": pytest.approx(0.3), "Industrials": 0.4}
    assert inst["AGG"]["asset_type"] == "bond_etf" and inst["AGG"]["sector_breakdown"] == {"Bonds": 1.0}
    assert inst["KO"] == {"name": "KO name", "asset_type": "stock", "sector": "Consumer", "expense_ratio": 0, "price": 60.0, "prev_close": 59.0}
    assert inst["CASH"]["price"] == 1.0
    assert info == {"provider": "yfinance", "fetched_at": "2026-10-02T12:00:00+00:00", "freshness": "cached"}      # the least fresh quote
    a = analyze_portfolio([{"ticker": t, "shares": 1} for t in inst], inst)
    assert not a["empty"] and {g["name"] for g in a["geography"]} == {"US stocks", "International stocks", "Bonds", "Cash"}


def test_without_a_database_only_bundled_prices_are_used():
    inst, info = P.portfolio_instruments(None, ["VTI", "KO", "CASH"])
    assert set(inst) == {"VTI", "CASH"} and inst["VTI"]["price"] == 288.0 and info["freshness"] == "sample"


def test_dividends_cover_the_last_twelve_months(market):
    holdings = [{"ticker": "KO", "name": "Coca-Cola", "shares": 10, "value": 600.0}, {"ticker": "CASH", "name": "Cash", "shares": 400, "value": 400.0},
                {"ticker": "^RUT", "name": "index", "shares": 1, "value": 0.0}]
    d = P.portfolio_dividends(object(), holdings, today=date(2026, 10, 2))
    assert d["total"] == 10.0 and d["yield"] == pytest.approx(0.01)                 # the 2025 payment is too old
    assert d["by_month"] == [{"month": "2026-06", "amount": 5.0}, {"month": "2026-09", "amount": 5.0}]
    assert d["by_holding"] == [{"ticker": "KO", "name": "Coca-Cola", "amount": 10.0, "yield": pytest.approx(10 / 600)}]


def test_history_reaches_back_to_the_earliest_purchase():
    today = date(2026, 10, 2)
    assert P._history_days("2026-01-01", today) == 250 and P._history_days("2025-03-01", today) == 750
    assert P._history_days("2022-06-01", today) == 1250 and P._history_days("1999-01-01", today) == 2520      # 10 years at most
