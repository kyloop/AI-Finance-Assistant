"""Market tools (src/workflow/market_tools.py) and the market agent's tool calling.

Every tool is tested directly against the bundled sample data (conftest keeps market data offline), then through the agent with a
fake tool-calling LLM: the model's choice of tools and arguments, the call limit, rejected calls, fallbacks, and where the figures
end up (market_data, the answer text, the synthesizer's prompt, the saved context)."""
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.orm import sessionmaker

from src.core import llm as llm_module
from src.core import market_service
from src.workflow import market_tools as MT
from src.workflow.graph import run_chat

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate", "horizon_years": 10, "goals": []}


@pytest.fixture
def db():
    from src.db.base import Base
    from src.db.session import make_engine
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


@pytest.fixture
def nvda_profile(monkeypatch):
    """Sample stock data has no valuation or earnings; give NVDA some, as Yahoo would."""
    real = market_service.PROVIDERS["sample"]["stock"]

    def stock(symbol, **kw):
        p = real(symbol, **kw)
        if symbol == "NVDA":
            p = {**p, "industry": "Semiconductors",
                 "valuation": {"trailing_pe": 52.3, "forward_pe": 31.4, "market_cap": 4.4e12, "beta": 1.7, "dividend_yield": 0.0002,
                               "fifty_two_week_low": 86.6, "fifty_two_week_high": 195.6, "average_volume": 1.8e8},
                 "earnings": {**p["earnings"], "next": {"date": "2026-11-19"},
                              "history": [{"quarter": "2026-07-31", "eps_estimate": 1.01, "eps_actual": 1.05, "surprise": 0.04}]},
                 "actions": {**p["actions"], "dividends_by_year": [{"year": 2025, "amount": 0.04}]}}
        return p
    monkeypatch.setitem(market_service.PROVIDERS["sample"], "stock", stock)


# ---------------------------------------------------------------- tools, called directly
def test_get_quote_returns_price_change_volume_and_day_range(db):
    q = MT.get_quote(db, ["nvda", "$VOO"])                          # case and cashtags are normalised
    assert set(q) == {"NVDA", "VOO"}
    nvda = q["NVDA"]["quote"]
    assert nvda["name"] == "NVIDIA Corp." and nvda["price"] > 0 and nvda["volume"] > 0
    assert nvda["day_low"] <= nvda["price"] <= nvda["day_high"] and isinstance(nvda["change_pct"], float)
    assert nvda["freshness"] == "sample" and nvda["source"] == "sample" and nvda["as_of"]


def test_get_quote_marks_unknown_symbols_and_caps_the_list(db, monkeypatch):
    assert MT.get_quote(db, ["ZZZZ"]) == {"ZZZZ": {"error": {"message": "no data for this symbol"}}}
    assert list(MT.get_quote(db, ["NVDA", "AAPL", "MSFT", "JPM", "VOO"])) == ["NVDA", "AAPL", "MSFT"]      # at most 3 per call


@pytest.mark.parametrize("bad", [[], "", ["!!"], [None]])
def test_get_quote_rejects_arguments_without_a_symbol(db, bad):
    with pytest.raises(MT.ToolError):
        MT.get_quote(db, bad)


def test_get_performance_returns_return_high_low_and_average_volume(db):
    p = MT.get_performance(db, ["NVDA"], "1y")["NVDA"]["period"]
    assert p["label"] == "last year"
    assert p["start_date"] < p["end_date"] and p["low"] <= p["start_price"] <= p["high"] and p["low"] <= p["end_price"] <= p["high"]
    assert p["return"] == pytest.approx(p["end_price"] / p["start_price"] - 1, abs=1e-4)
    assert p["annualised"] is None and p["avg_volume"] > 0 and p["partial"] is False and p["freshness"] == "sample"
    five = MT.get_performance(db, ["NVDA"], "5 years")["NVDA"]["period"]           # annualised only over a year or more
    assert five["annualised"] == pytest.approx((1 + five["return"]) ** (365.25 / _days(five)) - 1, abs=1e-3)


