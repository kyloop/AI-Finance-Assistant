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

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate", "horizon_years": 10}


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


# ---------------------------------------------------------------- levels above one company: sectors and the whole market
@pytest.fixture
def sectors(monkeypatch):
    """The 11 sector funds as sample instruments (the bundled data has none), XLK with live-style top holdings."""
    from src.rag import markets as MK
    for i, e in enumerate(e for e in MK.entries() if e["group"] == "sectors"):
        monkeypatch.setitem(market_service.INSTRUMENTS, e["symbol"], {"name": f"Select Sector SPDR {e['symbol']}", "price": 50.0 + 10 * i,
                                                                      "asset_type": "stock_etf", "expense_ratio": 0.0008})
    real = market_service.PROVIDERS["sample"]["fund"]

    def fund(symbol, **kw):
        f = real(symbol, **kw)
        if symbol == "XLK":
            f = {**f, "top_holdings": [{"symbol": "NVDA", "name": "NVIDIA Corp", "weight": 0.14},
                                       {"symbol": "AAPL", "name": "Apple Inc", "weight": 0.13},
                                       {"symbol": "MSFT", "name": "Microsoft Corp", "weight": 0.12},
                                       {"symbol": "ZZZZ", "name": "Delisted Co", "weight": 0.01}]}
        return f
    monkeypatch.setitem(market_service.PROVIDERS["sample"], "fund", fund)


def test_get_sector_performance_compares_the_sector_with_the_sp500_and_shows_its_largest_companies(db, sectors):
    s = MT.get_sector_performance(db, "XLK", "1 month")["XLK"]["sector"]
    xlk, spx = (MT.get_performance(db, [sym], "1 month")[sym]["period"]["return"] for sym in ("XLK", "^GSPC"))
    assert s["name"] == "Technology sector" and s["fund"] == "XLK" and s["label"] == "last month" and s["return"] == xlk
    assert s["benchmark"] == {"symbol": "^GSPC", "name": "S&P 500", "return": spx}
    assert s["vs_benchmark"] == pytest.approx(xlk - spx, abs=1e-4) and s["freshness"] == "sample"
    nvda = MT.get_performance(db, ["NVDA"], "1 month")["NVDA"]["period"]["return"]
    assert [(h["symbol"], h["weight"]) for h in s["holdings"]] == [("NVDA", 0.14), ("AAPL", 0.13), ("MSFT", 0.12), ("ZZZZ", 0.01)]
    assert s["holdings"][0]["return"] == nvda and s["holdings"][3]["return"] is None           # no history: shown without a figure


@pytest.mark.parametrize("named", ["XLK", "$xlk", "Technology sector", "tech stocks"])
def test_get_sector_performance_accepts_the_fund_symbol_or_the_sector_name(db, sectors, named):
    assert list(MT.get_sector_performance(db, named)) == ["XLK"]


@pytest.mark.parametrize("bad", ["AAPL", "gold", "", "the moon"])
def test_get_sector_performance_rejects_what_is_not_a_sector(db, sectors, bad):
    with pytest.raises(MT.ToolError, match="XLK \\(Technology\\)"):                          # the message lists the sectors
        MT.get_sector_performance(db, bad)


def test_get_market_overview_ranks_every_sector_and_lists_the_main_indices(db, sectors):
    o = MT.get_market_overview(db, "3 months")[MT.OVERVIEW_KEY]["overview"]
    assert o["label"] == "last 3 months" and [i["symbol"] for i in o["indices"]] == ["^GSPC", "^IXIC", "^DJI"]
    returns = [x["return"] for x in o["sectors"]]
    assert len(o["sectors"]) == 11 and returns == sorted(returns, reverse=True) and o["missing"] == []
    assert o["freshness"] == "sample" and o["start_date"] < o["end_date"]


def test_get_market_overview_lists_sectors_without_data(db, sectors, monkeypatch):
    monkeypatch.delitem(market_service.INSTRUMENTS, "XLRE")
    o = MT.get_market_overview(db)[MT.OVERVIEW_KEY]["overview"]
    assert o["label"] == "last month" and o["missing"] == ["XLRE"] and len(o["sectors"]) == 10


def test_sector_and_overview_figures_read_as_sentences(db, sectors):
    data = MT.merge_market(MT.get_sector_performance(db, "XLK"), MT.get_market_overview(db))
    text = "\n".join(MT.describe_lines(data))
    s = data["XLK"]["sector"]
    gap = abs(s["vs_benchmark"]) * 100
    assert f"- **Technology sector**, last month ({s['start_date']} to {s['end_date']}): **{s['return'] * 100:+.1f}%**" in text
    assert f"for the S&P 500 over the same dates ({gap:.1f} percentage points {'ahead' if s['vs_benchmark'] >= 0 else 'behind'})" in text
    assert "Measured by the XLK sector fund" in text and "NVIDIA Corp (NVDA, 14.00% of the fund)" in text and "Delisted" not in text
    assert "- **US stock market**, last month" in text and "S&P 500 **" in text and "Sectors, best to worst over the last month: " in text
    assert "$" not in text                                                     # returns, not fund prices
    block = MT.data_block(data)
    assert "XLK sector: **Technology sector**" in block and "MARKET overview: **US stock market**" in block and "{" not in block


