import pytest
from sqlalchemy import create_engine, text

from src.core import llm as llm_module
from src.core.config import DISCLAIMER
from src.db.session import init_db
from src.workflow import router as R
from src.workflow.graph import get_graph, run_chat
from src.workflow.safety import REFUSAL_NOTE, filter_advice
from src.workflow.tools import set_wiki_client, wiki_search
from tests.conftest import FakeWiki

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate"}
HOLDINGS = [{"ticker": "NVDA", "shares": 100, "cost_basis": 45.0}, {"ticker": "BND", "shares": 10, "cost_basis": None}]


def ask(q, *, history=None, holdings=None, profile=PROFILE, db=None):
    return run_chat(q, history=history or [], profile=profile, holdings=holdings or [], db=db)


@pytest.fixture
def db():
    from sqlalchemy.orm import sessionmaker

    from src.db.base import Base
    from src.db.session import make_engine
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


# ------------------------------------------------------------------ router + entities
def test_keyword_router_and_entities():
    assert R.classify("What is an ETF?") == ["qa"]
    assert set(R.classify("Is my portfolio too tech-heavy given the S&P 500 today?")) == {"portfolio", "market"}
    assert R.classify("How does a Roth IRA work?") == ["tax"]
    e = R.extract_entities("How is NVDA and Apple doing versus the Nasdaq?")
    assert e["tickers"] == ["NVDA", "AAPL"] and e["indices"] == ["^IXIC"]
    g = R.extract_entities("I want $1.5 million in 30 years, saving $2,000 a month")
    assert (g["target_amount"], g["monthly_amount"], g["years"]) == (1_500_000, 2000, 30)
    assert R.clean_topic("What is an ETF?") == "ETF" and R.clean_topic("How does a Roth IRA work?") == "Roth IRA"


def test_regressions_from_live_run():
    assert R.classify("How is that different from a mutual fund?") == ["qa"]           # "that" is not a ticker
    assert "goal" in R.classify("I want $1,000,000 in 30 years, saving $500 a month")
    assert "market" in R.classify("Tell me about NVDA") and "market" in R.classify("How is AAPL doing?")
    assert R.classify("What is a stock?") == ["qa"]


def test_advice_requests_get_a_no_advice_note_before_the_facts(db):
    s = ask("Should I sell my NVDA?", db=db)
    assert s["final_response"].startswith("I can't tell you whether to buy or sell") and "NVIDIA" in s["final_response"]
    assert any("advice request" in t for t in s["trace"])
    assert not ask("What is NVDA at?", db=db)["final_response"].startswith("I can't tell you")
    assert R.extract_entities("How is that different from a mutual fund?", [{"role": "user", "content": "What is an ETF?"}])["wiki_query"] == "ETF different from a mutual fund"


def test_off_topic_wikipedia_hits_are_rejected():
    class Off(FakeWiki):
        def get_page(self, title):
            page = super().get_page(title)
            page.text = "Whitney Houston is the debut studio album by American singer Whitney Houston, released in 1985 by Arista. " * 3
            return page
    set_wiki_client(Off({"whitney": ["Whitney Houston (album)"]}))
    assert wiki_search("whitney houston album") is None
    assert "rather not guess" in ask("What is whitney houston?")["final_response"]


def test_follow_up_uses_previous_topic():
    hist = [{"role": "user", "content": "What is an ETF?"}, {"role": "assistant", "content": "..."}]
    assert R.extract_entities("How is that different from a mutual fund?", hist)["wiki_query"].startswith("ETF")
    assert R.extract_entities("What is a bond?", hist)["wiki_query"] == "bond"          # no pronoun: no carry-over


def test_parse_llm_intents():
    assert R.parse_llm_intents('Sure: {"intents": ["market", "news", "bogus"], "confidence": 0.8}') == (["market", "news"], 0.8)
    assert R.parse_llm_intents("no json") is None and R.parse_llm_intents('{"intents": ["bogus"]}') is None


# ------------------------------------------------------------------ agents through the graph
def test_qa_answer_cites_wikipedia_and_appends_disclaimer():
    s = ask("What is an ETF?")
    assert s["agents"] == ["Finance Q&A"] and s["final_response"].endswith(DISCLAIMER)
    assert s["sources"][0]["url"].startswith("https://en.wikipedia.org/wiki/")
    assert "History" not in s["final_response"]                                        # lead only
    assert any("wiki_search('ETF')" in t for t in s["trace"])


def test_unknown_topic_admits_low_confidence_instead_of_guessing():
    s = ask("What is a flibbertigibbet fund?")
    assert "rather not guess" in s["final_response"] and s["sources"] == []