def _days(p) -> int:
    from datetime import date
    return (date.fromisoformat(p["end_date"]) - date.fromisoformat(p["start_date"])).days


def test_get_performance_flags_data_that_starts_later_than_asked(db):
    p = MT.get_performance(db, ["NVDA"], "20 years")["NVDA"]["period"]          # history reaches back ~10 years at most
    assert p["partial"] is True and p["label"] == "last 20 years"


def test_get_performance_rejects_an_unknown_period(db):
    with pytest.raises(MT.ToolError, match="unknown period"):
        MT.get_performance(db, ["NVDA"], "forever")


@pytest.mark.parametrize("period,label", [("1y", "last year"), ("6 months", "last 6 months"), ("10y", "last 10 years"),
                                          ("ytd", "year to date"), ("since 2015", "since 2015"), ("last year", "last year"),
                                          ("2 wks", "last 2 weeks"), ("a decade", "last 10 years")])
def test_parse_period_accepts_the_forms_the_model_sends(period, label):
    assert MT.parse_period(period)[1] == label


def test_get_company_profile_returns_sector_valuation_earnings_and_dividends(db, nvda_profile):
    p = MT.get_company_profile(db, "NVDA")["NVDA"]["profile"]
    assert p["sector"] == "Technology" and p["industry"] == "Semiconductors"
    assert p["trailing_pe"] == 52.3 and p["market_cap"] == 4.4e12 and p["next_earnings"] == "2026-11-19"
    assert p["eps_history"][0]["surprise"] == 0.04 and p["dividends_by_year"] == [{"year": 2025, "amount": 0.04}]
    assert p["freshness"] == "sample"


def test_get_company_profile_says_an_index_has_none(db):
    assert MT.get_company_profile(db, "^GSPC") == {"^GSPC": {"error": {"message": "^GSPC is an index; it has no company profile"}}}


def test_get_fund_profile_returns_expense_ratio_and_sectors(db):
    f = MT.get_fund_profile(db, "VOO")["VOO"]["fund"]
    assert f["name"] == "Vanguard S&P 500 ETF" and f["expense_ratio"] == 0.0003 and f["freshness"] == "sample"


def test_get_fund_profile_says_a_stock_is_not_a_fund(db):
    assert MT.get_fund_profile(db, "NVDA") == {"NVDA": {"error": {"message": "NVDA is a stock, not a fund"}}}


def test_run_tool_reports_unknown_tools_and_bad_arguments(db):
    assert MT.run_tool(db, "get_weather", {}) == ({"_error": "unknown tool 'get_weather'"}, "get_weather → unknown tool")
    data, note = MT.run_tool(db, "get_performance", {"symbols": ["NVDA"]})                          # period missing
    assert "_error" in data and note.startswith("get_performance(NVDA) → rejected")
    data, note = MT.run_tool(db, "get_quote", {"symbols": ["NVDA"]})
    assert "quote" in data["NVDA"] and note == "get_quote(NVDA) → sample"


def test_tool_specs_match_the_tools():
    specs = {s["function"]["name"]: s["function"] for s in MT.TOOL_SPECS}
    assert set(specs) == set(MT.TOOLS)
    assert all(s["description"] and set(s["parameters"]["required"]) <= set(s["parameters"]["properties"]) for s in specs.values())


def test_merge_market_combines_sections_per_symbol():
    merged = MT.merge_market({"TSLA": {"quote": {"price": 1}}}, {"TSLA": {"period": {"return": 0.1}}, "SBUX": {"quote": {"price": 2}}})
    assert merged == {"TSLA": {"quote": {"price": 1}, "period": {"return": 0.1}}, "SBUX": {"quote": {"price": 2}}}


