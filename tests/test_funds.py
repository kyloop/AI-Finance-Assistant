"""Fund / ETF profiles for the Research tab: yfinance `funds_data` normalised (Yahoo's quirks fixed), the sample fallback,
and the API's messages for symbols that aren't funds."""
import pandas as pd
import pytest

from src.core import market_service as M

NA = pd.NA


class FakeFundsData:
    """Shaped like yfinance 1.7.0's FundsData for VOO (values as Yahoo returned them on 2026-10-02)."""
    description = "Tracks the S&P 500."
    fund_overview = {"categoryName": "Large Blend", "family": "Vanguard", "legalType": "Exchange Traded Fund"}
    fund_operations = pd.DataFrame({"VOO": [0.0003, 0.0, 514320.12], "Category Average": [0.0072, 0.9461, 514320.12]},
                                   index=["Annual Report Expense Ratio", "Annual Holdings Turnover", "Total Net Assets"])
    asset_classes = {"cashPosition": 0.0007, "stockPosition": 0.9987, "bondPosition": 0.0, "otherPosition": 0.0006}
    equity_holdings = pd.DataFrame({"VOO": [0.04033, 0.18928, 0.27319, 0.0526, 514320.12, 19.4],
                                    "Category Average": [0.04351, 0.20568, NA, NA, NA, NA]},
                                   index=["Price/Earnings", "Price/Book", "Price/Sales", "Price/Cashflow", "Median Market Cap", "3 Year Earnings Growth"])
    bond_holdings = pd.DataFrame({"VOO": [NA, NA, NA], "Category Average": [4.6, NA, NA]}, index=["Duration", "Maturity", "Credit Quality"])
    bond_ratings = {"aa": 0.7254, "aaa": 0.0309, "bbb": 0.1225, "us_government": 0.5179}
    sector_weightings = {"technology": 0.3872, "financial_services": 0.1202, "realestate": 0.018}

    @property
    def top_holdings(self):
        raise ValueError("The truth value of a DataFrame is ambiguous")          # what mutual funds sometimes do inside yfinance

    def quote_type(self):
        return "ETF"


def test_fund_payload_fixes_yahoos_quirks_and_survives_a_failing_field():
    d = M._fund_payload("VOO", "Vanguard S&P 500 ETF", "ETF", FakeFundsData(), {"totalAssets": 1.75e12, "yield": 0.0104})
    assert d["equity"]["pe"] == 24.8 and d["equity"]["pb"] == 5.3 and d["equity"]["category_pe"] == 23.0     # inverted back
    assert d["equity"]["median_market_cap"] == pytest.approx(514_320_120_000) and d["equity"]["earnings_growth_3y"] == pytest.approx(0.194)
    assert d["total_assets"] == 1.75e12                                   # from info, not the bogus "Total Net Assets"
    assert d["operations"]["expense_ratio"] == 0.0003 and d["operations"]["turnover"] is None   # 0 = not reported
    assert d["top_holdings"] == [] and d["category"] == "Large Blend"     # a failing field doesn't lose the rest
    assert [a["name"] for a in d["asset_classes"]] == ["Stocks", "Cash", "Other"]                # bonds 0 dropped
    assert d["sector_weights"][0] == {"name": "Technology", "weight": 0.3872}
    assert [r["name"] for r in d["bond_ratings"]] == ["AAA", "AA", "BBB"] and d["government_share"] == 0.5179   # not a rating
    assert d["bond"]["category_duration"] == 4.6 and d["bond"]["duration"] is None


class FakeTicker:
    def __init__(self, kind, fund=True):
        self.kind, self.fund = kind, fund

    @property
    def funds_data(self):
        if not self.fund:
            raise RuntimeError("No Fund data found")
        return FakeFundsData()

    @property
    def info(self):
        if self.kind is None:
            raise RuntimeError("network down")
        return {"quoteType": self.kind, "longName": "Vanguard S&P 500 ETF", "totalAssets": 1.75e12}


def test_yf_fund_tells_a_stock_from_a_missing_fund(monkeypatch):
    monkeypatch.setattr(M, "_yf_ticker", lambda s: FakeTicker("ETF"))
    assert M._yf_fund("VOO")["name"] == "Vanguard S&P 500 ETF"
    monkeypatch.setattr(M, "_yf_ticker", lambda s: FakeTicker("EQUITY", fund=False))
    with pytest.raises(M.NotAFund) as e:
        M._yf_fund("AAPL")
    assert e.value.kind == "a stock"
    monkeypatch.setattr(M, "_yf_ticker", lambda s: FakeTicker(None, fund=False))
    with pytest.raises(M.ProviderEmpty):                                  # can't tell: try the next provider
        M._yf_fund("VOO")


def test_fund_api_on_sample_data(client):
    voo = client.get("/api/market/fund/voo").json()
    assert voo["freshness"] == "sample" and voo["data"]["name"] == "Vanguard S&P 500 ETF"
    assert voo["data"]["sector_weights"][0]["name"] == "Technology" and voo["data"]["operations"]["expense_ratio"] == 0.0003
    bnd = client.get("/api/market/fund/BND").json()["data"]
    assert bnd["asset_classes"] == [{"name": "Bonds", "weight": 1.0}] and bnd["sector_weights"] == []
    assert client.get("/api/market/fund/SPAXX").json()["data"]["quote_type"] == "MUTUALFUND"


def test_fund_api_explains_symbols_that_are_not_funds(client):
    r = client.get("/api/market/fund/AAPL")
    assert r.status_code == 404 and r.json()["detail"].startswith("AAPL is a stock, not a fund")
    assert "an index, not a fund" in client.get("/api/market/fund/^GSPC").json()["detail"]
    r = client.get("/api/market/fund/ZZZZ")
    assert r.status_code == 404 and "couldn't find" in r.json()["detail"]


