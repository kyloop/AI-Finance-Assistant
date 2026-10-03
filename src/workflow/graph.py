"""The Finnie orchestrator (LangGraph).

  START → proofread → router ─┬→ qa_agent ───────┐
                              ├→ tax_agent ──────┤
                              ├→ market_agent ───┤
                              ├→ news_agent ─────┤
                              ├→ portfolio_agent ┼→ verifier ─┬─(not_found, not yet researched)→ research ─→ verifier (again)
                              ├→ goal_agent ─────┤     ▲      ├─(still not_found after research)→ replan ─┬→ [agents not yet tried]
                              ├→ calc_agent ─────┤     │      │                                           └→ illustrate (none can help)
                              └→ clarify ────────┘     └──────┼── (the picked agents report back to the verifier)
                                                              └─(otherwise)→ illustrate → synthesizer → followups → compliance → END
Proofread fixes spelling, grammar and abbreviations in the message first (LLM only; otherwise it passes the message
through), so the router and agents read "TSLA over the last 10 years" rather than "tsla last 10 yrs".
The router picks one or more agents (run in parallel), each reporting answered / not_found / need_info. The verifier
rechecks them once each (knowledge-base and researched answers that don't answer the question become not_found;
follow-ups get clickable choices). Research looks not_found topics up on Wikipedia and goes back to the verifier. If an
output is still not_found after research, replan asks the LLM which agents not yet tried could supply what is missing
and runs them; this loop runs at most workflow.max_replans times (config.yaml) and never without an LLM. The synthesizer
writes only from answered outputs (falling back to the incomplete research only if nothing else answered) and passes
follow-up questions and calculator results through unchanged; followups offers a worked calculation, an example and a
related question after a real answer; illustrate adds a worked example with sample numbers to conceptual answers
about numeric topics; compliance filters advice and appends the disclaimer. A clicked choice comes
back as the next user message, so it is routed from the start."""
import time
from collections.abc import Iterator
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from . import nodes as N
from .state import FinanceState

AGENT_NODES = {"qa_agent": N.qa_node, "tax_agent": N.tax_node, "market_agent": N.market_node,
               "news_agent": N.news_node, "portfolio_agent": N.portfolio_node, "goal_agent": N.goal_node, "calc_agent": N.calc_node,
               "clarify": N.clarify_node}


@lru_cache
def get_graph():
    g = StateGraph(FinanceState)
    g.add_node("proofread", N.proofread_node)
    g.add_node("router", N.router_node)
    for name, fn in AGENT_NODES.items():
        g.add_node(name, fn)
        g.add_edge(name, "verifier")
    g.add_node("verifier", N.verifier_node)
    g.add_node("research", N.research_node)
    g.add_node("replan", N.replan_node)
    g.add_node("illustrate", N.illustrate_node)
    g.add_node("synthesizer", N.synthesizer_node)
    g.add_node("followups", N.followups_node)
    g.add_node("compliance", N.compliance_node)
    g.add_edge(START, "proofread")
    g.add_edge("proofread", "router")
    g.add_conditional_edges("router", N.route_after_router, list(AGENT_NODES))
    g.add_conditional_edges("verifier", N.route_after_verifier, ["research", "replan", "illustrate"])
    g.add_edge("research", "verifier")                                       # what research finds is checked too
    g.add_conditional_edges("replan", N.route_after_replan, [*AGENT_NODES, "illustrate"])
    g.add_edge("illustrate", "synthesizer")
    g.add_edge("synthesizer", "followups")
    g.add_edge("followups", "compliance")
    g.add_edge("compliance", END)
    return g.compile()


# What the UI's agent-flow panel draws: one entry per graph node, in left-to-right stages (agents share a stage because
# they run in parallel). tests/test_flow.py keeps this in step with the compiled graph.
FLOW_NODES = [
    ("proofread", "Proofread", 0, "Fixes spelling, grammar and abbreviations in your message (\"10 yrs\" → \"10 years\") before the Router reads it. Needs an LLM; otherwise your message goes through as typed."),
    ("router", "Router", 1, "Reads your question and decides which agents should handle it (several can run at once)."),
    ("qa_agent", "Q&A", 2, "Answers finance concepts from the knowledge base."),
    ("tax_agent", "Tax", 2, "Explains tax rules and accounts in general terms, from the knowledge base."),
    ("market_agent", "Market", 2, "Looks up prices and index moves."),
    ("news_agent", "News", 2, "Finds recent headlines for a company, its industry peers, or the market."),
    ("portfolio_agent", "Portfolio", 2, "Analyses your holdings: allocation, diversification, risk."),
    ("goal_agent", "Goals", 2, "Projects savings toward a target amount and date."),
    ("calc_agent", "Calculator", 2, "Computes exact figures: growth, loan payments, doubling time and more."),
    ("clarify", "Clarify", 2, "Asks you to rephrase when the message can't be understood."),
    ("verifier", "Verifier", 3, "Rechecks every agent's output: do the sources really answer the question? Adds clickable choices when more details are needed."),
    ("research", "Research", 4, "Fallback for when an agent found nothing: looks up the underlying concept on Wikipedia, then hands back to the Verifier. Skipped when every agent had an answer."),
    ("replan", "Replan", 5, "When an agent and Research both came up empty: picks other agents that could supply what is missing and sends the question to them (at most 3 times)."),
    ("illustrate", "Illustrate", 6, "Adds a worked example with sample numbers to conceptual answers about numeric topics."),
    ("synthesizer", "Synthesizer", 7, "Writes the reply from the agents' results only, adding no facts of its own."),
    ("followups", "Follow-ups", 8, "Suggests a few next questions you could ask."),
    ("compliance", "Compliance", 9, "Removes advice-like sentences and adds the disclaimer."),
]


