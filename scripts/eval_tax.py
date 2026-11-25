"""Tax agent eval: each case in tests/data/tax_eval.yaml (a single question or a chain of messages) is replayed through the
real workflow with the real LLM, carrying the conversation's memory between messages the way the chat endpoint does
(history + the last answer's context). After every message, what the tax agent understood and worked out is compared with
the expected answer: who answered, the filing status, how each amount was sorted, the household, the income tax and
federal total (within $1), the question it asked, and phrases the reply must contain.

  python -m scripts.eval_tax              # all cases, writes mds/tax-eval.md
  python -m scripts.eval_tax --only c01   # one case, printed only

Needs an LLM key (the model in config.yaml). About 4-8 LLM calls per message. Expected inputs are set by hand for each
case; the expected totals were worked out from them by hand or with the hand-tested estimator (tests/test_income_tax.py).
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import yaml

from src.core import income_tax as T
from src.core.config import get_config
from src.core.llm import current_llm
from src.workflow import tax_calc as TC
from src.workflow.graph import run_chat

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "tests" / "data" / "tax_eval.yaml"
OUT = ROOT / "mds" / "tax-eval.md"
PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate", "horizon_years": 10}
TOLERANCE = 1.0


def _profile_totals(prof: dict | None) -> tuple[float | None, float | None]:
    """(income tax, federal total) of the estimate carried in the answer's context."""
    if not prof:
        return None, None
    return prof.get("income_tax"), prof.get("total_federal")


def _asked(state: dict, prof: dict | None) -> str:
    """Which question the reply asked: a QUESTIONS key, "amount" (a missing amount), or "none"."""
    choices = state.get("choices") or []
    for key, (_, buttons) in TC.QUESTIONS.items():
        if choices == buttons:
            return key
    if prof and prof.get("pending") and (state.get("agent_outputs") or {}).get("tax", {}).get("status") == "need_info":
        return "amount"
    return "none"


def check_turn(state: dict, want: dict) -> list[str]:
    """What doesn't match the expected answer for one message (empty: it passes)."""
    problems = []
    prof = (state.get("context") or {}).get("tax")
    agents = state.get("agents") or []
    if want.get("tax_only") and agents != ["Tax Education"]:
        problems.append(f"answered by {agents}, expected the Tax agent only")
    if "filing_status" in want and (prof or {}).get("filing_status") != want["filing_status"]:
        problems.append(f"filing status {(prof or {}).get('filing_status')!r}, expected {want['filing_status']!r}")
    if "figures" in want:
        got = {round(i["amount"]): i["kind"] for i in (prof or {}).get("items") or []}
        for amount, kind in want["figures"].items():
            kinds = kind if isinstance(kind, list) else [kind]
            if got.get(round(float(amount))) not in kinds:
                problems.append(f"{amount:,} sorted as {got.get(round(float(amount)))!r}, expected {' or '.join(kinds)}")
        if extra := sorted(set(got) - {round(float(a)) for a in want["figures"]}):
            problems.append(f"unexpected amounts {extra}")
    if "household" in want:
        got_house = {k: v for k, v in ((prof or {}).get("household") or {}).items() if v}
        if got_house != want["household"]:
            problems.append(f"household {got_house}, expected {want['household']}")
    income_tax, total = _profile_totals(prof)
    for key, value in (("income_tax", income_tax), ("total_federal", total)):
        if key in want:
            exp = want[key]
            options = exp if isinstance(exp, list) else [exp]
            if not any(o is None and value is None or o is not None and value is not None and abs(value - o) <= TOLERANCE
                       for o in options):
                problems.append(f"{key} {value if value is None else round(value, 2)}, expected {exp}")
    if "asks" in want:
        asked = _asked(state, prof)
        allowed = want["asks"] if isinstance(want["asks"], list) else [want["asks"]]
        if asked not in allowed:
            problems.append(f"asked {asked!r}, expected {' or '.join(allowed)}")
    text = state.get("final_response") or ""
    for phrase in want.get("contains") or []:
        if phrase not in text:
            problems.append(f"reply lacks {phrase!r}")
    return problems


