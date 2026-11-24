"""Conversation eval: each conversation in tests/data/conversation_eval.yaml runs turn by turn through the chat API (the
streaming endpoint the app uses), in a fresh session, so history, saved context and topic memory carry over as in the app.
Each answer is then graded by an LLM judge on the four metrics of the knowledge-base and news generation tests
(scripts/eval_generation.py, same grade schema):

  relevance     1-5  does the answer address the question, as meant in the conversation (follow-ups included)?
  faithfulness  0-1  share of the answer's claims supported by the SOURCES: what the agents gave the synthesizer this turn
                     (their outputs and the market tools' exact figures); blank for a decline, which makes no claims
  correctness   1-5  do the answer's facts agree with the reference (live figures: with the sources' values, right period/subject)?
  completeness  0-1  share of the turn's key points the answer covers
A decline where the reference expects an answer scores relevance 1, correctness 1, completeness 0.

  python -m scripts.eval_conversations                      # all: mds/conversation-eval.md + mds/data/conversation-eval.json
  python -m scripts.eval_conversations --only market-today  # re-run some conversations (repeatable); the others' saved results stay
  python -m scripts.eval_conversations --set cross          # the 30 cross-domain chats: mds/conversation-eval-cross.md, ...-cross.html
  python -m scripts.eval_conversations --page-only          # rebuild mds/data/conversation-eval.html from the saved JSON
  python -m scripts.eval_conversations --regrade            # judge the saved answers again (after changing the judge or the YAML)

Needs an LLM key (OpenAI for the judge, the model in config.yaml); market data, news and the KB are live. Chats go to a local
SQLite file (mds/data/conversation-eval.db), never the configured or Turso database. Langfuse traces are sent when it is
configured; the report gives each conversation's Langfuse session id. One judge call per turn.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
# Conversation sets: name -> (cases, file stem of the outputs). "core" is the quick set; "cross" the 30 cross-domain chats.
SETS = {"core": ("conversation_eval.yaml", "conversation-eval", "Finnie Conversation Eval"),
        "cross": ("conversation_eval_cross.yaml", "conversation-eval-cross", "Finnie Cross-Domain Eval")}


def _use_set(name: str) -> None:
    """Point CASES and the outputs (report, raw JSON, HTML page) at one conversation set."""
    global CASES, OUT, RAW, PAGE, PAGE_TITLE
    cases, stem, PAGE_TITLE = SETS[name]
    CASES = ROOT / "tests" / "data" / cases
    OUT = ROOT / "mds" / f"{stem}.md"
    RAW = ROOT / "mds" / "data" / f"{stem}.json"
    PAGE = ROOT / "mds" / "data" / f"{stem}.html"                       # every question, answer and score, for reading and verifying


def load_cases() -> list[dict]:
    """The set's conversations: a plain list, or under `conversations` (beside YAML anchors such as shared portfolios)."""
    data = yaml.safe_load(CASES.read_text())
    return data["conversations"] if isinstance(data, dict) else data


_use_set("core")
PAGE_TEMPLATE = ROOT / "scripts" / "conversation_eval_page.html"
DB_FILE = ROOT / "mds" / "data" / "conversation-eval.db"