# ------------------------------------------------------------------ Stock research (corporate actions, statements, earnings)
def _ts(*days):
    return pd.DatetimeIndex([pd.Timestamp(d, tz="America/New_York") for d in days])


class FakeStock:
    """Shaped like yfinance 1.7.0's Ticker for AAPL (values as Yahoo returned them on 2026-10-02)."""
    dividends = pd.Series([0.26, 0.26, 0.27], index=_ts("2025-11-10", "2026-02-09", "2026-05-11"))
    splits = pd.Series([7.0, 4.0], index=_ts("2014-06-09", "2020-08-31"))
    capital_gains = pd.Series([], dtype=object)
    income_stmt = pd.DataFrame({pd.Timestamp("2025-09-30"): [4.16e11, 1.12e11, 7.46, 1.0], pd.Timestamp("2024-09-30"): [3.91e11, 9.37e10, 6.08, 2.0]},
                               index=["Total Revenue", "Net Income", "Diluted EPS", "Tax Effect Of Unusual Items"])
    quarterly_income_stmt = ttm_income_stmt = balance_sheet = quarterly_balance_sheet = cash_flow = quarterly_cash_flow = ttm_cash_flow = pd.DataFrame()
    calendar = {"Earnings Date": [pd.Timestamp("2026-10-29").date()], "Earnings Low": 1.93, "Earnings Average": 1.98, "Earnings High": 2.07,
                "Ex-Dividend Date": pd.Timestamp("2026-08-09").date()}
    earnings_history = pd.DataFrame({"epsActual": [2.02], "epsEstimate": [1.89], "surprisePercent": [0.0674]}, index=[pd.Timestamp("2026-06-30")])
    earnings_estimate = pd.DataFrame({"avg": [1.98], "numberOfAnalysts": [27], "growth": [0.0695]}, index=["0q"])
    revenue_estimate = eps_trend = pd.DataFrame()
    eps_revisions = pd.DataFrame({"upLast7days": [1], "downLast7Days": [0]}, index=["0q"])     # Yahoo's mixed capitalisation
    growth_estimates = pd.DataFrame({"stockTrend": [0.0851, NA], "indexTrend": [0.1579, 0.122]}, index=["+1y", "LTG"])

    def get_shares_full(self, start=None):
        return pd.Series([100, 101, 99], index=_ts("2026-01-05", "2026-01-05", "2026-03-02"))         # duplicate day

    def get_earnings_dates(self, limit=12):
        idx = _ts(*[f"20{26 - i // 4}-{(i % 4) * 3 + 1:02d}-15" for i in range(25)])             # 25 rows: Yahoo ignores `limit`
        return pd.DataFrame({"EPS Estimate": 1.9, "Reported EPS": 2.0, "Surprise(%)": 6.74}, index=idx)

    @property
    def quarterly_balance_sheet(self):
        raise RuntimeError("Yahoo hiccup")                                      # one failing piece must not lose the rest


def test_stock_payload_normalises_units_and_keeps_the_key_lines():
    d = M._stock_payload("AAPL", FakeStock(), {"longName": "Apple Inc.", "sector": "Technology"}, "EQUITY")
    a = d["actions"]
    assert a["dividends"][0] == {"date": "2026-05-11", "amount": 0.27}                                 # newest first
    assert a["dividends_by_year"] == [{"year": 2025, "amount": 0.26}, {"year": 2026, "amount": 0.53}]
    assert a["splits"][0] == {"date": "2020-08-31", "ratio": 4.0} and a["capital_gains"] == []
    assert a["shares"] == [{"date": "2026-03-31", "shares": 99}]                                       # last report of the quarter
    inc = d["statements"]["income"]["annual"]
    assert inc["periods"] == ["2025-09-30", "2024-09-30"]
    assert [r["name"] for r in inc["rows"]] == ["Total Revenue", "Net Income", "Diluted EPS"]          # raw noise rows dropped
    assert d["statements"]["balance"]["quarterly"] == {"periods": [], "rows": []} and d["statements"]["balance"]["ttm"]["rows"] == []
    e = d["earnings"]
    assert len(e["dates"]) == 12 and e["dates"][0]["surprise"] == pytest.approx(0.0674)                 # percent -> fraction
    assert e["history"][0]["surprise"] == pytest.approx(0.0674) and e["next"]["date"] == "2026-10-29"
    assert e["next"]["ex_dividend_date"] == "2026-08-09"
    assert e["eps_estimate"][0] == {"period": "Current quarter", "avg": 1.98, "low": None, "high": None, "year_ago": None, "analysts": 27, "growth": 0.0695}
    assert e["eps_revisions"][0]["up_7d"] == 1 and e["eps_revisions"][0]["down_7d"] == 0
    assert e["growth"][-1] == {"period": "Long-term growth", "stock": None, "index": 0.122}


def test_stock_payload_for_a_fund_has_dividends_but_no_company_data():
    d = M._stock_payload("VOO", FakeStock(), {"longName": "Vanguard S&P 500 ETF"}, "ETF")
    assert d["actions"]["dividends"] and d["statements"]["income"]["annual"]["rows"] == [] and d["earnings"]["dates"] == []


def test_stock_api_on_sample_data_and_for_an_index(client):
    r = client.get("/api/market/stock/AAPL").json()
    assert r["freshness"] == "sample" and r["data"]["name"] == "Apple Inc." and r["data"]["statements"]["income"]["annual"]["rows"] == []
    r = client.get("/api/market/stock/^GSPC")
    assert r.status_code == 404 and r.json()["detail"].startswith("^GSPC is an index, so it has no company data")