def evaluate(case: dict) -> dict:
    history, context, turns = [], None, []
    for i, msg in enumerate(case["messages"]):
        state = run_chat(msg, history=history[-get_config()["workflow"]["history_turns"]:], profile=PROFILE, holdings=[],
                         db=None, context=context)
        want = (case.get("expect") or [{}])[i] if i < len(case.get("expect") or []) else {}
        problems = check_turn(state, want) if want else []
        prof = (state.get("context") or {}).get("tax")
        turns.append({"message": msg, "problems": problems, "income_tax": _profile_totals(prof)[0],
                      "total": _profile_totals(prof)[1], "asked": _asked(state, prof), "agents": state.get("agents"),
                      "trace": [t for t in state.get("trace", []) if t.startswith(("router", "tax"))]})
        history += [{"role": "user", "content": msg}, {"role": "assistant", "content": state.get("final_response") or ""}]
        context = state.get("context")
    return {"id": case["id"], "about": case["about"], "kind": "chain" if len(case["messages"]) > 1 else "single",
            "turns": turns, "passed": all(not t["problems"] for t in turns)}


def _money(x) -> str:
    return "—" if x is None else f"${x:,.0f}"


def report(results: list[dict]) -> str:
    n, ok = len(results), sum(r["passed"] for r in results)
    msgs = sum(len(r["turns"]) for r in results)
    msgs_ok = sum(not t["problems"] for r in results for t in r["turns"])
    cfg = get_config()["llm"]
    lines = [
        "# Tax agent eval", "",
        f"`python -m scripts.eval_tax` on {date.today().isoformat()}: **{ok}/{n} cases passed** ({msgs_ok}/{msgs} messages). "
        f"Provider `{cfg.get('provider')}`; models {', '.join(f'{k}: {v}' for k, v in (cfg.get('models') or {}).items())}. "
        "Cases: [tests/data/tax_eval.yaml](../tests/data/tax_eval.yaml); design: [agent-tax-agent.md](agent-tax-agent.md).",
        "",
        "Each case is replayed through the real workflow with the real model, the conversation's memory carried between "
        "messages as in the app. After every message the check compares who answered, the filing status, how each amount "
        "was sorted, the household, the income tax and federal total (within $1), the question asked and required phrases. "
        "Expected inputs are set by hand; the totals come from them by hand or with the hand-tested estimator. The model "
        "varies between runs, so a case can pass one run and fail the next: a failure is a lead to look at.", "",
        "| Id | Kind | Case | Result | Income tax | Federal total | Asked | Problems |", "|---|---|---|---|---|---|---|---|"]
    for r in results:
        last = r["turns"][-1]
        probs = " / ".join(f"msg {i + 1}: {p}" for i, t in enumerate(r["turns"]) for p in t["problems"]) or ""
        lines.append(f"| {r['id']} | {r['kind']} ({len(r['turns'])}) | {r['about']} | {'pass' if r['passed'] else '**fail**'} | "
                     f"{_money(last['income_tax'])} | {_money(last['total'])} | {last['asked']} | {probs} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", help="case ids to run (printed only, the report isn't rewritten)")
    args = ap.parse_args()
    if current_llm() is None:
        raise SystemExit("needs an LLM key (see config.yaml llm.provider)")
    cases = yaml.safe_load(open(CASES))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]
    results = []
    for case in cases:
        r = evaluate(case)
        results.append(r)
        print(f"{r['id']} {'PASS' if r['passed'] else 'FAIL'}: {r['about']}")
        for i, t in enumerate(r["turns"], 1):
            print(f"   {i}. income tax {_money(t['income_tax'])}, total {_money(t['total'])}, asked {t['asked']}, {t['agents']}")
            for p in t["problems"]:
                print(f"      ✗ {p}")
            if t["problems"]:
                print("      " + " | ".join(t["trace"])[:600])
    print(f"{sum(r['passed'] for r in results)}/{len(results)} passed")
    if not args.only:
        OUT.write_text(report(results))
        print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