def test_tool_specs_list_the_sectors():
    spec = next(s["function"] for s in MT.TOOL_SPECS if s["function"]["name"] == "get_sector_performance")
    assert "XLK (Technology)" in spec["parameters"]["properties"]["sector"]["description"] and spec["parameters"]["required"] == ["sector"]


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
    s = ask(db, "Quote NVDA, AAPL, MSFT, JPM, VOO and QQQ", ToolLLM(calls))
    assert {"NVDA", "AAPL", "MSFT", "JPM"} <= set(s["market_data"])
    assert market_trace(s).count("skipped (limit of 4 tool calls)") == 2


def test_a_tool_call_for_a_company_the_question_is_not_about_is_skipped(db):
    """Turn 3 of a real chat: "hows aapl doing today?" after a gold answer also fetched the stock GOLD."""
    s = ask(db, "How is AAPL doing today?", ToolLLM([("get_quote", {"symbols": ["AAPL"]}), ("get_performance", {"symbols": ["GOLD"], "period": "1 month"})]))
    assert "GOLD" not in s["market_data"] and "get_performance(GOLD) → skipped (not what the question is about)" in market_trace(s)


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


# ---------------------------------------------------------------- the agent at each level
def test_a_sector_question_gets_the_sector_against_the_market_not_its_funds_price(db, sectors):
    llm_module.set_llm(None)
    s = run_chat("how is the tech sector doing?", history=[], profile=PROFILE, holdings=[], db=db)
    trace = market_trace(s)
    assert s["entities"]["levels"] == ["sector"] and "level: sector" in s["trace"]
    assert "get_sector_performance(XLK, last month) → sample" in trace and "get_quote" not in trace
    assert set(s["market_data"]["XLK"]) == {"sector"} and "Technology sector" in s["final_response"]
    assert "S&P 500" in s["final_response"] and "$" not in s["final_response"].split("This is for educational")[0]
    assert s["context"]["levels"] == ["sector"] and s["context"]["period"]["label"] == "last month"
    assert s["context"]["companies"] == [] and s["data_info"]["freshness"] == "sample"


def test_a_quote_the_model_asked_for_gives_way_to_the_sector_figures(db, sectors):
    llm = ToolLLM([("get_quote", {"symbols": ["XLK"]}), ("get_fund_profile", {"symbol": "XLK"})])
    s = ask(db, "what about just the tech sector?", llm)
    assert "Level: sector" in llm.prompt("You fetch market data")
    assert set(s["market_data"]["XLK"]) == {"sector"} and "get_sector_performance(XLK, last month)" in market_trace(s)
    assert "XLK sector: **Technology sector**" in llm.prompt("You are Finnie") and "XLK quote:" not in llm.prompt("You are Finnie")


def test_the_price_of_a_sector_fund_is_still_a_quote(db, sectors):
    llm_module.set_llm(None)
    s = run_chat("price of XLK", history=[], profile=PROFILE, holdings=[], db=db)
    assert "quote" in s["market_data"]["XLK"] and "sector" not in s["market_data"]["XLK"]


def test_the_market_as_a_whole_over_a_period_gets_the_overview(db, sectors):
    llm_module.set_llm(None)
    s = run_chat("how has the stock market performed over the last 3 months?", history=[], profile=PROFILE, holdings=[], db=db)
    trace = market_trace(s)
    assert s["entities"]["levels"] == ["market"] and "get_market_overview(last 3 months) → sample" in trace
    assert "get_quote(^GSPC, ^DJI, ^IXIC) → sample; get_quote(^RUT)" in trace and "get_performance(" not in trace     # the indices' periods: in the overview
    assert "Sectors, best to worst over the last 3 months" in s["agent_outputs"]["market"]["content"]
    assert MT.OVERVIEW_KEY not in [c["symbol"] for c in s["context"]["companies"]]


def test_a_company_against_the_market_today_compares_todays_moves(db, sectors):
    """A real chat: "is the market up or down today?" saved "last month" (the overview's default), and the next turn,
    "nvda vs market trending today?", compared NVDA's day with the indices' month and quoted only two of the four indices."""
    llm_module.set_llm(None)
    context = {"question": "Is the US stock market up or down today?", "companies": [],
               "markets": [{"key": "group:us_indices", "name": "the US stock market"}], "levels": ["market"],
               "period": {"start": "2026-10-05", "label": "last month"}}
    s = run_chat("how is NVDA doing vs the stock market today?", history=[], profile=PROFILE, holdings=[], db=db, context=context)
    trace, data = market_trace(s), s["market_data"]
    assert "get_market_overview" not in trace and "get_performance" not in trace and MT.OVERVIEW_KEY not in data
    assert all("quote" in data[sym] for sym in ("NVDA", "^GSPC", "^IXIC", "^DJI")) and "^RUT" in data   # no sample data for ^RUT


