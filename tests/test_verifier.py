"""Verifier + research: agents report answered / not_found / need_info, and nothing that isn't an answer gets rewritten
into one (regression for "I want to buy a house" producing an unsourced, partly invented reply)."""
from src.core import llm as llm_module
from src.core.config import DISCLAIMER, get_config
from src.workflow import nodes as N
from src.workflow.graph import run_chat
from src.workflow.tools import set_kb_searcher, set_wiki_client
from tests.conftest import FakeWiki

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate"}
MIN = get_config()["rag"]["min_score"]
HOUSE = "I would like purchase a house. what woul;dbe mindful for me?"


class ScriptedLLM:
    """Replies by role, recognised from the system prompt; records the roles it was asked to play."""
    model = "scripted"

    def __init__(self, **replies):
        self.replies = {"router": '{"intents": ["qa"], "confidence": 0.9}', "check": '{"answers": true}',
                        "choices": '{"choices": ["What should I know before buying a house?", "Plan savings for a $60,000 down payment in 5 years"]}',
                        "topics": '{"topics": ["Mortgage loan", "Down payment"]}', "replan": '{"intents": [], "reason": "none can help"}',
                        "synth": "Answer written from the context.", **replies}
        self.calls: list[str] = []

    def invoke(self, messages):
        system = messages[0][1]
        if "You are the proofreader" in system:                  # the proofread node: message unchanged, not counted as a call
            return type("R", (), {"content": messages[1][1].removeprefix("Message: ")})()
        role = ("router" if "You are the router" in system else "check" if "retrieved SOURCES" in system else
                "choices" if "messages the USER" in system else "topics" if "Wikipedia articles" in system else
                "replan" if "coordinate the specialist agents" in system else "synth")
        self.calls.append(role)
        reply = self.replies[role]
        if isinstance(reply, list):                    # a list scripts successive calls; the last reply repeats
            reply = reply.pop(0) if len(reply) > 1 else reply[0]
        return type("R", (), {"content": reply})()


def ask(q, **kw):
    return run_chat(q, history=[], profile=PROFILE, holdings=[], db=None, **kw)


def kb_hit(score, text="Mortgage-free facts about compound interest."):
    return {"score": score, "doc_id": "compound-interest", "doc_title": "Compound interest", "section": "(lead)", "text": text,
            "source_url": "https://en.wikipedia.org/wiki/Compound_interest", "category": "basics", "piece": 0, "pieces": 1,
            "tokens": 20, "section_tokens": 20}


def test_need_info_is_passed_through_with_choices_and_never_rewritten():
    llm = ScriptedLLM(router='{"intents": ["goal"], "confidence": 0.9}')
    llm_module.set_llm(llm)
    s = ask(HOUSE)
    assert s["final_response"].startswith(N.GOAL_ASK) and s["final_response"].endswith(DISCLAIMER)
    assert s["choices"] == ["What should I know before buying a house?", "Plan savings for a $60,000 down payment in 5 years"]
    assert "synth" not in llm.calls and s["sources"] == []                      # nothing invented around the question
    assert any("asking with 2 choices" in t for t in s["trace"])


def test_need_info_choices_fall_back_to_defaults_without_llm():
    s = ask("How should I plan for retirement?")
    assert "target amount" in s["final_response"] and s["choices"] == N.GOAL_CHOICES


def test_not_found_researches_llm_topics_instead_of_the_raw_sentence():
    wiki = FakeWiki(results={"mortgage": ["Mortgage loan"], "down payment": ["Down payment"]})
    set_wiki_client(wiki)
    set_kb_searcher(lambda q, k=None: [kb_hit(MIN - 0.05)])                    # below min_score: topic not indexed
    llm_module.set_llm(ScriptedLLM())
    s = ask(HOUSE)
    assert wiki.queries == []                                                  # exact titles fetched, no search needed
    assert [x["title"] for x in s["sources"]] == ["Mortgage loan (Wikipedia)", "Down payment (Wikipedia)"]
    assert "wiki_topic('Mortgage loan') → Mortgage loan" in s["trace"]
    assert s["final_response"].startswith("Answer written from the context.")
    assert any(t.startswith("research: topics") for t in s["trace"])


def test_verifier_sends_kb_answers_that_dont_answer_to_research():
    wiki = FakeWiki(results={"mortgage": ["Mortgage loan"]})
    set_wiki_client(wiki)
    set_kb_searcher(lambda q, k=None: [kb_hit(MIN + 0.1)])                     # strong score, wrong content
    llm = ScriptedLLM(check='{"answers": false}', topics='{"topics": ["Mortgage loan"]}')
    llm_module.set_llm(llm)
    s = ask("How does a mortgage work?")
    assert llm.calls[:2] == ["router", "check"]
    assert any("don't answer the question → research" in t for t in s["trace"])
    assert [x["title"] for x in s["sources"]] == ["Mortgage loan (Wikipedia)"]


def test_kb_answer_kept_when_verifier_confirms_it():
    set_kb_searcher(lambda q, k=None: [kb_hit(MIN + 0.1)])
    llm_module.set_llm(ScriptedLLM())
    s = ask("What is compound interest?")
    assert s["sources"][0]["url"] == "https://en.wikipedia.org/wiki/Compound_interest"
    assert any(t == "verifier: qa sources answer the question" for t in s["trace"])
    assert not any("research" in t for t in s["trace"])


