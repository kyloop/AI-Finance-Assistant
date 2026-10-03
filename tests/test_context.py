"""Conversation context: each answer saves what it used (question, companies, period, figures) and a follow-up starts from it."""
import pytest
from sqlalchemy.orm import sessionmaker

from src.core import llm as llm_module
from src.workflow import context as CTX
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
