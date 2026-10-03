"""The agent-flow stream: node events from the LangGraph run, and the NDJSON chat endpoint that carries them."""
import json

import pytest

from src.workflow import graph as G

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate", "horizon_years": 10, "goals": []}


@pytest.fixture
def db():
    from sqlalchemy.orm import sessionmaker

    from src.db.base import Base
    from src.db.session import make_engine
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


def run(q, db=None, **kw):
    return list(G.stream_chat(q, history=[], profile=PROFILE, holdings=[], db=db, **kw))


def test_flow_layout_covers_every_graph_node():
    ids = {n["id"] for n in G.flow_layout()}
    assert ids == set(G.get_graph().get_graph().nodes) - {"__start__", "__end__"}


def test_events_start_and_end_each_node_in_order():
    events = run("What is an ETF?")
    nodes = [e for e in events if e["type"] != "final"]
    assert events[-1]["type"] == "final" and events[-1]["state"]["final_response"]
    assert [e["node"] for e in nodes if e["type"] == "node_start"] == [e["node"] for e in nodes if e["type"] == "node_end"]
    assert [e["node"] for e in nodes if e["type"] == "node_start"][:2] == ["proofread", "router"]
    assert [e["node"] for e in nodes if e["type"] == "node_start"][-1] == "compliance"
    router_end = next(e for e in nodes if e["type"] == "node_end" and e["node"] == "router")
    assert router_end["picked"] == ["qa_agent"] and "keywords" in router_end["detail"]
    assert all(e["ms"] >= 0 and e["t"] >= 0 for e in nodes if e["type"] == "node_end")


def test_parallel_agents_both_appear_and_report_status(db):
    events = run("Is my portfolio too tech-heavy? What is the S&P 500 doing?", db)
    ended = {e["node"]: e for e in events if e["type"] == "node_end"}
    assert {"portfolio_agent", "market_agent"} <= set(ended)
    assert ended["market_agent"]["status"] == "answered"
    assert {"portfolio_agent", "market_agent"} == set(ended["router"]["picked"])
    starts = [e["node"] for e in events if e["type"] == "node_start"]
    assert starts.index("market_agent") < next(i for i, e in enumerate(events) if e["type"] == "node_end" and e["node"] in ("market_agent", "portfolio_agent"))


def test_an_agent_that_fails_is_reported_as_error_and_the_run_continues():
    events = run("What is the S&P 500 doing?")                 # no database session: the market agent fails inside its wrapper
    assert next(e for e in events if e["type"] == "node_end" and e["node"] == "market_agent")["status"] == "error"
    assert events[-1]["type"] == "final"


def test_a_failing_node_ends_with_error_status_then_raises(monkeypatch):
    def boom(state, config):
        raise RuntimeError("boom")
    monkeypatch.setattr(G.N, "synthesizer_node", boom)
    G.get_graph.cache_clear()
    seen = []
    try:
        with pytest.raises(RuntimeError):
            for e in G.stream_chat("What is an ETF?", history=[], profile=PROFILE, holdings=[], db=None):
                seen.append(e)
    finally:
        G.get_graph.cache_clear()
    assert seen[-1]["type"] == "node_end" and seen[-1]["node"] == "synthesizer" and seen[-1]["status"] == "error"


def stream(client, sid, message):
    r = client.post(f"/api/sessions/{sid}/chat/stream", json={"message": message})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in r.text.splitlines()]


def test_stream_endpoint_emits_nodes_then_the_stored_reply(client, sid):
    events = stream(client, sid, "What is an ETF?")
    assert events[0] == {**events[0], "type": "node_start", "node": "proofread"}
    done = events[-1]
    assert done["type"] == "done" and "not financial advice" in done["message"]["content"]
    stored = client.get(f"/api/sessions/{sid}/messages").json()
    assert [m["role"] for m in stored] == ["user", "assistant"] and stored[1]["content"] == done["message"]["content"]


def test_stream_endpoint_empty_message_and_failure(client, sid, monkeypatch):
    assert [e["type"] for e in stream(client, sid, "  ")] == ["done"]
    def boom(*a, **k):
        raise RuntimeError("boom")
        yield
    monkeypatch.setattr("src.api.routers.chat.stream_chat", boom)
    done = stream(client, sid, "What is an ETF?")[-1]
    assert done["type"] == "done" and "something went wrong" in done["message"]["content"]


def test_flow_edges_include_the_research_and_replan_loops_and_match_the_nodes():
    edges = G.flow_edges()
    pairs = {(e["from"], e["to"]): e["conditional"] for e in edges}
    assert pairs[("verifier", "research")] and pairs[("verifier", "replan")] and pairs[("verifier", "illustrate")]
    assert pairs[("research", "verifier")] is False                                  # research is always rechecked
    assert pairs[("replan", "illustrate")] and all(pairs[("replan", a)] for a in G.AGENT_NODES)
    assert ("__start__", "proofread") in pairs and ("proofread", "router") in pairs and ("compliance", "__end__") in pairs
    assert {x for e in edges for x in (e["from"], e["to"])} == {n["id"] for n in G.flow_layout()} | {"__start__", "__end__"}


def test_flow_endpoint(client):
    assert client.get("/api/chat/flow").json()["edges"] == G.flow_edges()
    nodes = client.get("/api/chat/flow").json()["nodes"]
    assert nodes[0]["id"] == "proofread" and nodes[0]["kind"] == "step" and nodes[0]["stage"] == 0
    assert nodes[1]["id"] == "router" and nodes[1]["stage"] == 1
    assert all(n["description"] for n in nodes) and "Wikipedia" in next(n for n in nodes if n["id"] == "research")["description"]
    assert {n["id"] for n in nodes if n["kind"] == "agent"} == set(G.AGENT_NODES)
