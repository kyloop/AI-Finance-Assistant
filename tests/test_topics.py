"""Topic memory, step 1 (mds/topic-memory.md): each answer joins a topic, the topics row rolls its turns up, and a topic
can be rebuilt from its messages. The pure tests need no app; the API tests run through /chat with no LLM (conftest)."""
import pytest

from src.core import llm as llm_module
from src.workflow import topics as T

TSLA = {"symbol": "TSLA", "name": "Tesla"}
SBUX = {"symbol": "SBUX", "name": "Starbucks"}
MONTH = {"label": "1 month", "start": "2026-09-30"}


def ctx(question, intents=("market",), companies=(), markets=(), facts=None, source_ids=(), topic_id=None, period=MONTH):
    return {"question": question, "intents": list(intents), "companies": list(companies), "markets": list(markets),
            "levels": [], "tab": "Chat", "symbol": None, "period": period, "facts": facts or {},
            "topic_id": topic_id, "source_ids": list(source_ids)}


# ---------------------------------------------------------------- pure helpers
def test_topic_ids_count_up_within_a_conversation():
    assert T.next_topic_id([]) == "t1"
    assert T.next_topic_id(["t1", "t2"]) == "t3"
    assert T.next_topic_id(["t2", "t9", "x"]) == "t10"


def test_labels_are_built_from_the_companies_and_what_was_asked():
    one = T.apply_turn(T.empty_topic("t1"), ctx("How has TSLA performed?", companies=[TSLA]), 1)
    assert one["label"] == "TSLA performance"
    two = T.apply_turn(one, ctx("How have TSLA and SBUX performed?", companies=[TSLA, SBUX]), 2)
    assert two["label"] == "TSLA, SBUX performance"
    three = T.apply_turn(two, ctx("Any news on them?", intents=["news"], companies=[TSLA, SBUX]), 3)
    assert three["label"] == "TSLA, SBUX performance & news"


def test_a_topic_without_entities_keeps_the_label_it_started_with():
    one = T.apply_turn(T.empty_topic("t1"), ctx("What is swing trading?", intents=["qa"], period=None), 1, label="Swing trading")
    two = T.apply_turn(one, ctx("Show an example of a swing trade.", intents=["calc"], period=None), 2, label="Something else")
    assert one["label"] == two["label"] == "Swing trading"
    assert T.apply_turn(T.empty_topic("t2"), ctx("How diversified is my portfolio?", intents=["portfolio"]), 3)["label"] == "Your portfolio"


def test_a_label_names_the_company_once_the_topic_gains_one():
    one = T.apply_turn(T.empty_topic("t1"), ctx("What is swing trading?", intents=["qa"]), 1, label="Swing trading")
    two = T.apply_turn(one, ctx("Can you swing trade NVDA?", intents=["qa", "market"], companies=[{"symbol": "NVDA", "name": "NVIDIA"}]), 2)
    assert two["label"] == "NVDA performance"


def test_apply_turn_merges_lists_and_keeps_the_latest_values():
    first = T.apply_turn(T.empty_topic("t1"), ctx("TSLA?", companies=[TSLA], source_ids=["kb:a#(lead)"],
                                                 facts={"TSLA": {"price": 1.0, "as_of": "2026-10-01"}}), 10)
    nxt = ctx("TSLA vs SBUX this year?", companies=[TSLA, SBUX], source_ids=["kb:a#(lead)", "kb:b#X"],
              facts={"TSLA": {"return": 0.1, "as_of": "2026-10-30"}, "SBUX": {"return": -0.03, "as_of": "2026-10-30"}},
              period={"label": "year to date", "start": "2026-01-02"})
    t = T.apply_turn(first, nxt, 12)
    assert [c["symbol"] for c in t["companies"]] == ["TSLA", "SBUX"]
    assert t["source_ids"] == ["kb:a#(lead)", "kb:b#X"]
    assert t["facts"]["TSLA"] == {"return": 0.1, "as_of": "2026-10-30"}          # replaced whole: no stale price mixed in
    assert t["period"]["label"] == "year to date"
    assert t["message_ids"] == [10, 12] and t["turns"] == 2
    assert first["message_ids"] == [10]                                          # the input topic is not changed