RAW.parent.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_FILE}"      # before src.db.session builds its engine
os.environ["TURSO_DATABASE_URL"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from scripts.eval_generation import Grade  # noqa: E402
from src.api.main import app  # noqa: E402
from src.api.routers import chat as chat_router  # noqa: E402
from src.core import market_service  # noqa: E402
from src.core.config import DISCLAIMER, get_config  # noqa: E402
from src.core.llm import current_llm  # noqa: E402
from src.core.tracing import session_hash  # noqa: E402
from src.db import aliases  # noqa: E402
from src.db.session import init_db  # noqa: E402
from src.workflow import market_tools as MT  # noqa: E402

JUDGE_SYSTEM = """You grade answers from a multi-agent personal-finance assistant, turn by turn in a conversation. Be strict and literal.
You get: the CONVERSATION so far (only to understand what the question refers to), the QUESTION, the SOURCES (what the
assistant's agents found this turn: market data, articles, calculations, knowledge-base text), the assistant's ANSWER, a
REFERENCE answer and numbered KEY POINTS.

- claims: split the ANSWER into its individual factual claims (figures, dates, facts about companies, markets, rules). For each,
  supported = true only if the SOURCES state or directly imply it (the CONVERSATION does not count). Not claims: disclaimers,
  statements of what the assistant can or cannot do, offers to help, and saying information isn't available.
- relevance (1-5): how directly the ANSWER addresses the QUESTION as meant in the conversation (5 = fully on point, 1 = off-topic).
  A follow-up such as "which did better?" or "and at 5%?" refers to the subjects, figures and period just discussed. Declining
  scores 5 only if the reference says to decline.
- correctness (1-5): agreement of the ANSWER's facts with the REFERENCE (5 = all consistent, 3 = minor errors, 1 = wrong or
  contradicts it). Where the reference names figures without giving their values (live market data), the SOURCES hold the true
  values: a figure that differs from them, or belongs to the wrong period or subject, is an error. Missing information lowers
  completeness, not correctness, unless the answer declines a question the reference answers (then 1).
- key_points_covered: the numbers of the KEY POINTS the ANSWER states or clearly conveys.
- declined: true if the ANSWER refuses or says it can't answer instead of answering.
Give a one-sentence reason."""


# ---------------------------------------------------------------- running the conversations
_final: dict = {}


def _capturing(real):
    """Wraps the chat router's stream_chat so the eval sees the turn's final state (agent outputs, market data) for faithfulness."""
    def stream_chat(*args, **kwargs):
        for ev in real(*args, **kwargs):
            if ev["type"] == "final":
                _final["state"] = ev["state"]
            yield ev
    return stream_chat


def sources_of(state: dict) -> str:
    """What the synthesizer wrote from: each answered agent's output, then the market tools' exact figures."""
    blocks = [f"[{name}]\n{o.get('content', '')}" for name, o in (state.get("agent_outputs") or {}).items()
              if o.get("status") == "answered" and o.get("content")]
    if data := MT.data_block(state.get("market_data") or {}):
        blocks.append(f"[market data]\n{data}")
    return "\n\n".join(blocks) or "(none)"


def ask(client: TestClient, sid: str, q: str, view: dict | None) -> dict:
    """One turn through the streaming endpoint: the stored reply, the sources it was written from, node timings, wall time."""
    t0, nodes, message = time.monotonic(), [], None
    _final.clear()
    with client.stream("POST", f"/api/sessions/{sid}/chat/stream", json={"message": q, **({"view": view} if view else {})}) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            ev = json.loads(line)
            if ev["type"] == "node_end":
                nodes.append({k: ev.get(k) for k in ("node", "ms", "status", "detail")})
            elif ev["type"] == "done":
                message = ev["message"]
            elif ev["type"] == "error":
                message = {"content": ev["message"], "agents": [], "sources": [], "trace": ["stream error"], "choices": []}
    state = _final.get("state") or {}
    return {"message": message or {}, "nodes": nodes, "seconds": round(time.monotonic() - t0, 2),
            "sources": sources_of(state), "read_as": state.get("question")}


def grade(judge, history: list[tuple[str, str]], turn: dict, answer: str, sources: str) -> dict:
    """The four metrics for one answer (scoring rules as in scripts/eval_generation.py)."""
    points = turn["key_points"]
    convo = "\n".join(f"user: {q}\nassistant: {a[:1200]}" for q, a in history) or "(this is the first turn)"
    numbered = "\n".join(f"{i}. {p}" for i, p in enumerate(points, 1))
    answer = answer.replace(DISCLAIMER, "").strip()            # compliance's fixed line, not something the answer claims
    out = judge.invoke([("system", JUDGE_SYSTEM), ("human",
        f"CONVERSATION:\n{convo}\n\nQUESTION: {turn['q']}\n\nSOURCES:\n{sources}\n\nANSWER:\n{answer}\n\n"
        f"REFERENCE:\n{turn['reference']}\n\nKEY POINTS:\n{numbered}")])
    g: Grade = out["parsed"]
    covered = sorted({i for i in g.key_points_covered if 1 <= i <= len(points)})
    # The judge's `declined` also fires for answers that decline one part and answer the rest ("I can't say whether to buy,
    # but here are the facts"), so only a refusal that conveys none of the key points scores the floor.
    floor = g.declined and not turn.get("decline") and not covered
    claims = len(g.claims)
    usage = out["raw"].usage_metadata or {}
    relevance = 5 if turn.get("decline") and g.declined else 1 if floor else g.relevance   # declining was the right answer
    return {"relevance": relevance, "correctness": 1 if floor else g.correctness,
            "faithfulness": None if g.declined and not claims else round(sum(c.supported for c in g.claims) / claims, 3) if claims else 1.0,
            "completeness": 0.0 if floor else round(len(covered) / len(points), 3),
            "claims": claims, "unsupported": [c.claim for c in g.claims if not c.supported],
            "missed": [p for i, p in enumerate(points, 1) if i not in covered], "declined": g.declined, "reason": g.reason,
            "tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)}


def run_conversation(client: TestClient, judge, conv: dict) -> dict:
    sid = client.post("/api/sessions").json()["id"]
    if conv.get("profile"):
        client.put(f"/api/sessions/{sid}/profile", json=conv["profile"]).raise_for_status()
    if conv.get("holdings"):
        client.put(f"/api/sessions/{sid}/portfolio", json={"holdings": conv["holdings"]}).raise_for_status()
    turns, history = [], []
    for i, t in enumerate(conv["turns"], 1):
        got = ask(client, sid, t["q"], t.get("view"))
        m = got["message"]
        answer = m.get("content", "")
        scores = grade(judge, history, t, answer, got["sources"])
        history.append((t["q"], answer))
        turns.append({"n": i, "q": t["q"], "read_as": got["read_as"], "reference": t["reference"], "key_points": t["key_points"],
                      "answer": answer, "agents": m.get("agents") or [], "sources_given": got["sources"],
                      "choices": m.get("choices") or [], "trace": m.get("trace") or [], "nodes": got["nodes"],
                      "seconds": got["seconds"], **scores})
        f = scores["faithfulness"]
        print(f"  {conv['id']} #{i} {got['seconds']:5.1f}s  rel {scores['relevance']} faith {'n/a' if f is None else f'{f:.2f}'} "
              f"corr {scores['correctness']} compl {scores['completeness']:.2f}{'  ⚠' if flagged(turns[-1]) else ''}  {t['q']}", flush=True)
    return {"id": conv["id"], "title": conv.get("title", ""), "session": sid, "langfuse_session": session_hash(sid), "turns": turns}


# ---------------------------------------------------------------- report
def flagged(t: dict) -> bool:
    """A turn worth reading first: anything short of full marks on a metric."""
    return t["relevance"] < 5 or t["correctness"] < 5 or (t["faithfulness"] is not None and t["faithfulness"] < 1) or t["completeness"] < 1


def summary(turns: list[dict]) -> dict:
    mean = lambda k: round(statistics.mean(v), 2) if (v := [t[k] for t in turns if t[k] is not None]) else None  # noqa: E731
    return {"turns": len(turns), "relevance": mean("relevance"), "faithfulness": mean("faithfulness"), "correctness": mean("correctness"),
            "completeness": mean("completeness"), "fully_faithful": sum(t["faithfulness"] == 1.0 for t in turns),
            "faith_scored": sum(t["faithfulness"] is not None for t in turns), "flagged": sum(flagged(t) for t in turns),
            "median_s": round(statistics.median(t["seconds"] for t in turns), 1) if turns else 0.0,
            "max_s": max((t["seconds"] for t in turns), default=0.0)}


def _fmt(x, digits=2) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}" if isinstance(x, float) else str(x)


def _slowest(nodes: list[dict], n: int = 3) -> str:
    top = sorted((x for x in nodes if x.get("ms") is not None), key=lambda x: -x["ms"])[:n]
    return ", ".join(f"{x['node']} {x['ms'] / 1000:.1f}s" for x in top)


def report(convs: list[dict], started: str, model: str, judge_model: str) -> str:
    every = [t for c in convs for t in c["turns"]]
    a = summary(every)
    secs = sorted(t["seconds"] for t in every)
    lines = ["# Conversation eval", "",
             f"Run {started}: {len(convs)} conversations, {len(every)} turns, answered by `{model}`, graded by `{judge_model}`. Generated by "
             "`python -m scripts.eval_conversations` from `tests/data/conversation_eval.yaml`; raw output (sources given, node "
             "timings, judge reasons) in `mds/data/conversation-eval.json`.", "",
             "| Metric | Scale | Meaning |", "|---|---|---|",
             "| Relevance | 1-5 | Does the answer address the question, as meant in the conversation? |",
             "| Faithfulness | 0-1 | Share of the answer's claims supported by what the agents gave the synthesizer this turn (hallucination check); n/a for a decline |",
             "| Correctness | 1-5 | Agreement with the turn's reference (live figures: with the sources, right period and subject) |",
             "| Completeness | 0-1 | Share of the turn's key points covered |", "",
             "## Summary", "",
             f"**All {a['turns']} turns:** relevance **{_fmt(a['relevance'])}**, faithfulness **{_fmt(a['faithfulness'])}** "
             f"({a['fully_faithful']} of {a['faith_scored']} fully supported), correctness **{_fmt(a['correctness'])}**, "
             f"completeness **{_fmt(a['completeness'])}**. {a['flagged']} turns below full marks (⚠). "
             f"Latency per turn: median {a['median_s']}s, p90 {secs[round(0.9 * (len(secs) - 1))] if secs else 0:.1f}s, max {a['max_s']:.1f}s.", "",
             "| Conversation | Turns | Relevance | Faithfulness | Correctness | Completeness | ⚠ | Median s | Langfuse session |",
             "|---|---|---|---|---|---|---|---|---|"]
    for c in convs:
        s = summary(c["turns"])
        lines.append(f"| [{c['id']}](#{c['id']}) | {s['turns']} | {_fmt(s['relevance'])} | {_fmt(s['faithfulness'])} | "
                     f"{_fmt(s['correctness'])} | {_fmt(s['completeness'])} | {s['flagged']} | {s['median_s']} | `{c['langfuse_session']}` |")
    lines += ["", "### Turns below full marks", "", "| Turn | Rel | Faith | Corr | Compl | Judge's reason |", "|---|---|---|---|---|---|"]
    lines += [f"| {c['id']} #{t['n']}: {t['q']} | {t['relevance']} | {_fmt(t['faithfulness'])} | {t['correctness']} | "
              f"{_fmt(t['completeness'])} | {t['reason'].replace('|', '/')} |" for c in convs for t in c["turns"] if flagged(t)]
    for c in convs:
        lines += ["", f"## {c['id']}", "", f"_{c['title']}_", ""]
        for t in c["turns"]:
            lines += [f"### {t['n']}. {t['q']}{' ⚠' if flagged(t) else ''}", "",
                      f"**Relevance {t['relevance']}/5 · Faithfulness {_fmt(t['faithfulness'])} ({t['claims']} claims) · "
                      f"Correctness {t['correctness']}/5 · Completeness {_fmt(t['completeness'])}**", "",
                      f"- **Judge:** {t['reason']}",
                      f"- **Read as:** {t['read_as'] or '—'}",
                      f"- **Agents:** {', '.join(t['agents']) or '—'} · {t['seconds']:.1f}s (slowest: {_slowest(t['nodes']) or '—'})",
                      f"- **Reference:** {t['reference']}"]
            if t["missed"]:
                lines.append("- **Key points missed:** " + "; ".join(t["missed"]))
            if t["unsupported"]:
                lines.append("- **Unsupported claims:** " + "; ".join(f"“{x}”" for x in t["unsupported"]))
            lines += ["", "> " + t["answer"].replace("\n", "\n> "), ""]
            lines += ["<details><summary>Sources given to the synthesizer</summary>", "", "```", t["sources_given"], "```", "", "</details>", "",
                      "<details><summary>Trace</summary>", "", "```", *t["trace"], "```", "", "</details>", ""]
    return "\n".join(lines) + "\n"


def regrade(judge, judge_model: str, cases: dict) -> None:
    """Judge the saved answers again with the current judge prompt and the YAML's references, then rewrite every output."""
    run = json.loads(RAW.read_text())
    for c in run["conversations"]:
        if c["id"] not in cases:
            continue
        history = []
        for t, case in zip(c["turns"], cases[c["id"]]["turns"]):
            t.update(reference=case["reference"], key_points=case["key_points"],
                     **grade(judge, history, case, t["answer"], t["sources_given"]))
            history.append((t["q"], t["answer"]))
            print(f"  {c['id']} #{t['n']} rel {t['relevance']} faith {_fmt(t['faithfulness'])} corr {t['correctness']} "
                  f"compl {t['completeness']:.2f}{'  ⚠' if flagged(t) else ''}  {t['q']}", flush=True)
    run["judge"] = judge_model
    RAW.write_text(json.dumps(run, indent=1, default=str))
    OUT.write_text(report(run["conversations"], run["run"], run["model"], judge_model))
    write_page(run)
    a = summary([t for c in run["conversations"] for t in c["turns"]])
    print(f"\nrelevance {_fmt(a['relevance'])}  faithfulness {_fmt(a['faithfulness'])}  correctness {_fmt(a['correctness'])}  "
          f"completeness {_fmt(a['completeness'])}  ({a['flagged']} of {a['turns']} turns below full marks)")


def write_page(run: dict) -> None:
    """The HTML review page: the run's data embedded in scripts/conversation_eval_page.html."""
    data = json.dumps(run, default=str).replace("</", "<\\/")          # safe inside a <script> element
    PAGE.write_text(PAGE_TEMPLATE.read_text().replace("__TITLE__", PAGE_TITLE).replace("__DATA__", data))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=sorted(SETS), default="core", help="conversation set (default core)")
    ap.add_argument("--only", action="append", help="conversation id (repeatable)")
    ap.add_argument("--page-only", action="store_true", help="rebuild the HTML page from the saved JSON, without running anything")
    ap.add_argument("--regrade", action="store_true", help="judge the saved answers again, without running the chats")
    args = ap.parse_args()
    _use_set(args.set)
    if args.page_only:
        write_page(json.loads(RAW.read_text()))
        return print(f"wrote {PAGE.relative_to(ROOT)}")
    llm = current_llm()
    if llm is None:
        raise SystemExit("needs an LLM key")
    from langchain_openai import ChatOpenAI
    judge_model = get_config()["llm"]["models"]["openai"]
    judge = ChatOpenAI(model=judge_model, temperature=0).with_structured_output(Grade, include_raw=True)
    convs = [c for c in load_cases() if not args.only or c["id"] in args.only]
    if args.regrade:
        return regrade(judge, judge_model, {c["id"]: c for c in convs})
    init_db()
    market_service.alias_store = (aliases.get_alias, aliases.put_alias)
    chat_router.stream_chat = _capturing(chat_router.stream_chat)
    client = TestClient(app)                  # not as a context manager: no news/boards pollers, just the API
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    model = getattr(llm, "model_name", None) or getattr(llm, "model", None) or type(llm).__name__
    order = [c["id"] for c in load_cases()]
    kept = json.loads(RAW.read_text())["conversations"] if args.only and RAW.exists() else []   # --only replaces just those
    run = {"run": started, "model": model, "judge": judge_model, "conversations": []}
    done = {c["id"]: c for c in kept if c["id"] in order}
    for c in convs:
        print(f"{c['id']}: {c.get('title', '')}", flush=True)
        done[c["id"]] = {**run_conversation(client, judge, c), "ran_at": started}
        run["conversations"] = sorted(done.values(), key=lambda x: order.index(x["id"]))
        RAW.write_text(json.dumps(run, indent=1, default=str))             # kept as it goes, in case a later one fails
    results = run["conversations"]
    from src.core import tracing
    tracing.flush()
    OUT.write_text(report(results, started, model, judge_model))
    write_page(run)
    a = summary([t for c in results for t in c["turns"]])
    tokens = sum(t["tokens"] for c in results for t in c["turns"])
    print(f"\nrelevance {_fmt(a['relevance'])}  faithfulness {_fmt(a['faithfulness'])}  correctness {_fmt(a['correctness'])}  "
          f"completeness {_fmt(a['completeness'])}  ({a['flagged']} of {a['turns']} turns below full marks; judge {tokens:,} tokens)")
    print(f"wrote {OUT.relative_to(ROOT)}, {PAGE.relative_to(ROOT)} and {RAW.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
