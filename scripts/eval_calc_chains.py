"""Calculator chain eval: each conversation in tests/data/calc_chain_eval.yaml (three messages, each follow-up changing or
building on the one before) is replayed through the real workflow with the real LLM, carrying the conversation's memory
between messages the way the chat endpoint does (history + the last answer's context). After every message the reply's
numbers are compared with the reference answers worked out in Python: every expected group must match a number in the
reply within 0.5% (a rate as a decimal or a percentage; a count within 0.5).

  python -m scripts.eval_calc_chains              # all chains, writes mds/calc-chain-eval.md
  python -m scripts.eval_calc_chains --only c01   # some chains, printed only
  python -m scripts.eval_calc_chains --workers 4  # chains run in parallel (each chain's messages stay in order)

Needs an LLM key (the model in config.yaml); Tavily is used when TAVILY_API_KEY is set. Roughly 5-15 LLM calls per message.
The model varies between runs, so a chain can pass one run and fail the next: a failure is a lead to look at.
"""
from __future__ import annotations

import argparse
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import yaml

from src.core.config import get_config
from src.core.llm import current_llm
from src.workflow.graph import run_chat

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "tests" / "data" / "calc_chain_eval.yaml"
OUT = ROOT / "mds" / "calc-chain-eval.md"
PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate", "horizon_years": 10}
REL = 0.005                                   # 0.5%
NUMBER = re.compile(r"(?<![\w.])-?\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)")


def reply_numbers(text: str) -> list[float]:
    """Every number written in the reply ("$1,229,796.08", "5.12%", "290 months"), minus signs ignored."""
    return [float(m[1].replace(",", "")) for m in NUMBER.finditer(text.replace("−", "-"))]


def matches(want: float, got: float) -> bool:
    if abs(want) < 1:                                  # a rate given as a decimal: also accept it as a percentage
        return abs(got - want) <= max(REL * abs(want), 5e-4) or abs(got - want * 100) <= max(REL * abs(want * 100), 0.01)
    if float(want).is_integer() and abs(want) < 1000:   # a count (months, years, payments)
        return abs(got - want) <= 0.5
    return abs(got - want) <= REL * abs(want)


def check(text: str, groups: list[list[float]]) -> list[str]:
    """Which expected groups the reply doesn't contain."""
    nums = reply_numbers(text)
    return [f"no {' or '.join(f'{v:,.2f}'.rstrip('0').rstrip('.') for v in g)}" for g in groups
            if not any(matches(w, n) for w in g for n in nums)]


def _answered_by(state: dict) -> str:
    agents = state.get("agents") or []
    out = (state.get("agent_outputs") or {}).get("calc") or {}
    return ", ".join(agents) + (f" ({out.get('status')})" if out.get("status") and out.get("status") != "answered" else "")


def evaluate(case: dict) -> dict:
    history, context, turns = [], None, []
    for msg, groups in zip(case["messages"], case["expect"]):
        try:
            state = run_chat(msg, history=history[-get_config()["workflow"]["history_turns"]:], profile=PROFILE,
                             holdings=[], db=None, context=context)
        except Exception as e:  # noqa: BLE001 — a crash is a failed message, the chain goes on
            state = {"final_response": "", "agents": [], "trace": [f"crashed: {e!r}"]}
        text = state.get("final_response") or ""
        problems = check(text, groups)
        route = next((t for t in reversed(state.get("trace") or []) if t.startswith("calc (")), "")
        turns.append({"message": msg, "problems": problems, "by": _answered_by(state),
                      "route": route.split(":")[0].removeprefix("calc (").rstrip(")") if route else "",
                      "trace": [t for t in state.get("trace", []) if t.startswith(("proofread", "router", "calc ", "replan"))]})
        history += [{"role": "user", "content": msg}, {"role": "assistant", "content": text}]
        context = state.get("context")
    return {"id": case["id"], "about": case["about"], "turns": turns, "passed": all(not t["problems"] for t in turns)}


def report(results: list[dict]) -> str:
    n, ok = len(results), sum(r["passed"] for r in results)
    msgs = sum(len(r["turns"]) for r in results)
    msgs_ok = sum(not t["problems"] for r in results for t in r["turns"])
    by_pos = [sum(not r["turns"][i]["problems"] for r in results) for i in range(3)]
    cfg = get_config()["llm"]
    lines = [
        "# Calculator chain eval", "",
        f"`python -m scripts.eval_calc_chains` on {date.today().isoformat()}: **{ok}/{n} chains passed**, {msgs_ok}/{msgs} "
        f"messages (first message {by_pos[0]}/{n}, first follow-up {by_pos[1]}/{n}, second follow-up {by_pos[2]}/{n}). "
        f"Provider `{cfg.get('provider')}`; models {', '.join(f'{k}: {v}' for k, v in (cfg.get('models') or {}).items())}. "
        "Chains: [tests/data/calc_chain_eval.yaml](../tests/data/calc_chain_eval.yaml); single questions: "
        "[calc-eval.md](calc-eval.md); design: [calc-pipeline-design.md](calc-pipeline-design.md).", "",
        "Each chain is three messages replayed through the real workflow with the real model, the conversation's memory "
        "carried between messages as in the app. A message passes when its reply contains every expected figure (within "
        "0.5%); the references were worked out in Python from the standard formulas. The model varies between runs, so a "
        "chain can pass one run and fail the next: a failure is a lead to look at.", "",
        "| Id | Chain | Result | Msg 1 | Msg 2 | Msg 3 |", "|---|---|---|---|---|---|"]

    def cell(t: dict) -> str:
        head = "ok" if not t["problems"] else "**" + "; ".join(t["problems"]) + "**"
        return f"{head} ({t['by'] or 'no agent'}{', ' + t['route'] if t['route'] else ''})".replace("|", "\\|")

    for r in results:
        lines.append(f"| {r['id']} | {r['about']} | {'pass' if r['passed'] else '**fail**'} | "
                     + " | ".join(cell(t) for t in r["turns"]) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", help="chain ids to run (printed only, the report isn't rewritten)")
    ap.add_argument("--workers", type=int, default=4, help="chains run at the same time (default 4)")
    args = ap.parse_args()
    if current_llm() is None:
        raise SystemExit("needs an LLM key (see config.yaml llm.provider)")
    cases = yaml.safe_load(open(CASES))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(evaluate, cases))
    for r in results:
        print(f"{r['id']} {'PASS' if r['passed'] else 'FAIL'}: {r['about']}")
        for i, t in enumerate(r["turns"], 1):
            print(f"   {i}. {'ok' if not t['problems'] else '; '.join(t['problems'])} [{t['by']}; {t['route']}]")
            if t["problems"]:                          # why: the routing and every rejection, not the whole trace
                why = [x for x in t["trace"] if x.startswith(("router", "replan")) or re.search(r"rejected|plan path|→ ask|no usable", x)]
                for x in why:
                    print("      " + x[:400])
    print(f"{sum(r['passed'] for r in results)}/{len(results)} chains passed, "
          f"{sum(not t['problems'] for r in results for t in r['turns'])}/{sum(len(r['turns']) for r in results)} messages")
    if not args.only:
        OUT.write_text(report(results))
        print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