def flow_layout() -> list[dict]:
    return [{"id": i, "label": label, "stage": stage, "kind": "agent" if i in AGENT_NODES else "step", "description": desc}
            for i, label, stage, desc in FLOW_NODES]


def flow_edges() -> list[dict]:
    """The compiled graph's own edges (START/END included); `conditional` ones are chosen at run time by a routing function."""
    return [{"from": e.source, "to": e.target, "conditional": e.conditional} for e in get_graph().get_graph().edges]


def _initial_state(question, history, profile, holdings, saved_goal, view, context=None) -> dict:
    return {"question": question, "history": history, "profile": profile, "holdings": holdings, "saved_goal": saved_goal, "view": view,
            "context_in": context,
            "agent_outputs": {}, "errors": [], "trace": []}


RUN_CONFIG = {"recursion_limit": 60}       # supersteps; the replan loop (at most 3 rounds) needs about 25


def run_chat(question: str, *, history: list[dict], profile: dict, holdings: list[dict], db, saved_goal: dict | None = None, view: dict | None = None,
             context: dict | None = None) -> dict:
    """Invoke the graph for one user turn; returns the final state. `context` is the previous answer's saved context."""
    return get_graph().invoke(_initial_state(question, history, profile, holdings, saved_goal, view, context), config={**RUN_CONFIG, "configurable": {"db": db}})


def _detail(node: str, result: dict) -> tuple[str, str]:
    """(status, one-line note) describing what a finished node did, for the flow panel."""
    if node == "router":
        return "ok", f"{', '.join(result.get('intent') or [])} ({result.get('router_mode', '?')})"
    if node in AGENT_NODES:
        o = next(iter((result.get("agent_outputs") or {}).values()), {})
        return ("error", "failed") if o.get("error") else (o.get("status", "answered"), "")
    trace = result.get("trace") or []
    return "ok", trace[-1].split(": ", 1)[-1][:90] if trace else ""


def stream_chat(question: str, *, history: list[dict], profile: dict, holdings: list[dict], db, saved_goal: dict | None = None,
                view: dict | None = None, context: dict | None = None) -> Iterator[dict]:
    """Run the graph and yield one event as each node starts and finishes (parallel agents overlap), then the final state:
      {"type": "node_start", "node", "t"}                          t = seconds since the turn began
      {"type": "node_end", "node", "t", "ms", "status", "detail"}   status: ok | answered | not_found | need_info | error
                                                                    (the router's and replan's also list the agents they "picked")
      {"type": "final", "state": {...}}
    A node that raises ends with status "error" and the exception then propagates."""
    t0 = time.monotonic()
    running: dict[str, tuple[str, float]] = {}                # task id -> (node, start time)
    final: dict = {}
    stream = get_graph().stream(_initial_state(question, history, profile, holdings, saved_goal, view, context),
                                config={**RUN_CONFIG, "configurable": {"db": db}}, stream_mode=["tasks", "values"])
    try:
        for mode, ev in stream:
            if mode == "values":
                final = ev
                continue
            now = time.monotonic()
            if "input" in ev:                                 # a node is starting
                running[ev["id"]] = (ev["name"], now)
                yield {"type": "node_start", "node": ev["name"], "t": round(now - t0, 3)}
                continue
            _, began = running.pop(ev["id"], (ev["name"], now))
            status, note = ("error", str(ev["error"])[:90]) if ev.get("error") else _detail(ev["name"], ev.get("result") or {})
            end = {"type": "node_end", "node": ev["name"], "t": round(now - t0, 3), "ms": int((now - began) * 1000), "status": status, "detail": note}
            if ev["name"] == "router":
                end["picked"] = N.route_after_router(ev.get("result") or {})
            elif ev["name"] == "replan":                     # the agents a replan round added (none: on to illustrate)
                end["picked"] = [n for n in N.route_after_replan(ev.get("result") or {}) if n in AGENT_NODES]
            yield end
    except Exception as e:
        now = time.monotonic()
        for node, began in running.values():                  # a raising node never reports its own end
            yield {"type": "node_end", "node": node, "t": round(now - t0, 3), "ms": int((now - began) * 1000), "status": "error", "detail": type(e).__name__}
        raise
    yield {"type": "final", "state": final}