def test_market_agent_quotes_tickers_and_indices(db):
    s = ask("What is NVDA at, and how is the S&P 500 doing?", db=db)
    assert "NVIDIA" in s["final_response"] and "S&P 500" in s["final_response"]
    assert s["data_info"]["freshness"] == "sample" and s["agents"] == ["Market Analysis"]


def test_market_agent_reports_return_over_the_asked_period(db):
    s = ask("How has NVDA done over the last year?", db=db)
    assert "last year" in s["final_response"] and "total return" in s["final_response"]
    assert any("get_performance(NVDA, last year)" in t for t in s["trace"])
    assert "total return" not in ask("What is NVDA at?", db=db)["final_response"]       # no period asked: quote only


@pytest.mark.parametrize("q,label", [
    ("last 10 yrs", "last 10 years"), ("last 10y", "last 10 years"), ("past 5 yaers", "last 5 years"), ("for the past 5 yrs", "last 5 years"),
    ("last 6 mo", "last 6 months"), ("past 3 mos", "last 3 months"), ("last 2 mon", "last 2 months"), ("last 6 mths", "last 6 months"),
    ("last 6 monts", "last 6 months"), ("last 6m", "last 6 months"), ("last 2 wks", "last 2 weeks"), ("last 30 days", "last 30 days"),
    ("last 2 decades", "last 20 years"), ("what about last month", "last month"),
    ("what happened last mon", None), ("news over the weekend", None), ("price of TSLA in the market", None)])
def test_market_period_units_accept_abbreviations_and_typos(q, label):
    from src.workflow.market_tools import asked_period as _asked_period
    assert (_asked_period(q) or (None, None))[1] == label


def test_market_period_tolerates_typos_and_carries_over_to_follow_ups():
    from src.workflow.nodes import _period_for
    st = lambda q, hist=(): {"question": q, "history": list(hist)}                       # noqa: E731
    assert _period_for(st("I thought you have last 10 yers tsla performance"))[1] == "last 10 years"
    assert _period_for(st("ORCL and TSLA over the past decade"))[1] == "last 10 years"
    hist = [{"role": "user", "content": "what about last 10yr for oracle and tsla?"}, {"role": "assistant", "content": "..."}]
    assert _period_for(st("which stock has better performance?", hist))[1] == "last 10 years"
    assert _period_for(st("what is the price of TSLA?", hist)) is None                 # a plain quote stays a quote
    typo = [{"role": "user", "content": "what is the lat month tsla doing?"},          # history keeps the typo...
            {"role": "assistant", "content": "Over the last month, Tesla had a total return of -1.5%."}]   # ...the answer doesn't
    assert _period_for(st("what about compare to starbucks", typo))[1] == "last month"


def test_market_concept_without_ticker_falls_back_to_knowledge_lookup(db):
    assert "Exchange-traded fund" in ask("Explain the market trend for an ETF", db=db)["final_response"]


def test_portfolio_agent_with_and_without_holdings():
    assert "Portfolio** tab" in ask("Is my portfolio diversified?")["final_response"]
    r = ask("Is my portfolio diversified?", holdings=HOLDINGS)["final_response"]
    assert "Diversification score" in r and "NVDA is" in r and "Concentration risk" in r


def test_goal_agent_projects_or_asks_for_details():
    r = ask("I want to retire with $1,000,000 in 30 years, saving $500 a month")["final_response"]
    assert "$1,000,000" in r and "a month" in r
    assert "target amount" in ask("How should I plan for retirement?")["final_response"]


def test_tax_agent_adds_scope_caveat():
    s = ask("How does a Roth IRA work?")
    assert s["agents"] == ["Tax Education"] and "not what you personally should do" in s["final_response"]


def test_multi_intent_fans_out_and_merges_in_one_answer(db):
    s = ask("Is my portfolio too tech-heavy given the S&P 500 today?", holdings=HOLDINGS, db=db)
    assert s["agents"] == ["Portfolio Analysis", "Market Analysis"]
    assert "Diversification score" in s["final_response"] and "S&P 500" in s["final_response"]
    assert s["final_response"].count(DISCLAIMER) == 1


def test_gibberish_gets_clarify_prompt():
    s = ask("?!? 123")
    assert s["agents"] == ["Finnie"] and "didn't quite catch" in s["final_response"]


# ------------------------------------------------------------------ failure handling
def test_wiki_outage_is_reported_not_raised():
    set_wiki_client(FakeWiki(fail=True))
    s = ask("What is an ETF?")
    assert "couldn't reach my knowledge source" in s["final_response"] and s["errors"]
    assert s["final_response"].endswith(DISCLAIMER)


