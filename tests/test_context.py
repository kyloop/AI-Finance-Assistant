"""Conversation context: each answer saves what it used (question, companies, period, figures) and a follow-up starts from it."""
import pytest
from sqlalchemy.orm import sessionmaker

from src.core import llm as llm_module
from src.workflow import context as CTX
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


def turns(db, *questions):
    """Run questions as one conversation, passing each answer's context to the next; returns the final states."""
    states, history, context = [], [], None
    for q in questions:
        s = run_chat(q, history=history, profile=PROFILE, holdings=[], db=db, context=context)
        states.append(s)
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": s["final_response"]}]
        context = s["context"]
    return states


def symbols(ctx):
    return [c["symbol"] for c in ctx["companies"]]


def test_an_answer_saves_its_companies_period_and_figures(db):
    (s,) = turns(db, "How has NVDA done over the last month?")
    ctx = s["context"]
    assert ctx["question"] == "How has NVDA done over the last month?" and "market" in ctx["intents"]
    assert symbols(ctx) == ["NVDA"] and ctx["period"]["label"] == "last month"
    f = ctx["facts"]["NVDA"]
    assert f["price"] > 0 and f["period"] == "last month" and {"return", "start_price", "end_price"} <= set(f)


def test_a_follow_up_keeps_the_period_for_a_new_company(db):
    _, s = turns(db, "How has NVDA done over the last month?", "what about AAPL?")
    assert s["follow_up"] and "Apple" in s["final_response"] and "last month" in s["final_response"]
    assert symbols(s["context"]) == ["AAPL"] and s["context"]["period"]["label"] == "last month"


def test_a_comparison_adds_the_new_company_to_the_earlier_one(db):
    _, s = turns(db, "How has NVDA done over the last month?", "compare to MSFT")
    assert "from the previous answer: NVDA" in s["trace"]
    assert set(symbols(s["context"])) == {"NVDA", "MSFT"} and s["final_response"].count("total return") == 2


def test_which_did_better_uses_both_companies_and_the_period(db):
    *_, s = turns(db, "How has NVDA done over the last month?", "compare to MSFT", "which did better?")
    assert s["agents"] == ["Market Analysis"] and set(symbols(s["context"])) == {"NVDA", "MSFT"}
    assert s["final_response"].count("total return") == 2 and "last month" in s["final_response"]


def test_a_new_topic_drops_the_earlier_companies_and_period(db):
    _, s = turns(db, "How has NVDA done over the last month?", "What is an ETF?")
    assert not s["follow_up"] and s["context"]["companies"] == [] and s["context"]["period"] is None


def test_a_calculation_keeps_the_conversation_subject_for_the_next_turn(db):
    *_, s = turns(db, "How has NVDA done over the last month?", "How much will $10,000 grow to at 6% a year over 10 years?")
    assert s["agents"] == ["Calculator"] and symbols(s["context"]) == ["NVDA"] and s["context"]["period"]["label"] == "last month"


def test_a_plain_price_question_does_not_carry_the_period(db):
    _, s = turns(db, "How has NVDA done over the last month?", "what is the price of it?")
    assert "NVIDIA" in s["final_response"] and "total return" not in s["final_response"]


def test_news_saves_its_companies_for_the_next_turn(db):
    (s,) = turns(db, "latest news on NVDA")
    assert "News" in s["agents"] and symbols(s["context"]) == ["NVDA"]


def test_news_on_them_uses_the_companies_of_the_previous_answer(db):
    _, s = turns(db, "How has NVDA done over the last month?", "any news on them?")
    assert "News" in s["agents"] and "from the previous answer: NVDA" in s["trace"]
    assert any(t.startswith("news") and "NVDA" in t for t in s["trace"]) and symbols(s["context"]) == ["NVDA"]


def test_news_on_another_company_too_keeps_the_earlier_one(db):
    _, s = turns(db, "latest news on NVDA", "news on MSFT too?")
    assert "from the previous answer: NVDA" in s["trace"] and set(symbols(s["context"])) == {"NVDA", "MSFT"}


def test_the_news_agent_reads_the_proofread_question(db):
    llm_module.set_llm(ContextLLM('{"question": "What is the latest news on NVDA?", "follow_up": false}', router='{"intents": ["news"], "confidence": 0.9}'))
    s = run_chat("wats teh latst nws on nvda", history=[], profile=PROFILE, holdings=[], db=db)
    assert s["question"] == "What is the latest news on NVDA?"
    assert any(t.startswith("news") and "NVDA" in t for t in s["trace"])          # NVDA found in the corrected text


class ContextLLM:
    """Proofreads with a scripted JSON reply, routes to market, and records what each prompt was given."""
    model = "context"

    def __init__(self, proofread, router='{"intents": ["market"], "confidence": 0.9}'):
        self.proofread, self.router, self.prompts = proofread, router, {}

    def invoke(self, messages):
        system, user = messages[0][1], messages[1][1]
        role = "proofread" if "You are the proofreader" in system else "router" if "You are the router" in system else "other"
        self.prompts.setdefault(role, user)
        reply = {"proofread": self.proofread, "router": self.router}.get(role, "Answer.")
        return type("R", (), {"content": reply})()