def test_describe_lines_and_data_block_show_every_section(db, nvda_profile):
    data = MT.merge_market(MT.get_quote(db, ["NVDA", "ZZZZ"]), MT.get_performance(db, ["NVDA"], "1y"))
    data = MT.merge_market(data, MT.merge_market(MT.get_company_profile(db, "NVDA"), MT.get_fund_profile(db, "VOO")))
    text = "\n".join(MT.describe_lines(data))
    assert "**NVIDIA Corp.** (NVDA): $" in text and "volume" in text and "day range" in text
    assert "**NVIDIA Corp.**, last year:" in text and "average daily volume" in text      # the quote's name on the period line
    assert "P/E (trailing) 52.30" in text and "market cap $4.4T" in text and "next earnings 2026-11-19" in text
    assert "**Vanguard S&P 500 ETF** (VOO) fund: expense ratio 0.03%" in text and "_I don't have data for: ZZZZ._" in text
    block = MT.data_block(data)
    assert "NVDA quote: price=" in block and "volume=" in block and "NVDA profile:" in block and "trailing_pe=52.3" in block
    assert "ZZZZ" not in block and "change_pct=" in block and "%" in block


# ---------------------------------------------------------------- the agent calling them
class ToolLLM:
    """Routes to market and answers the market agent's tool request with scripted tool calls; records every prompt."""
    model = "tools"

    def __init__(self, calls=(), *, bind_fails=False, proofread=None):
        self.calls, self.bind_fails, self.proofread, self.prompts, self.bound = list(calls), bind_fails, proofread, [], None

    def bind_tools(self, tools):
        if self.bind_fails:
            raise NotImplementedError("this model can't call tools")
        self.bound = tools
        return self

    def invoke(self, messages):
        system, user = messages[0][1] if isinstance(messages[0], tuple) else messages[0].content, \
            messages[1][1] if isinstance(messages[1], tuple) else messages[1].content
        self.prompts.append((system, user))
        if "You fetch market data" in system:
            return AIMessage(content="", tool_calls=[{"name": n, "args": a, "id": f"call_{i}"} for i, (n, a) in enumerate(self.calls)])
        if "You are the router" in system:
            return AIMessage(content='{"intents": ["market"], "confidence": 0.9}')
        if "You are the proofreader" in system:
            return AIMessage(content=self.proofread or user.split("Message: ", 1)[-1])
        return AIMessage(content="Answer from the figures.")

    def prompt(self, marker: str) -> str:
        return next(u for s, u in self.prompts if marker in s)


def ask(db, q, llm, context=None):
    llm_module.set_llm(llm)
    return run_chat(q, history=[], profile=PROFILE, holdings=[], db=db, context=context)


def market_trace(s) -> str:
    return next(t for t in s["trace"] if t.startswith("market ("))


@pytest.mark.parametrize("call,section", [
    (("get_quote", {"symbols": ["NVDA"]}), "quote"),
    (("get_performance", {"symbols": ["NVDA"], "period": "6 months"}), "period"),
    (("get_company_profile", {"symbol": "NVDA"}), "profile"),
    (("get_fund_profile", {"symbol": "VOO"}), "fund"),
])
def test_each_tool_can_be_called_by_the_model(db, nvda_profile, call, section):
    llm = ToolLLM([call])
    s = ask(db, "Tell me about NVDA and VOO", llm)
    sym = call[1].get("symbol") or call[1]["symbols"][0]
    assert section in s["market_data"][sym] and market_trace(s).startswith("market (LLM tools): " + call[0])
    assert [t["function"]["name"] for t in llm.bound] == list(MT.TOOLS)                   # the model is offered every tool


def test_the_model_can_call_several_tools_in_one_reply(db, nvda_profile):
    s = ask(db, "What is NVDA's P/E and how has it done this year?", ToolLLM([
        ("get_quote", {"symbols": ["NVDA"]}), ("get_company_profile", {"symbol": "NVDA"}),
        ("get_performance", {"symbols": ["NVDA"], "period": "ytd"})]))
    nvda = s["market_data"]["NVDA"]
    assert set(nvda) == {"quote", "profile", "period"} and nvda["period"]["label"] == "year to date"
    out = s["agent_outputs"]["market"]["content"]
    assert "P/E (trailing) 52.30" in out and "year to date:" in out and "volume" in out