def test_agent_crash_is_contained_and_other_agents_still_answer(db, monkeypatch):
    import src.workflow.nodes as nodes
    monkeypatch.setattr(nodes, "analyze_portfolio", lambda *a, **k: 1 / 0)
    s = get_graph().invoke({"question": "Is my portfolio ok given the S&P 500 today?", "history": [], "profile": PROFILE,
                            "holdings": HOLDINGS, "agent_outputs": {}, "errors": [], "trace": []}, config={"configurable": {"db": db}})
    assert "S&P 500" in s["final_response"] and s["errors"] == ["portfolio: ZeroDivisionError"]
    assert "incomplete" in s["final_response"]
    assert s["agents"] == ["Market Analysis"]


def test_everything_failing_gives_friendly_fallback(monkeypatch):
    import src.workflow.nodes as nodes
    monkeypatch.setattr(nodes, "wiki_search", lambda *a, **k: 1 / 0)
    assert "trouble answering" in ask("What is an ETF?")["final_response"]


# ------------------------------------------------------------------ safety
def test_advice_sentences_removed_and_refusal_added():
    text = "An ETF holds many assets. You should sell your NVDA today. Stocks can fall. This will definitely make 10% a year."
    out, n = filter_advice(text)
    assert n == 2 and "sell your NVDA" not in out and "10%" not in out
    assert "An ETF holds many assets." in out and out.endswith(REFUSAL_NOTE)
    assert filter_advice("Diversification spreads risk.") == ("Diversification spreads risk.", 0)


# ------------------------------------------------------------------ LLM path
class FakeLLM:
    model = "fake-1"

    def __init__(self, intents='{"intents": ["market"], "confidence": 0.9}', answer="LLM answer grounded in context.", fail=False,
                 proofread=None):
        self.intents, self.answer, self.fail, self.calls, self.proofread = intents, answer, fail, [], proofread

    def invoke(self, messages):
        if self.fail:
            raise RuntimeError("api down")
        system = messages[0][1]
        if "You are the proofreader" in system:                  # unchanged unless a correction is given
            self.calls.append("proofread")
            return type("R", (), {"content": self.proofread or messages[1][1].removeprefix("Message: ")})()
        self.calls.append("router" if "You are the router" in system else "synth")
        return type("R", (), {"content": self.intents if "You are the router" in system else self.answer})()


def test_llm_routes_and_writes_final_answer(db):
    fake = FakeLLM()
    llm_module.set_llm(fake)
    s = ask("tell me about nvidia", db=db)
    assert s["router_mode"] == "llm" and s["agents"] == ["Market Analysis"] and fake.calls == ["proofread", "router", "synth", "synth"]  # answer + follow-ups
    assert s["final_response"].startswith("LLM answer grounded") and s["final_response"].endswith(DISCLAIMER)
    assert llm_module.llm_status() == {"enabled": True, "provider": "FakeLLM", "model": "fake-1", "last_error": None}


def test_proofread_corrects_the_message_before_routing(db):
    llm_module.set_llm(FakeLLM(proofread="How has TSLA done over the last 10 years?"))
    s = ask("how has tsla doen ovr lst 10 yrs", db=db)
    assert s["original_question"] == "how has tsla doen ovr lst 10 yrs" and s["question"] == "How has TSLA done over the last 10 years?"
    assert "proofread: “how has tsla doen ovr lst 10 yrs” → “How has TSLA done over the last 10 years?”" in s["trace"]


@pytest.mark.parametrize("fixed", ["Tesla is a car maker founded in 2003 that went public in 2010 and has grown a lot since then, "
                                   "making it one of the best performing large companies of the decade.",   # an answer, not a correction
                                   "How has Tesla done over the last years?",                             # lost the number and ticker
                                   ""])
def test_proofread_keeps_the_message_when_the_rewrite_is_not_a_correction(fixed):
    llm_module.set_llm(FakeLLM(proofread=fixed or " "))
    s = ask("How has TSLA done over the last 10 yrs?")
    assert s["question"] == s["original_question"] == "How has TSLA done over the last 10 yrs?"
    assert any(t.startswith("proofread: ") and "→" not in t for t in s["trace"])


def test_proofread_passes_through_without_an_llm():
    s = ask("What is an ETF?")
    assert s["question"] == s["original_question"] and "proofread: skipped (no LLM)" in s["trace"]


def test_llm_low_confidence_clarifies_and_bad_json_falls_back_to_keywords():
    llm_module.set_llm(FakeLLM(intents='{"intents": ["qa"], "confidence": 0.1}'))
    assert ask("hmm")["agents"] == ["Finnie"]
    llm_module.set_llm(FakeLLM(intents="I think it is a market question"))
    s = ask("What is an ETF?")
    assert s["router_mode"] == "keywords" and s["agents"] == ["Finance Q&A"]