CONTEXT = {"question": "How has TSLA done over the last month?", "intents": ["market"],
           "companies": [{"symbol": "NVDA", "name": "NVIDIA Corporation"}], "period": {"start": "2026-09-02", "label": "last month"},
           "facts": {"NVDA": {"price": 180.5, "as_of": "2026-10-02"}}}


def test_proofread_completes_a_follow_up_from_the_context(db):
    llm = ContextLLM('{"question": "Compare NVDA and MSFT over the last month.", "follow_up": true}')
    llm_module.set_llm(llm)
    s = run_chat("compare to msft", history=[], profile=PROFILE, holdings=[], db=db, context=CONTEXT)
    assert "Companies: NVIDIA Corporation (NVDA)" in llm.prompts["proofread"] and "Period: last month" in llm.prompts["proofread"]
    assert s["question"] == "Compare NVDA and MSFT over the last month." and s["follow_up"]
    assert "(follow-up of the previous question)" in next(t for t in s["trace"] if t.startswith("proofread"))


def test_proofread_rejects_a_follow_up_that_invents_a_company(db):
    llm_module.set_llm(ContextLLM('{"question": "Compare NVDA, MSFT and AAPL over the last month.", "follow_up": true}'))
    s = run_chat("compare to MSFT", history=[], profile=PROFILE, holdings=[], db=db, context=CONTEXT)
    assert s["question"] == "compare to MSFT" and "rewrite rejected" in next(t for t in s["trace"] if t.startswith("proofread"))


def test_describe_lists_the_figures_for_prompts():
    text = CTX.describe({**CONTEXT, "facts": {"SBUX": {"price": 94.71, "as_of": "2026-10-02", "period": "last month", "return": -0.105,
                                                       "start_price": 105.82, "end_price": 94.71}}})
    assert "SBUX: price $94.71 on 2026-10-02; last month return -10.5% ($105.82 → $94.71)" in text


def test_the_chat_api_saves_the_context_and_starts_the_next_turn_from_it(client, sid):
    client.post(f"/api/sessions/{sid}/chat", json={"message": "How has NVDA done over the last month?"})
    r = client.post(f"/api/sessions/{sid}/chat", json={"message": "compare to MSFT"}).json()
    assert "from the previous answer: NVDA" in r["trace"] and r["content"].count("total return") == 2


CALC_HISTORY = [{"role": "user", "content": "How much does $10,000 grow at 8% a year for 5 years?"},
                {"role": "assistant", "content": "**Result: future value = $14,693.28**"},
                {"role": "user", "content": "What if I invest in buying a vehicle, how much return should I get after 5 years?"},
                {"role": "assistant", "content": "A vehicle usually loses value."}]
VEHICLE = {"question": CALC_HISTORY[2]["content"], "intents": ["qa"], "companies": [], "period": None, "facts": {}}


def test_proofread_completes_a_follow_up_of_an_earlier_turn_from_the_recent_conversation(db):
    # the trace that prompted this: the figures were two turns back, behind a question without any
    llm = ContextLLM('{"question": "How much does $20,000 grow at 8% a year for 5 years?", "follow_up": true}')
    llm_module.set_llm(llm)
    s = run_chat("what if the presdnent value is $20000?", history=CALC_HISTORY, profile=PROFILE, holdings=[], db=db,
                 context=VEHICLE)
    assert "RECENT CONVERSATION:" in llm.prompts["proofread"] and "8% a year" in llm.prompts["proofread"]
    assert s["question"] == "How much does $20,000 grow at 8% a year for 5 years?" and s["follow_up"]


def test_proofread_reads_20000_and_20_000_as_the_same_number(db):
    llm_module.set_llm(ContextLLM('{"question": "What if the present value is $20,000?", "follow_up": false}'))
    s = run_chat("what if the presdnent value is $20000?", history=[], profile=PROFILE, holdings=[], db=db)
    assert s["question"] == "What if the present value is $20,000?"


def test_proofread_still_rejects_a_number_that_isnt_in_the_conversation(db):
    llm_module.set_llm(ContextLLM('{"question": "How much does $20,000 grow at 9% a year for 5 years?", "follow_up": true}'))
    s = run_chat("what if it's $20000?", history=CALC_HISTORY, profile=PROFILE, holdings=[], db=db, context=VEHICLE)
    assert s["question"] == "what if it's $20000?" and s["follow_up"]          # kept as typed; "what if" still marks it


# ---- the tab on screen: "this" after a tab switch means what the user is now looking at, not the earlier answer
HOLDINGS = [{"ticker": "AAPL", "shares": 10, "cost_basis": 150.0, "purchase_date": None},
            {"ticker": "MSFT", "shares": 5, "cost_basis": 300.0, "purchase_date": None}]