def test_entities_are_capped_most_recent_first():
    names = [{"symbol": s, "name": s} for s in ("AAA", "BBB", "CCC")]
    t = T.apply_turn(T.empty_topic("t1"), ctx("q", companies=names), 1)
    t = T.apply_turn(t, ctx("and DDD?", companies=[{"symbol": "DDD", "name": "DDD"}]), 2)
    assert [c["symbol"] for c in t["companies"]] == ["DDD", "AAA", "BBB"]


def test_sources_keep_the_ten_most_recent():
    t = T.empty_topic("t1")
    for i in range(14):
        t = T.apply_turn(t, ctx("q", source_ids=[f"kb:d{i}#(lead)"]), i)
    assert len(t["source_ids"]) == T.MAX_SOURCES and t["source_ids"][-1] == "kb:d13#(lead)" and t["source_ids"][0] == "kb:d4#(lead)"


def test_figures_the_user_did_not_give_are_caught():
    assert T.adds_figures("TSLA rose 7.2% last month.", "How has TSLA done?")
    assert T.adds_figures("TSLA is at $297.55.", "How has TSLA done?")
    assert not T.adds_figures("Compared TSLA and SBUX performance.", "How has TSLA done?")
    assert not T.adds_figures("Worked out how $10,000 grows at 8% a year.", "How much does $10,000 grow at 8% a year?")


def test_summaries_are_clipped_to_three_sentences():
    assert T.clip_summary("One. Two. Three. Four.") == "Two. Three. Four."
    assert T.fallback_summary(["Asked about TSLA", "Compared TSLA and SBUX.", "", "Asked for news.", "Asked about volatility"]) == \
        "Compared TSLA and SBUX. Asked for news. Asked about volatility."


# ---------------------------------------------------------------- summaries with and without an LLM
class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def invoke(self, messages):
        return type("R", (), {"content": self.reply})()


@pytest.fixture
def llm():
    def use(reply):
        llm_module.set_llm(FakeLLM(reply))
    yield use
    llm_module.clear_llm_override()


def test_without_an_llm_the_summary_is_the_question():
    topic = T.empty_topic("t1")
    turn, merged, label = T.summarize_turn(topic, ctx("How has TSLA stock performed?"), earlier_turns=[], earlier_questions=[])
    assert (turn, merged, label) == ("How has TSLA stock performed?", "How has TSLA stock performed?", "")


def test_the_llm_writes_the_summaries(llm):
    llm('{"summary": "Compared TSLA and SBUX performance.", "topic_summary": "Looked at TSLA, then compared it with SBUX.", '
        '"label": "TSLA vs SBUX"}')
    turn, merged, label = T.summarize_turn({"label": "TSLA performance", "summary": "Looked at TSLA."},
                                           ctx("How have TSLA and SBUX performed?"), earlier_turns=["Looked at TSLA."],
                                           earlier_questions=["How has TSLA performed?"])
    assert turn == "Compared TSLA and SBUX performance."
    assert merged == "Looked at TSLA, then compared it with SBUX." and label == "TSLA vs SBUX"


def test_a_summary_with_figures_falls_back(llm):
    llm('{"summary": "TSLA rose 7.2% while SBUX fell 3.1%.", "topic_summary": "TSLA is at $297.55.", "label": "TSLA"}')
    turn, merged, _ = T.summarize_turn({"summary": "Looked at TSLA."}, ctx("How have TSLA and SBUX performed?"),
                                       earlier_turns=["Looked at TSLA."], earlier_questions=["How has TSLA performed?"])
    assert turn == "How have TSLA and SBUX performed?"
    assert merged == "Looked at TSLA. How have TSLA and SBUX performed?"