def test_a_first_message_comparing_a_company_with_the_market_today_quotes_the_indices(db, sectors):
    """The same question as a chat's first message: the router named only NVDA, and the model fetched the market overview
    (a month's returns, its default) next to NVDA's quote, so the answer set NVDA's day against the indices' month."""
    s = ask(db, "How did NVIDIA perform compared to the market today?",
            ToolLLM([("get_quote", {"symbols": ["NVDA"]}), ("get_market_overview", {})]))
    trace, data = market_trace(s), s["market_data"]
    assert "market overview (last month) dropped: the question is about today" in trace and MT.OVERVIEW_KEY not in data
    assert all("quote" in data[sym] for sym in ("NVDA", "^GSPC", "^IXIC", "^DJI"))
    assert s["context"]["period"] is None and s["context"]["markets"][0]["key"] == "group:us_indices"


class PortfolioRouterLLM(ToolLLM):
    """A router that also picks portfolio, as the LLM did for a market question asked right after "summary of my portfolio?"."""
    def invoke(self, messages):
        system = messages[0][1] if isinstance(messages[0], tuple) else messages[0].content
        if "You are the router" in system:
            self.prompts.append((system, ""))
            return AIMessage(content='{"intents": ["portfolio", "market"], "confidence": 0.9}')
        return super().invoke(messages)


@pytest.mark.parametrize("q,kept", [("how about nvda vs market trending today?", False),
                                    ("how is my portfolio doing against the market today?", True),
                                    ("is NVDA a big position for me compared with the market?", True)])
def test_a_market_question_keeps_the_portfolio_agent_only_when_it_is_about_my_holdings(db, sectors, q, kept):
    s = ask(db, q, PortfolioRouterLLM([("get_quote", {"symbols": ["NVDA"]})]))
    assert ("portfolio" in s["intent"]) is kept and "market" in s["intent"]


def test_a_company_against_the_market_over_a_period_still_gets_the_overview(db, sectors):
    llm_module.set_llm(None)
    s = run_chat("how has NVDA done vs the market over the last month?", history=[], profile=PROFILE, holdings=[], db=db)
    assert s["market_data"]["NVDA"]["period"]["label"] == "last month"
    assert s["market_data"][MT.OVERVIEW_KEY]["overview"]["label"] == "last month"


def test_the_model_can_call_the_sector_and_overview_tools(db, sectors):
    llm = ToolLLM([("get_sector_performance", {"sector": "XLE", "period": "ytd"}), ("get_market_overview", {"period": "ytd"})])
    s = ask(db, "How are energy stocks doing this year compared with the rest of the market?", llm)
    assert s["market_data"]["XLE"]["sector"]["label"] == "year to date"
    assert s["market_data"][MT.OVERVIEW_KEY]["overview"]["label"] == "year to date"
    assert market_trace(s).startswith("market (LLM tools): get_sector_performance(XLE, ytd) → sample; get_market_overview(ytd) → sample")


def test_a_repeated_tool_call_runs_once_and_does_not_use_up_the_limit(db, sectors):
    calls = [("get_market_overview", {}), ("get_market_overview", {}), ("get_market_overview", {}), ("get_quote", {"symbols": ["NVDA"]}),
             ("get_quote", {"symbols": ["AAPL"]}), ("get_quote", {"symbols": ["MSFT"]})]
    s = ask(db, "How is the stock market doing?", ToolLLM(calls))
    trace = market_trace(s)
    assert trace.count("get_market_overview()") == 1 and "skipped" not in trace and {"NVDA", "AAPL", "MSFT"} <= set(s["market_data"])


def test_the_market_cache_lock_is_per_session_so_parallel_fetches_cannot_deadlock_on_the_pool():
    # one global lock hung the Live Market tab: its holder waited for a pooled connection held by sessions queued behind it
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from src.core import market_service as MS
    file_db = create_engine("sqlite:///unused.db")                # never connected
    a, b = Session(file_db), Session(file_db)
    assert MS._cache_lock(a) is MS._cache_lock(a)          # agents sharing a request's session still take turns
    assert MS._cache_lock(a) is not MS._cache_lock(b)
    memory = create_engine("sqlite://", poolclass=StaticPool)     # one shared connection: one lock
    assert MS._cache_lock(Session(memory)) is MS._cache_lock(Session(memory))
