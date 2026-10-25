"""Calculator eval: each question in tests/data/calc_eval.yaml goes through the LLM's plan (with its one repair round)
and Python's execution, as in the calc node; a question passes when every expected group matches some step result.

  python -m scripts.eval_calc              # all questions, writes mds/calc-eval.md
  python -m scripts.eval_calc --only c10   # one question, printed only (failing steps are always printed)

Needs an LLM key (the model in config.yaml); Wolfram|Alpha is used for solve steps when its key is set. One or two LLM
calls per question.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import yaml

from src.core import calc_plan as PLAN
from src.core.config import get_config
from src.core.llm import current_llm
from src.workflow import calc_pipeline as CP
from src.workflow.nodes import calculate

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "tests" / "data" / "calc_eval.yaml"
OUT = ROOT / "mds" / "calc-eval.md"
TOLERANCE = 0.005


def _matches(expected: float, values: list[float]) -> bool:
    return any(abs(v - expected) <= TOLERANCE * max(1.0, abs(expected)) or
               abs(v * 100 - expected) <= TOLERANCE * max(1.0, abs(expected)) for v in values)


def evaluate(case: dict) -> dict:
    q = case["q"]
    out = calculate(q, f"Recent conversation:\n(none)\n\nMessage: {q}", q)
    result = out.result if out.kind == "answer" else None
    route = ("plan path on sourced equations" if result is not None and result.get("model_note") == CP.BUILT_ON_NOTE else
             "plan path" if result is not None and result.get("model_note") else
             "sourced: " + ", ".join(sorted({x["status"] for x in result["quotes"]})) if result and result.get("quotes")
             else "arithmetic" if result is not None else out.kind)
    row = {"id": case["id"], "q": q, "route": route, "errors": out.errors, "trace": out.trace,
           "repaired": bool(out.errors) and result is not None}
    if case.get("status") == "need_info":
        row.update(ok=out.kind == "needs", got="asked" if out.kind in ("needs", "ask") else "answered")
        return row
    if result is None:
        row.update(ok=False, got={"needs": "asked for numbers", "ask": "asked"}.get(out.kind, out.kind))
        return row
    values = [v for k, v in result["values"].items() if k not in result["inputs"] and v is not None]
    for d in result["details"].values():
        rows = d.get("rows") or []
        if rows and isinstance(rows[0][0], float):
            values += [v for _, r in rows if isinstance(r, dict) for v in r.values() if isinstance(v, (int, float))]
    missing = [g for g in case.get("expect", []) if not any(_matches(x, values) for x in g)]
    shown = "; ".join(f"{s['name']} = {result['values'][s['name']]:.6g}" for s in result["steps"]
                      if result["values"].get(s["name"]) is not None)
    samples = [k for k, i in result["inputs"].items() if i["from"] == "sample"]
    row.update(ok=not missing, got=shown + (f" (samples: {', '.join(samples)})" if samples else ""), missing=missing)
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--verbose", action="store_true", help="print every plan, not only the failing ones")
    args = ap.parse_args()
    if current_llm() is None:
        raise SystemExit("needs an LLM key")
    cases = [c for c in yaml.safe_load(CASES.read_text()) if not args.only or c["id"] == args.only]
    rows = []
    for c in cases:
        r = evaluate(c)
        rows.append(r)
        print(f"{r['id']} {'PASS' if r['ok'] else 'FAIL'} [{r['route']}]{' (repaired)' if r['repaired'] else ''}: "
              f"{r['got']}" + (f"  errors: {r['errors']}" if r["errors"] else ""))
        if not r["ok"] or args.verbose:
            print("   steps:", " | ".join(r["trace"])[:3000])
    passed = sum(r["ok"] for r in rows)
    print(f"{passed}/{len(rows)} passed, {sum(r['repaired'] for r in rows)} after a repair")
    if args.only:
        return
    cfg = get_config()["llm"]
    model = ", ".join(f"{k}: {v}" for k, v in cfg.get("models", {}).items())
    lines = ["# Calculator eval", "",
             f"`python -m scripts.eval_calc` on {date.today().isoformat()}: {passed}/{len(rows)} passed, "
             f"{sum(r['repaired'] for r in rows)} of them after the repair round. Provider `auto` (first key set); "
             f"models {model}. Questions and references: [tests/data/calc_eval.yaml](../tests/data/calc_eval.yaml); "
             "design: [calc-pipeline-design.md](calc-pipeline-design.md) and [calc-plan-design.md](calc-plan-design.md). Route: "
             "sourced (equation from the knowledge base and the web, cross-checked) or plan path (Finnie's own model).", "",
             "| Id | Question | Result | Route | Results | Rejections |", "|---|---|---|---|---|---|"]
    for r in rows:
        res = ("pass" if r["ok"] else "**fail**") + (" (repaired)" if r["repaired"] else "")
        errs = " / ".join(e.replace("|", "\\|") for e in r["errors"])
        lines.append(f"| {r['id']} | {r['q'][:90]}{'…' if len(r['q']) > 90 else ''} | {res} | {r['route']} | "
                     f"{r['got'].replace('|', '\\|')} | {errs} |")
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