SAVED_GOAL = {"goal_type": "retirement", "target_amount": 1_000_000, "horizon_years": 30, "current_savings": 10_000,
              "monthly_contribution": 500, "risk_tolerance": "moderate"}
PORTFOLIO_VIEW, GOALS_VIEW = {"tab": "Portfolio", "selected": None, "watchlist": []}, {"tab": "Goals", "selected": None, "watchlist": []}


def on_tabs(db, *turns_):
    """Run (question, view) turns as one conversation with holdings and a saved goal; returns the final states."""
    states, history, context = [], [], None
    for q, view in turns_:
        s = run_chat(q, history=history, profile=PROFILE, holdings=HOLDINGS, saved_goal=SAVED_GOAL, db=db, view=view, context=context)
        states.append(s)
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": s["final_response"]}]
        context = s["context"]
    return states


@pytest.mark.parametrize("q", ["What about this?", "explain this", "How is this stock doing?", "what does this mean?",
                               "How am I doing?", "Is this good?", "what's shown here?"])
def test_messages_that_point_at_the_screen(q):
    assert CTX.POINTS_AT_SCREEN.search(q)


@pytest.mark.parametrize("q", ["What is an ETF?", "What about it?", "How is that different from a bond?", "Is this year a good time to save?",
                               "compare them"])
def test_messages_that_dont_point_at_the_screen(q):
    assert not CTX.POINTS_AT_SCREEN.search(q)


def test_an_answer_saves_the_tab_it_was_asked_on(db):
    (s,) = on_tabs(db, ("How diversified is my portfolio?", PORTFOLIO_VIEW))
    assert s["context"]["tab"] == "Portfolio"


def test_this_after_switching_tabs_means_the_new_tab(db):
    first, second = on_tabs(db, ("How diversified is my portfolio?", PORTFOLIO_VIEW), ("What about this?", GOALS_VIEW))
    assert first["intent"] == ["portfolio"]
    assert second["intent"] == ["goal"] and not second["follow_up"] and second["screen"]["switched"] == "Portfolio"
    assert "$1,000,000" in second["final_response"]
    assert "since you switched from the Portfolio tab" in second["final_response"]


def test_a_follow_up_on_the_same_tab_keeps_the_conversation(db):
    _, second = on_tabs(db, ("How diversified is my portfolio?", PORTFOLIO_VIEW), ("What about this?", PORTFOLIO_VIEW))
    assert second["screen"] is None and second["follow_up"]
    assert "since you switched" not in second["final_response"]


def test_a_named_subject_wins_over_the_tab(db):
    _, second = on_tabs(db, ("Am I on track for retirement?", GOALS_VIEW), ("How diversified is my portfolio?", PORTFOLIO_VIEW))
    assert second["screen"] is None and second["intent"] == ["portfolio"]


def test_a_tab_with_nothing_to_read_leaves_the_conversation_in_charge(db):
    s = run_chat("What about this?", history=[], profile=PROFILE, holdings=[], db=db, view=PORTFOLIO_VIEW,
                 context={"question": "Am I on track?", "intents": ["goal"], "companies": [], "tab": "Goals", "facts": {}})
    assert s["screen"] is None                                     # no holdings: "this" can't be the Portfolio tab


def test_this_on_a_research_tab_is_the_symbol_shown(db):
    view = {"tab": "Research", "selected": "AAPL", "watchlist": []}
    s = run_chat("explain this", history=[], profile=PROFILE, holdings=[], db=db, view=view)
    assert s["intent"] == ["market"] and "AAPL" in s["entities"]["tickers"] and "AAPL" in s["final_response"]


def test_this_compared_with_another_ticker_keeps_the_symbol_shown(db):
    view = {"tab": "Market", "selected": "AAPL", "watchlist": []}
    s = run_chat("How does this stock compare to MSFT?", history=[], profile=PROFILE, holdings=[], db=db, view=view)
    assert s["entities"]["tickers"][:2] == ["AAPL", "MSFT"]


def test_after_a_tab_switch_the_llm_sees_the_screen_not_the_conversation(db):
    llm = ContextLLM('{"question": "What about this?", "follow_up": false}', router='{"intents": ["qa"], "confidence": 0.9}')
    llm_module.set_llm(llm)
    history = [{"role": "user", "content": "How diversified is my portfolio?"}, {"role": "assistant", "content": "Fairly."}]
    s = run_chat("What about this?", history=history, profile=PROFILE, holdings=HOLDINGS, saved_goal=SAVED_GOAL, db=db, view=GOALS_VIEW,
                 context={"question": "How diversified is my portfolio?", "intents": ["portfolio"], "companies": [], "tab": "Portfolio", "facts": {}})
    assert "CONTEXT" not in llm.prompts["proofread"] and "RECENT CONVERSATION" not in llm.prompts["proofread"]
    assert "On screen: your saved plan on the Goals tab" in llm.prompts["router"] and "diversified" not in llm.prompts["router"]
    assert s["intent"] == ["goal"]                                 # the router's bare "qa" is replaced by the tab's agent