def test_llm_failure_degrades_to_extractive_answer():
    llm_module.set_llm(FakeLLM(fail=True))
    s = ask("What is an ETF?")
    assert any("extractive" in t for t in s["trace"]) and "Exchange-traded fund" in s["final_response"]


def test_llm_status_reports_a_failing_provider_in_plain_language():
    class Broke(FakeLLM):
        def invoke(self, messages):
            raise RuntimeError("Error code: 429 - insufficient_quota credit_balance_exhausted")
    llm_module.set_llm(Broke())
    ask("What is an ETF?")
    assert "no credits" in llm_module.llm_status()["last_error"]
    llm_module.set_llm(FakeLLM())
    ask("What is an ETF?")
    assert llm_module.llm_status()["last_error"] is None


def test_advice_from_llm_is_filtered():
    llm_module.set_llm(FakeLLM(intents='{"intents": ["qa"], "confidence": 1}', answer="ETFs are funds. You should buy VTI now."))
    r = ask("What is an ETF?")["final_response"]
    assert "buy VTI" not in r and REFUSAL_NOTE in r


# ------------------------------------------------------------------ tools + api + db
def test_wiki_search_caches_and_rejects_irrelevant_hits():
    wiki = FakeWiki()
    set_wiki_client(wiki)
    assert wiki_search("etf")["confidence"] == "high"
    wiki_search("etf")
    assert wiki.queries == ["etf"]                                                     # second call served from cache
    wiki.results["zzz"] = ["Exchange-traded fund"]
    assert wiki_search("zzz qqqq") is None                                             # title/lead share no words with query


def test_chat_api_returns_sources_trace_and_status(client, sid):
    r = client.post(f"/api/sessions/{sid}/chat", json={"message": "What is an ETF?"}).json()
    assert r["sources"][0]["title"].startswith("Exchange-traded fund") and r["trace"][0].startswith("proofread") and r["trace"][1].startswith("router")
    assert client.get(f"/api/sessions/{sid}/messages").json()[-1]["trace"] == r["trace"]
    assert client.get("/api/chat/status").json()["llm"]["enabled"] is False


def test_chat_api_uses_saved_portfolio_and_profile(client, sid):
    client.put(f"/api/sessions/{sid}/portfolio", json={"holdings": [{"ticker": "NVDA", "shares": 100}]})
    r = client.post(f"/api/sessions/{sid}/chat", json={"message": "How diversified is my portfolio?"}).json()
    assert "NVDA is 100%" in r["content"]


def test_init_db_adds_new_columns_to_an_old_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id VARCHAR(32), role VARCHAR(16), content TEXT, "
                       "agents JSON, sources JSON, data_info JSON, created_at DATETIME)"))
    init_db(engine)
    with engine.begin() as c:
        assert "trace" in [r[1] for r in c.execute(text("PRAGMA table_info(messages)"))]


def test_goal_agent_uses_saved_goal_when_none_stated():
    saved = {"goal_type": "retirement", "target_amount": 1_000_000, "horizon_years": 30, "current_savings": 10_000,
             "monthly_contribution": 500, "risk_tolerance": "moderate"}
    from src.workflow.graph import run_chat
    out = run_chat("Am I on track for retirement?", history=[], profile={"risk_tolerance": "moderate"}, holdings=[], db=None, saved_goal=saved)
    assert "Goals** tab" in out["final_response"] and "$1,000,000" in out["final_response"]


def test_market_agent_resolves_watchlist_and_selected_symbol(client, sid):
    view = {"tab": "Live", "selected": "NVDA", "watchlist": ["AAPL", "MSFT"]}
    r = client.post(f"/api/sessions/{sid}/chat", json={"message": "How is my watchlist doing?", "view": view}).json()
    assert "AAPL" in r["content"] and "MSFT" in r["content"]
    r = client.post(f"/api/sessions/{sid}/chat", json={"message": "What is the price of this?", "view": view}).json()
    assert "NVDA" in r["content"]


def test_portfolio_agent_reports_gain_loss_and_benchmark(db):
    r = ask("How is my portfolio doing?", holdings=HOLDINGS, db=db)["final_response"]
    assert "Gain/loss against what you paid" in r and "Today:" in r
    assert "for the S&P 500" in r and "bought in full on its purchase date (2026-01-01 where none is set)" in r


def test_prompts_see_the_last_four_messages_up_to_1000_characters_each():
    from src.workflow import history as H
    hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i} " + "x" * 1500} for i in range(6)]
    lines = H.transcript(hist).splitlines()
    assert [ln.split()[1] for ln in lines] == ["m2", "m3", "m4", "m5"]
    assert all(len(ln.split(": ", 1)[1]) == 1000 for ln in lines)