def test_nothing_found_anywhere_says_so_without_an_llm_answer():
    set_wiki_client(FakeWiki(results={}))
    llm = ScriptedLLM(topics='{"topics": ["Flibbertigibbet"]}')
    llm_module.set_llm(llm)
    s = ask("What is a flibbertigibbet fund?")
    assert "rather not guess" in s["final_response"] and s["sources"] == [] and "synth" not in llm.calls


def test_chat_api_returns_and_stores_choices(client, sid):
    r = client.post(f"/api/sessions/{sid}/chat", json={"message": "How should I plan for retirement?"}).json()
    assert r["choices"] == N.GOAL_CHOICES
    assert client.get(f"/api/sessions/{sid}/messages").json()[-1]["choices"] == N.GOAL_CHOICES


def test_topic_lookup_rejects_search_results_whose_title_doesnt_match():
    from src.workflow.tools import wiki_topic
    wiki = FakeWiki(results={"home buying": ["Opendoor"], "closing": ["Closing costs"]})
    set_wiki_client(wiki)
    assert wiki_topic("Home buying") is None                                   # no such page; "Opendoor" shares no word
    assert wiki_topic("Closing costs")["title"] == "Closing costs"             # exact title


def test_choices_that_question_the_user_are_replaced_by_defaults():
    llm_module.set_llm(ScriptedLLM(router='{"intents": ["goal"], "confidence": 0.9}',
                                   choices='{"choices": ["What is your savings goal amount?", "How long do you want to save?"]}'))
    assert ask("Help me make a savings plan for my goal")["choices"] == N.GOAL_CHOICES


# ------------------------------------------------------------------ replan loop
import pytest  # noqa: E402

ETF_Q = "What would be the symbols of top ETFs like VOO?"


@pytest.fixture
def db():
    from sqlalchemy.orm import sessionmaker

    from src.db.base import Base
    from src.db.session import make_engine
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


def ask_db(q, db):
    return run_chat(q, history=[], profile=PROFILE, holdings=[], db=db)


def test_research_that_doesnt_answer_is_rechecked_and_replanned_to_another_agent(db):
    llm = ScriptedLLM(topics='{"topics": ["Exchange-traded fund"]}', check='{"answers": false, "missing": "ETF ticker symbols"}',
                      replan='{"intents": ["market"], "reason": "market quotes named ETFs"}')
    llm_module.set_llm(llm)
    s = ask_db(ETF_Q, db)
    assert llm.calls.count("check") == 1 and llm.calls.count("replan") == 1        # research checked once, one replan round
    assert any(t.startswith("verifier: qa researched sources don't answer the question either (missing: ETF ticker symbols)") for t in s["trace"])
    assert "replan 1/3: market (market quotes named ETFs)" in s["trace"]
    assert s["agents"] == ["Market Analysis"] and s["data_info"]["provider"] == "sample"       # the quote answers; qa's miss isn't shown
    assert s["sources"] == []                                                       # the rejected Wikipedia page isn't cited


def test_replan_never_reruns_an_agent_and_stops_when_none_can_help():
    llm = ScriptedLLM(topics='{"topics": ["Exchange-traded fund"]}', check='{"answers": false, "missing": "ticker symbols"}',
                      replan='{"intents": ["qa"], "reason": "explain it"}')                # qa already ran: filtered out
    llm_module.set_llm(llm)
    s = ask(ETF_Q)
    assert "replan 1/3: no other agent can supply what is missing" in s["trace"] and llm.calls.count("replan") == 1
    assert any(t.startswith("synthesizer:") and "partial" in t for t in s["trace"])  # falls back to the incomplete research
    assert [x["title"] for x in s["sources"]] == ["Exchange-traded fund (Wikipedia)"]


def test_replan_loop_is_capped_by_max_replans(monkeypatch):
    monkeypatch.setitem(get_config()["workflow"], "max_replans", 1)
    llm = ScriptedLLM(topics='{"topics": ["Exchange-traded fund"]}', check='{"answers": false}',
                      replan=['{"intents": ["tax"]}', '{"intents": ["news"]}'])        # tax fails too, but no second round
    llm_module.set_llm(llm)
    s = ask(ETF_Q)
    assert llm.calls.count("replan") == 1 and "replan 1/1: tax" in s["trace"]
    assert any(t.startswith("verifier: tax") for t in s["trace"])                   # the replanned agent was verified too


def test_replan_runs_up_to_the_limit_trying_new_agents_each_round(db):
    llm = ScriptedLLM(topics='{"topics": ["Exchange-traded fund"]}', check='{"answers": false}',
                      replan=['{"intents": ["tax"]}', '{"intents": ["tax", "market"]}', '{"intents": []}'])
    llm_module.set_llm(llm)
    s = ask(ETF_Q.replace(" like VOO", ""))                                           # no ticker: market finds nothing either
    assert [t for t in s["trace"] if t.startswith("replan")] == ["replan 1/3: tax", "replan 2/3: market",
                                                                  "replan 3/3: no other agent can supply what is missing"]


def test_no_replan_without_an_llm():
    set_wiki_client(FakeWiki(results={}))
    s = ask("What is a flibbertigibbet fund?")
    assert not any(t.startswith("replan") for t in s["trace"]) and "rather not guess" in s["final_response"]