def test_a_quote_is_added_when_the_model_only_asked_for_a_profile(db, nvda_profile):
    s = ask(db, "What is NVDA's P/E?", ToolLLM([("get_company_profile", {"symbol": "NVDA"})]))
    assert set(s["market_data"]["NVDA"]) == {"profile", "quote"} and "get_quote(NVDA) → sample" in market_trace(s)
    assert s["agent_outputs"]["market"]["confidence"] == "high"


def test_tool_calls_beyond_the_limit_are_skipped(db):
    calls = [("get_quote", {"symbols": [s]}) for s in ("NVDA", "AAPL", "MSFT", "JPM", "VOO", "QQQ")]
    s = ask(db, "Quote NVDA", ToolLLM(calls))
    assert set(s["market_data"]) == {"NVDA", "AAPL", "MSFT", "JPM"}
    assert market_trace(s).count("skipped (limit of 4 tool calls)") == 2


def test_rejected_calls_are_traced_and_the_quote_is_still_fetched(db):
    s = ask(db, "How is NVDA doing?", ToolLLM([("get_performance", {"symbols": ["NVDA"], "period": "forever"}), ("get_weather", {})]))
    trace = market_trace(s)
    assert "get_performance(NVDA, forever) → rejected (unknown period" in trace and "get_weather → unknown tool" in trace
    assert "get_quote(NVDA) → sample" in trace and "quote" in s["market_data"]["NVDA"]          # filled in regardless


def test_a_model_that_calls_no_tools_still_gets_the_quote_and_the_asked_period(db):
    s = ask(db, "How has NVDA done over the last month?", ToolLLM([]))
    assert "get_quote(NVDA) → sample" in market_trace(s) and "get_performance(NVDA, last month) → sample" in market_trace(s)
    assert s["market_data"]["NVDA"]["period"]["label"] == "last month"


def test_a_model_without_tool_calling_falls_back_to_the_standard_figures(db):
    s = ask(db, "How is NVDA doing?", ToolLLM(bind_fails=True))
    assert "tool calling failed (NotImplementedError)" in market_trace(s) and "quote" in s["market_data"]["NVDA"]


def test_without_an_llm_the_agent_uses_the_same_tools(db):
    llm_module.set_llm(None)
    s = run_chat("How has NVDA done over the last month?", history=[], profile=PROFILE, holdings=[], db=db)
    assert market_trace(s).startswith("market (keywords): get_quote(NVDA) → sample; get_performance(NVDA, last month)")
    assert "volume" in s["final_response"] and "average daily volume" in s["final_response"]


def test_the_model_is_told_the_companies_period_and_earlier_figures(db):
    llm = ToolLLM([("get_quote", {"symbols": ["MSFT"]})], proofread='{"question": "Compare NVDA and MSFT.", "follow_up": true}')
    context = {"question": "How has NVDA done over the last month?", "companies": [{"symbol": "NVDA", "name": "NVIDIA Corporation"}],
               "period": {"start": "2026-09-02", "label": "last month"}, "facts": {"NVDA": {"price": 180.5, "as_of": "2026-10-02"}}}
    ask(db, "compare to MSFT", llm, context=context)
    prompt = llm.prompt("You fetch market data")
    assert "Companies: " in prompt and "MSFT" in prompt and "NVDA" in prompt
    assert "Period the conversation is about: last month" in prompt and "NVDA: price $180.50 on 2026-10-02" in prompt


def test_the_figures_reach_the_synthesizer_and_the_saved_context(db, nvda_profile):
    llm = ToolLLM([("get_quote", {"symbols": ["NVDA"]}), ("get_company_profile", {"symbol": "NVDA"})])
    s = ask(db, "What is NVDA's trading volume and P/E?", llm)
    synth = llm.prompt("You are Finnie")
    assert "Data (exact figures from the market tools" in synth and "NVDA quote:" in synth and "volume=" in synth and "trailing_pe=52.3" in synth
    facts = s["context"]["facts"]["NVDA"]
    assert facts["volume"] > 0 and facts["trailing_pe"] == 52.3 and facts["price"] > 0
    assert s["data_info"]["freshness"] == "sample"