def test_an_unusable_reply_falls_back(llm):
    llm("sure, here you go")
    turn, merged, label = T.summarize_turn(T.empty_topic("t1"), ctx("What is an expense ratio?", intents=["qa"]),
                                           earlier_turns=[], earlier_questions=[])
    assert (turn, merged, label) == ("What is an expense ratio?", "What is an expense ratio?", "")


# ---------------------------------------------------------------- through the chat API (no LLM)
def _chat(client, sid, text, cid=None):
    body = {"message": text, **({"conversation_id": cid} if cid else {})}
    r = client.post(f"/api/sessions/{sid}/chat", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def db(client):
    """A session on the test app's database, open for the whole test so what is read from it can still load (the generator
    must be kept: dropping it closes the session and detaches the objects), and closed afterwards."""
    from src.api.main import app
    from src.db.session import get_db
    gen = app.dependency_overrides[get_db]()
    yield next(gen)
    gen.close()


def _db_conv(db, sid):
    from src.db.models import Conversation
    return db, db.query(Conversation).filter_by(session_id=sid).order_by(Conversation.id.desc()).first()


def test_each_answer_joins_a_topic_and_the_topic_rolls_its_turns_up(client, sid, db):
    _chat(client, sid, "What is an ETF?")
    _chat(client, sid, "What is the price of NVDA?")                           # not a follow-up: a new topic
    db, conv = _db_conv(db, sid)
    replies = [m for m in conv.messages if m.role == "assistant"]
    assert [m.context["topic_id"] for m in replies] == ["t1", "t2"]
    assert [m.context["summary"] for m in replies] == [m.context["question"] for m in replies]   # no LLM: the question
    rows = {t.topic_id: t for t in conv.topics}
    assert set(rows) == {"t1", "t2"}
    assert rows["t1"].message_ids == [replies[0].id] and rows["t2"].message_ids == [replies[1].id]
    assert rows["t1"].summary == replies[0].context["question"] and rows["t2"].label.startswith("NVDA")


def test_a_follow_up_stays_in_the_topic(client, sid, db):
    _chat(client, sid, "What is the price of NVDA?")
    _chat(client, sid, "what about MSFT?")
    db, conv = _db_conv(db, sid)
    a, b = [m for m in conv.messages if m.role == "assistant"]
    assert a.context["topic_id"] == b.context["topic_id"] == "t1"               # "what about" carries the context → same topic
    assert len(conv.topics) == 1 and conv.topics[0].turns == 2
    assert conv.topics[0].summary == T.fallback_summary([a.context["question"], b.context["question"]])


def test_a_rebuilt_topic_matches_the_live_one(client, sid, db):
    _chat(client, sid, "What is the price of NVDA?")
    _chat(client, sid, "what about MSFT?")
    db, conv = _db_conv(db, sid)
    live = {t.topic_id: T._as_dict(t) for t in conv.topics}
    for topic_id, before in live.items():
        after = T.rebuild_topic(db, conv, topic_id)
        for key in ("label", "companies", "markets", "intents", "period", "facts", "source_ids", "message_ids", "turns"):
            assert after[key] == before[key], key


def test_rebuilding_a_topic_with_no_turns_left_removes_it(client, sid, db):
    _chat(client, sid, "What is an ETF?")
    db, conv = _db_conv(db, sid)
    msg = next(m for m in conv.messages if m.role == "assistant")
    msg.context = {**msg.context, "topic_id": "t7"}
    db.commit()
    assert T.rebuild_topic(db, conv, "t1") is None and not any(t.topic_id == "t1" for t in conv.topics)
    assert T.rebuild_topic(db, conv, "t7")["turns"] == 1


def test_deleting_a_conversation_deletes_its_topics(client, sid, db):
    _chat(client, sid, "What is an ETF?")
    db, conv = _db_conv(db, sid)
    from src.db.models import Topic
    cid = conv.id                                     # read before the delete: afterwards the row can't be reloaded
    assert db.query(Topic).filter_by(conversation_id=cid).count() == 1
    assert client.delete(f"/api/sessions/{sid}/conversations/{cid}").status_code == 204
    db.expire_all()
    assert db.query(Topic).filter_by(conversation_id=cid).count() == 0


# ---------------------------------------------------------------- which turns stay in the previous topic
from src.workflow import context as CTX  # noqa: E402

ETF_CONTEXT = {"question": "What is an ETF?", "intents": ["qa"], "companies": [], "markets": [], "facts": {}, "topic_id": "t1"}


def _built(question, intents, follow_up):
    return CTX.build({"question": question, "intent": intents, "follow_up": follow_up, "context_in": ETF_CONTEXT,
                      "entities": {}, "turn_context": {}, "sources": []})


def test_a_calculation_that_points_back_stays_in_the_topic():
    assert _built("How much will $10,000 grow at 7% on this ETF?", ["calc"], follow_up=True)["topic_id"] == "t1"


def test_a_calculation_that_does_not_point_back_starts_a_topic():
    assert _built("How much will $10,000 grow at 7%?", ["calc"], follow_up=False)["topic_id"] is None


def test_a_new_question_starts_a_topic_and_a_follow_up_keeps_it():
    assert _built("What is the price of NVDA?", ["market"], follow_up=False)["topic_id"] is None
    assert _built("What are its fees?", ["qa"], follow_up=True)["topic_id"] == "t1"


def test_through_the_api_a_calculation_on_this_etf_joins_the_etf_topic(client, sid, db):
    _chat(client, sid, "What is an ETF?")
    _chat(client, sid, "How much will $10,000 grow at 7% on this ETF?")       # "this": a follow-up, even without an LLM
    _chat(client, sid, "How much will $5,000 grow at 6% over 8 years?")        # points at nothing: a topic of its own
    db, conv = _db_conv(db, sid)
    assert [m.context["topic_id"] for m in conv.messages if m.role == "assistant"] == ["t1", "t1", "t2"]


# ================================================================ step 2: entities and topic assignment
NVDA = {"symbol": "NVDA", "name": "NVIDIA"}
US = {"key": "group:us_indices", "name": "US stock market"}


def cand(topic_id, *, uid=None, label="", entities=(), updated="2026-11-01T10:00:00", summary="", vec=None, conv=1, **kw):
    return {"uid": uid or f"u-{conv}-{topic_id}", "topic_id": topic_id, "conversation_id": conv, "label": label,
            "entities": [list(e) for e in entities], "updated_at": updated, "summary": summary, "summary_vec": vec,
            "companies": kw.get("companies", []), "markets": kw.get("markets", []), "intents": kw.get("intents", []),
            "period": kw.get("period"), "facts": kw.get("facts", {}), "source_ids": kw.get("source_ids", []),
            "last_question": kw.get("last_question", "")}


def msg(question, *, intents=("market",), companies=(), tickers=(), markets=(), wiki_query="", current="t1", follow_up=False,
        original=None):
    return {"question": question, "original_question": original or question, "intent": list(intents), "follow_up": follow_up,
            "context_in": {"topic_id": current} if current else None,
            "entities": {"companies": list(companies), "tickers": list(tickers), "markets": list(markets), "wiki_query": wiki_query}}


def test_turn_entities_come_from_what_the_agents_used():
    keys = T.turn_entities(ctx("q", intents=["qa", "portfolio"], companies=[TSLA], markets=[US],
                               source_ids=["kb:expense-ratio#(lead)", "kb:index-fund#Costs", "kb:stock#(lead)",
                                           "wikipedia:Tax return (United States):123", "web:https://x.com", "news:9"]))
    assert keys == {("company", "TSLA"), ("market", "group:us_indices"), ("user_data", "portfolio"),
                    ("concept", "expense-ratio"), ("concept", "index-fund")}               # only the top 2 sources
    assert T.concept_of("wikipedia:Tax return (United States):123") == "tax-return-united-states"


def test_a_named_company_decides_rule_5():
    hard, _ = T.message_entities(msg("Is market sentiment favorable toward NVDA?", companies=[NVDA], markets=[US]))
    assert hard == {("company", "NVDA")}
    hard, _ = T.message_entities(msg("How is the market doing today?", markets=[US]))
    assert hard == {("market", "group:us_indices")}


def test_rule_1_entities_that_match_nothing_start_a_new_topic():
    pool = {"current": [cand("t1", label="SPY, NVDA performance", entities=[("company", "SPY"), ("company", "NVDA")])]}
    got = T.choose(msg("How is the market doing today?", markets=[US]), pool, embed=lambda t: 1 / 0)   # no embedding call
    assert got["action"] == "new" and got["topic_id"] is None


def test_rule_2_a_message_with_no_subject_continues():
    pool = {"current": [cand("t3", label="Swing trading", entities=[("concept", "swing-trading")])]}
    got = T.choose(msg("show example", intents=["calc"], current="t3"), pool)
    assert got["action"] == "continue" and got["topic_id"] == "t3"


def test_rule_3_several_matches_continue_the_most_recent_and_link_the_rest():
    pool = {"current": [cand("t1", entities=[("company", "NVDA")], updated="2026-11-01T10:00:00"),
                        cand("t3", entities=[("concept", "swing-trading"), ("company", "NVDA")], updated="2026-11-01T10:05:00")]}
    got = T.choose(msg("Can you swing trade NVDA?", intents=["qa", "market"], companies=[NVDA], current="t3",
                       wiki_query="swing trade NVDA"), pool)
    assert got["action"] == "continue" and got["topic_id"] == "t3" and got["related"] == ["u-1-t1"]


def test_a_company_named_again_reopens_its_older_topic():
    tsla = cand("t1", label="TSLA performance", entities=[("company", "TSLA")], companies=[TSLA], period=MONTH,
                facts={"TSLA": {"return": 0.07, "as_of": "2026-10-30"}}, last_question="How has TSLA performed?")
    pool = {"current": [tsla, cand("t2", label="Expense ratio", entities=[("concept", "expense-ratio")])]}
    got = T.choose(msg("back to tesla, any news?", intents=["news"], companies=[TSLA], current="t2"), pool)
    assert got["action"] == "reopen" and got["topic_id"] == "t1"
    assert got["context"]["companies"] == [TSLA] and got["context"]["period"] == MONTH and got["context"]["topic_id"] == "t1"


def test_a_follow_up_always_continues():
    pool = {"current": [cand("t1", entities=[("company", "TSLA")])]}
    got = T.choose(msg("compare to starbucks", companies=[SBUX], follow_up=True), pool)
    assert got["action"] == "continue" and got["topic_id"] == "t1"


def test_a_concept_named_again_reopens_its_topic():
    pool = {"current": [cand("t1", entities=[("concept", "swing-trading")]), cand("t2", entities=[("company", "TSLA")])]}
    got = T.choose(msg("what is swing trading again?", intents=["qa"], wiki_query="swing trading", current="t2"), pool)
    assert got["action"] == "reopen" and got["topic_id"] == "t1"


def test_walkthrough_tax_market_tesla_nvda():
    t1 = cand("t1", label="Tax return", entities=[("concept", "tax-return-united-states")], updated="2026-11-01T10:00:00")
    t2 = cand("t2", label="US market performance & news", entities=[("market", "group:us_indices")], updated="2026-11-01T10:01:00")
    t3 = cand("t3", label="TSLA performance", entities=[("company", "TSLA")], updated="2026-11-01T10:03:00")
    pool = {"current": [t1, t2, t3]}
    q3 = T.choose(msg("Which stocks gained the most today?", follow_up=True, current="t2"), {"current": [t1, t2]})
    assert q3["topic_id"] == "t2"
    q5 = T.choose(msg("Is TSLA up or down?", follow_up=True, current="t3"), pool)
    assert q5["topic_id"] == "t3"
    q6 = T.choose(msg("Is market sentiment favorable toward NVDA?", intents=["market", "news"], companies=[NVDA], markets=[US],
                      current="t3"), pool)
    assert q6["action"] == "new"                                                              # not the US-market topic


# ================================================================ step 3: embeddings and earlier chats
def test_rule_4_wording_alone_needs_an_embedding_match():
    pool = {"current": [cand("t1", label="Risk", summary="Discussed how much risk to take at 30.", vec=[1.0, 0.0])]}
    near = T.choose(msg("how should I think about risk when young?", intents=["qa"], current="t9"), pool, embed=lambda t: [[0.95, 0.1]])
    far = T.choose(msg("how should I think about risk when young?", intents=["qa"], current="t9"), pool, embed=lambda t: [[0.1, 1.0]])
    off = T.choose(msg("how should I think about risk when young?", intents=["qa"], current="t9"), pool, embed=None)
    assert near["action"] == "reopen" and near["topic_id"] == "t1"
    assert far["action"] == off["action"] == "new"


def test_earlier_chats_are_linked_never_continued():
    old = cand("t1", conv=7, uid="old-tsla", label="TSLA, SBUX performance", entities=[("company", "TSLA"), ("company", "SBUX")],
               summary="Compared TSLA and SBUX performance over one month.", updated="2026-10-03T09:00:00",
               facts={"TSLA": {"price": 277.56, "return": 0.072, "period": "1 month", "as_of": "2026-10-02"}})
    got = T.choose(msg("TSLA vs NVDA this year?", companies=[TSLA, NVDA], current=None), {"current": [], "earlier": [old]})
    assert got["action"] == "link" and got["topic_id"] is None and got["related"] == ["old-tsla"]
    assert got["linked"] == [{"uid": "old-tsla", "date": "2026-10-03", "label": "TSLA, SBUX performance"}]
    assert "2026-10-03: Compared TSLA and SBUX performance" in got["background"]
    assert "277" not in got["background"] and "context" not in got                        # no figures, no carried subject


def test_since_last_time_brings_the_dated_figures():
    old = cand("t1", conv=7, label="TSLA performance", entities=[("company", "TSLA")], summary="Looked at TSLA performance.",
               facts={"TSLA": {"price": 277.56, "as_of": "2026-10-02"}})
    got = T.choose(msg("How has TSLA changed since we last talked?", companies=[TSLA], current=None), {"current": [], "earlier": [old]})
    assert "TSLA then (as of 2026-10-02, for comparison only): price 277.56" in got["background"]


def test_this_chat_comes_before_earlier_chats():
    here = cand("t1", label="TSLA news", entities=[("company", "TSLA")])
    old = cand("t1", conv=7, uid="old", entities=[("company", "TSLA")])
    got = T.choose(msg("TSLA vs NVDA this year?", companies=[TSLA, NVDA], current="t1"), {"current": [here], "earlier": [old]})
    assert got["action"] == "continue" and got["linked"] == []


def test_an_earlier_chat_needs_the_stricter_similarity():
    old = cand("t1", conv=7, uid="old", label="Risk", summary="Risk at 30.", vec=[1.0, 0.0])
    q = msg("how should I think about risk when young?", intents=["qa"], current=None)
    assert T.choose(q, {"current": [], "earlier": [old]}, embed=lambda t: [[0.83, 0.56]])["action"] == "new"     # cos 0.83
    assert T.choose(q, {"current": [], "earlier": [old]}, embed=lambda t: [[0.95, 0.31]])["action"] == "link"    # cos 0.95


def test_follow_up_wording_without_a_subject():
    for text in ("show example", "Show me an example", "tell me more", "why?"):
        assert CTX.subjectless(text) and CTX.looks_like_follow_up(text), text
    for text in ("Can you give an example of compound interest?", "what is swing trading?"):
        assert not CTX.subjectless(text), text


def test_reranked_keeps_each_chunk_once_by_score():
    from src.workflow.nodes import _reranked
    fresh = [{"doc_id": "a", "section": "(lead)", "piece": 0, "score": 0.70}, {"doc_id": "b", "section": "X", "piece": 0, "score": 0.69}]
    earlier = [{"doc_id": "a", "section": "(lead)", "piece": 0, "score": 0.70}, {"doc_id": "c", "section": "Y", "piece": 0, "score": 0.75}]
    assert [h["doc_id"] for h in _reranked(fresh, earlier, 5)] == ["c", "a", "b"]


# ---------------------------------------------------------------- through the graph and the API
def test_the_topic_node_runs_after_the_router_and_is_a_no_op_without_topics():
    from src.workflow import graph as G
    assert [n["id"] for n in G.flow_layout()][:3] == ["proofread", "router", "topic"]
    assert any(e["from"] == "router" and e["to"] == "topic" for e in G.flow_edges())
    s = G.run_chat("What is an ETF?", history=[], profile={"knowledge_level": "beginner", "risk_tolerance": "moderate", "horizon_years": 10}, holdings=[], db=None)
    assert "topic: no topic memory for this run" in s["trace"] and "topic" not in s


def test_the_api_reopens_an_older_topic_of_the_chat(client, sid, db):
    _chat(client, sid, "What is the price of NVDA?")
    _chat(client, sid, "What is an ETF?")
    _chat(client, sid, "What is the price of NVDA today?")                     # names NVDA again: back to t1, not a new topic
    db, conv = _db_conv(db, sid)
    assert [m.context["topic_id"] for m in conv.messages if m.role == "assistant"] == ["t1", "t2", "t1"]
    nvda = next(t for t in conv.topics if t.topic_id == "t1")
    assert nvda.turns == 2 and ("company", "NVDA") in {(e.kind, e.key) for e in nvda.entities}


def test_the_api_links_an_earlier_chat_and_can_answer_without_it(client, sid, db, monkeypatch):
    from src.workflow import nodes as N
    _chat(client, sid, "What is the price of NVDA?")
    cid = client.post(f"/api/sessions/{sid}/conversations").json()["id"]
    monkeypatch.setattr(N, "_writes_from_notes", lambda: True)               # as with an LLM: the reply may use the notes
    reply = _chat(client, sid, "What is the price of NVDA?", cid)
    assert [l["label"] for l in reply["linked"]] == ["NVDA performance"]          # shown as "Using 1 earlier chat"
    db, conv = _db_conv(db, sid)
    assert conv.id == cid and conv.topics[0].related and conv.topics[0].topic_id == "t1"
    again = client.post(f"/api/sessions/{sid}/chat", json={"message": "What is the price of NVDA?", "conversation_id": cid,
                                                           "no_memory": True}).json()
    db.expire_all()
    assert again["linked"] == [] and conv.topics[0].related == []


def test_topics_get_an_embedding_when_embeddings_are_on(client, sid, db):
    T.set_topic_embedder(lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    _chat(client, sid, "What is an ETF?")
    db, conv = _db_conv(db, sid)
    assert conv.topics[0].summary_vec == [0.1, 0.2, 0.3]


# ================================================================ optional: lowercase names without an LLM
def test_lowercase_company_names_next_to_a_cue_are_found():
    from src.workflow import symbols as S
    assert S.lowercase_mentions("ho'ws tesla stock doing?") == ["TSLA"]
    assert S.lowercase_mentions("visa stock price") == ["V"]
    for text in ("I want to save for a visa", "how is the market doing", "how are growth stocks doing", "first stock I bought"):
        assert S.lowercase_mentions(text) == [], text


def test_without_an_llm_a_lowercase_company_goes_to_the_market_agent(client, sid):
    reply = _chat(client, sid, "ho'ws tesla stock doing?")
    assert "Market Analysis" in reply["agents"]


def test_turn_summary_sees_the_start_of_the_answer():
    from src.workflow import topics as TOP
    prompt = TOP._turn_prompt({}, {"question": "How is my goal planning?", "intents": ["goal"]}, [],
                              "Your retirement plan is projected to fall short of its target.")
    assert "Answer (start; say what it covered, not its figures): Your retirement plan is projected" in prompt
    assert "Answer" not in TOP._turn_prompt({}, {"question": "q"}, [])
