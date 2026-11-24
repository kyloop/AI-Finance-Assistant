"""The Portfolio agent's report: sections chosen by the question, figures with plain explanations (src/workflow/portfolio_report.py)."""
import pytest

from src.core.calculators import analyze_portfolio
from src.core.market_service import INSTRUMENTS
from src.workflow import portfolio_report as PR

HOLDINGS = [{"ticker": "NVDA", "shares": 50, "cost_basis": 45.0}, {"ticker": "QQQ", "shares": 10},
            {"ticker": "BND", "shares": 20}, {"ticker": "VXUS", "shares": 15}]
PERF = {"start": "2026-01-02", "period_return": 0.20, "annualized_return": 0.25, "benchmark_return": 0.05, "excess_return": 0.15,
        "benchmark": {"symbol": "^GSPC", "name": "S&P 500"}, "volatility": 0.30, "benchmark_volatility": 0.15,
        "max_drawdown": -0.20, "benchmark_max_drawdown": -0.10, "sharpe": 0.8, "risk_free_rate": 0.04, "assumed": [],
        "default_start": "2026-01-01", "contributions": [{"ticker": "NVDA", "contribution": 0.16}, {"ticker": "QQQ", "contribution": 0.05},
                                                         {"ticker": "BND", "contribution": -0.01}]}


@pytest.mark.parametrize("q, sections", [
    ("Is my portfolio diversified?", ["diversification"]),
    ("Is my portfolio too tech-heavy?", ["diversification"]),
    ("How did my portfolio perform against the market?", ["performance"]),
    ("How risky and how volatile are my holdings?", ["risk"]),
    ("What fees am I paying?", ["fees"]),
    ("How much dividend income do I get?", ["income"]),
    ("Analyse my portfolio", PR.SECTIONS),
    ("Give me a detailed review of my portfolio's risk", PR.SECTIONS),
    ("What about my portfolio?", PR.SECTIONS),
])
def test_focus_follows_the_question(q, sections):
    assert PR.focus(q) == sections


def test_full_report_explains_each_figure():
    a = analyze_portfolio(HOLDINGS, INSTRUMENTS, "moderate")
    div = {"total": 30.0, "yield": 0.002, "by_holding": [{"ticker": "BND", "amount": 30.0, "yield": 0.02}], "by_month": []}
    r = PR.report(a, PERF, div, PR.SECTIONS, "moderate")
    for heading in ("**Diversification**", "**Performance**", "**Risk**", "**Fees**", "**Dividend income**", "| Holding |"):
        assert heading in r
    assert "+16.0 pts" in r and "NVDA alone produced most of the gain" in r          # what drove the return
    assert "15.0 points ahead of" in r and "about 2.0× as bumpy" in r
    assert "What holds the score back most" in r and "none in" in r                  # why the score is what it is
    assert f"${0.20 * a['total_value']:,.0f}" in r                                     # the drawdown in dollars
    assert "modest return for the swings taken" in r and "not a forecast" in r


def test_report_without_price_history_says_so():
    a = analyze_portfolio(HOLDINGS, INSTRUMENTS, "moderate")
    r = PR.report(a, None, None, ["performance", "risk"], "moderate")
    assert "isn't available right now" in r and "Volatility" not in r and "Contribution" not in r
    assert "**Diversification**" not in r
