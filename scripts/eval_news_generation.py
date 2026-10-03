"""News answer-quality evaluation: answer each question from its top-5 retrieved stories, then score the answer with an LLM judge.

  python -m scripts.eval_news_generation               # all questions, both variants (needs OPENAI_API_KEY; 2 LLM calls per question per variant)
  python -m scripts.eval_news_generation --limit 2     # quick check on the first 2 questions

Same method and metrics as scripts/eval_generation.py (the knowledge-base test), whose answer prompt, judge prompt, grade schema and
refusal detector are reused so the scores are comparable:
  relevance 1-5, faithfulness 0-1 (claims supported by the retrieved stories), correctness 1-5 (vs the reference), completeness 0-1 (key points covered).
Questions: tests/data/news_eval.yaml; true answers and key points: tests/data/news_eval_reference.yaml (questions without an entry are
skipped if answerable; out_of_scope and near_miss questions need none, the right answer is to decline).
Outputs: mds/data/news_eval_generation.csv (answers, scores, judge reasons), news_eval_generation_summary.csv, and the generation section of mds/news-eval.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
from pathlib import Path

import yaml
from qdrant_client import QdrantClient

from scripts.eval_generation import ANSWER_SYSTEM, JUDGE_SYSTEM, Grade, is_decline
from src.core.config import get_config
from src.rag import news

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "mds" / "data"
K = 5
VARIANTS = ("title+summary", "title only")
DECLINE_REFERENCE = ("Nothing in the available stories answers this question. The correct answer is to say that the sources don't "
                     "cover it, without guessing or using outside knowledge.")
DECLINE_POINTS = ["Says the sources don't cover the question"]


def context_block(hits: list[dict]) -> str:
    return "\n\n".join(f"[{i}] {h['publisher']}, {h['published'][:10]}: {h['title']}" + (f"\n{h['summary']}" if h["summary"] else "")
                       for i, h in enumerate(hits, 1))


KB_ALL = {"relevance": 4.91, "faithfulness": 0.98, "correctness": 4.90, "completeness": 0.96}      # kb-eval-summary.md, All (93), max 250


def write_report(rows: list[dict], summary: list[dict], usage: dict, model: str) -> None:
    """Fill the generation section of mds/news-eval.md (between its generation markers)."""
    A, B = summary
    n_in = A["questions"]
    f = lambda r, k: ("n/a" if r[k] == "" else f"{float(r[k]):.2f}" if k in ("faithfulness", "completeness") else f"{int(r[k])}")     # noqa: E731
    L = ["`python -m scripts.eval_news_generation`: for each question and variant, the top-5 stories go to `" + model + "` (the app's model, temperature 0) "
         "with the instruction to answer only from them (<= 150 words) or say they don't cover the question. The same model then judges the answer "
         "against the stories and the question's reference answer and key points ([news_eval_reference.yaml](../tests/data/news_eval_reference.yaml)). "
         "The prompts, grade schema and refusal detector are the knowledge-base test's (`scripts/eval_generation.py`), so the scores are comparable. "
         "Because the same model writes and judges, scores may be lenient.", "",
         "| Metric | Scale | Meaning |", "|---|---|---|",
         "| Relevance | 1-5 | Does the answer address the question asked? |",
         "| Faithfulness | 0-1 | Share of the answer's claims supported by the retrieved stories (hallucination check); not scored for refusals |",
         "| Correctness | 1-5 | Do the answer's facts agree with the reference answer? |",
         "| Completeness | 0-1 | Share of the reference key points covered; 0 for a refused answerable question |", "",
         "n32 and n33 are retrieval-only: their stories never name the winner, so a correct \"the summary doesn't say\" would be scored as a refusal. "
         "Raw results with every answer, unsupported claim and judge reason: [news_eval_generation.csv](data/news_eval_generation.csv), "
         "[news_eval_generation_summary.csv](data/news_eval_generation_summary.csv).", "",
         f"### Summary ({n_in} answerable questions)", "", "| | title+summary | title only | Reference: knowledge base, all 93 (max 250) |", "|---|---|---|---|",
         f"| Relevance (1-5) | **{A['relevance']:.2f}** | {B['relevance']:.2f} | {KB_ALL['relevance']:.2f} |",
         f"| Faithfulness (0-1) | **{A['faithfulness']:.2f}** | {B['faithfulness']:.2f} | {KB_ALL['faithfulness']:.2f} |",
         f"| Correctness (1-5) | **{A['correctness']:.2f}** | {B['correctness']:.2f} | {KB_ALL['correctness']:.2f} |",
         f"| Completeness (0-1) | **{A['completeness']:.2f}** | {B['completeness']:.2f} | {KB_ALL['completeness']:.2f} |",
         f"| Answers with every claim supported | {A['fully_faithful']} of {n_in} | {B['fully_faithful']} of {n_in} | |",
         f"| Answerable questions wrongly refused | {A['wrongly_declined']} | {B['wrongly_declined']} | 1 |",
         f"| Out-of-scope questions refused | {A['out_of_scope_declined']} of {A['out_of_scope']} | {B['out_of_scope_declined']} of {B['out_of_scope']} | 6 of 6 |",
         f"| Near-miss questions refused | {A['near_miss_declined']} of {A['near_miss']} | {B['near_miss_declined']} of {B['near_miss']} | |", "",
         "The knowledge-base column is a different question set, shown for scale only. Faithfulness is averaged over answered questions only.", "",
         "### Per question (relevance 1-5 / faithfulness 0-1 / correctness 1-5 / completeness 0-1)", "",
         "A refused answerable question scores 1 / n/a / 1 / 0.00. Bold marks the better variant by completeness, then correctness.", "",
         "| id | Question | title+summary | title only |", "|---|---|---|---|"]
    by = {(r["variant"], r["id"]): r for r in rows}
    for r in (r for r in rows if r["variant"] == VARIANTS[0] and r["in_scope"]):
        a, b = r, by[(VARIANTS[1], r["id"])]
        key = lambda x: (float(x["completeness"]), int(x["correctness"]))                                    # noqa: E731
        cell = lambda x, win: ("**" if win else "") + f"{f(x, 'relevance')} / {f(x, 'faithfulness')} / {f(x, 'correctness')} / {f(x, 'completeness')}" \
            + (" refused" if x["declined"] else "") + ("**" if win else "")                                      # noqa: E731
        L.append(f"| {r['id']} | {r['question']} | {cell(a, key(a) > key(b))} | {cell(b, key(b) > key(a))} |")
    L += ["", "### Unrelated and unanswerable questions: did the answer decline?", "",
          "No story answers these, so the right result is a decline. **Unrelated** = out of scope, not about finance (o01-o06). "
          "**Unanswerable** = near-miss, a finance question on a topic the stories don't cover (m01-m05), which is the harder case because "
          "retrieval still returns related stories.", "",
          "| id | Kind | Question | title+summary | title only |", "|---|---|---|---|---|"]
    for r in (r for r in rows if r["variant"] == VARIANTS[0] and not r["in_scope"]):
        b = by[(VARIANTS[1], r["id"])]
        L.append(f"| {r['id']} | {'unrelated' if r['kind'] == 'out_of_scope' else 'unanswerable'} | {r['question']} | {'declined' if r['declined'] else '**answered**'} | {'declined' if b['declined'] else '**answered**'} |")
    L += ["", f"Judge and answer calls used {usage['input']:,} input and {usage['output']:,} output tokens ({model}).", ""]
    path = ROOT / "mds" / "news-eval.md"
    text = path.read_text()
    a, b = "<!-- generation:start -->", "<!-- generation:end -->"
    path.write_text(text.split(a, 1)[0] + a + "\n" + "\n".join(L) + "\n" + b + text.split(b, 1)[1])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="only the first N questions (quick check)")
    args = ap.parse_args()

    from langchain_openai import ChatOpenAI
    model = get_config()["llm"]["models"]["openai"]
    answerer = ChatOpenAI(model=model, temperature=0)
    judge = ChatOpenAI(model=model, temperature=0).with_structured_output(Grade, include_raw=True)

    stories = json.loads((ROOT / "tests/data/news_snapshot.json").read_text())["stories"]
    refs = yaml.safe_load((ROOT / "tests/data/news_eval_reference.yaml").read_text())
    questions = [q for q in yaml.safe_load((ROOT / "tests/data/news_eval.yaml").read_text())
                 if q["id"] in refs or q.get("kind", "answerable") != "answerable"][:args.limit]
    get_config()["news_index"]["retention_days"] = 100_000            # frozen sample: keep every story whatever its age

    rows, usage = [], {"input": 0, "output": 0}
    for variant in VARIANTS:
        client = QdrantClient(":memory:")
        news._ready = False
        news.ingest("MARKET", [{"id": s["id"], "title": s["title"], "summary": s["summary"] if variant == "title+summary" else "",
                                "publisher": s["publisher"], "url": s["url"], "published": s["published"]} for s in stories], client=client)
        for q in questions:
            in_scope = bool(q["expect"])
            reference, key_points = (refs[q["id"]]["reference"], refs[q["id"]]["key_points"]) if in_scope else (DECLINE_REFERENCE, DECLINE_POINTS)
            hits = news.search(client, q["q"], days=100_000, k=K)
            ctx = context_block(hits)
            reply = answerer.invoke([("system", ANSWER_SYSTEM), ("human", f"SOURCES:\n{ctx}\n\nQUESTION: {q['q']}")])
            answer = reply.content.strip()
            points = "\n".join(f"{i}. {p}" for i, p in enumerate(key_points, 1))
            out = judge.invoke([("system", JUDGE_SYSTEM), ("human",
                f"QUESTION: {q['q']}\n\nSOURCES:\n{ctx}\n\nANSWER:\n{answer}\n\nREFERENCE:\n{reference}\n\nKEY POINTS:\n{points}")])
            g: Grade = out["parsed"]
            for msg in (reply, out["raw"]):
                usage["input"] += (msg.usage_metadata or {}).get("input_tokens", 0)
                usage["output"] += (msg.usage_metadata or {}).get("output_tokens", 0)
            covered = {i for i in g.key_points_covered if 1 <= i <= len(key_points)}
            declined = is_decline(answer)
            claims = len(g.claims)
            rows.append({
                "variant": variant, "id": q["id"], "kind": q.get("kind", "answerable"), "in_scope": in_scope, "question": q["q"],
                # a refused answerable question scores the floor, whatever the judge said (as in the knowledge-base test)
                "relevance": 1 if declined and in_scope else g.relevance,
                "correctness": 1 if declined and in_scope else g.correctness,
                "faithfulness": "" if declined else round(sum(c.supported for c in g.claims) / claims, 3) if claims else 1.0,
                "completeness": 0.0 if declined and in_scope else round(len(covered) / len(key_points), 3),
                "claims": claims, "unsupported_claims": json.dumps([c.claim for c in g.claims if not c.supported]),
                "declined": declined, "reason": g.reason, "answer": answer})
            print(f"  {variant} {q['id']}: rel {g.relevance} faith {rows[-1]['faithfulness'] or 'n/a'} "
                  f"corr {g.correctness} compl {rows[-1]['completeness']:.2f}{'  declined' if declined else ''}")

    summary = []
    for variant in VARIANTS:
        v = [r for r in rows if r["variant"] == variant]
        ins = [r for r in v if r["in_scope"]]
        mean = lambda key, rs: round(st.mean(r[key] for r in rs if r[key] != ""), 3) if any(r[key] != "" for r in rs) else ""   # noqa: E731
        summary.append({"variant": variant, "questions": len(ins), "relevance": mean("relevance", ins), "faithfulness": mean("faithfulness", ins),
                        "correctness": mean("correctness", ins), "completeness": mean("completeness", ins),
                        "fully_faithful": sum(r["faithfulness"] == 1.0 for r in ins), "wrongly_declined": sum(r["declined"] for r in ins),
                        "out_of_scope": sum(r["kind"] == "out_of_scope" for r in v),
                        "out_of_scope_declined": sum(r["declined"] for r in v if r["kind"] == "out_of_scope"),
                        "near_miss": sum(r["kind"] == "near_miss" for r in v),
                        "near_miss_declined": sum(r["declined"] for r in v if r["kind"] == "near_miss")})

    suffix = "_partial" if args.limit else ""
    for path, data in ((OUT_DIR / f"news_eval_generation{suffix}.csv", rows), (OUT_DIR / f"news_eval_generation_summary{suffix}.csv", summary)):
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, data[0].keys())
            w.writeheader()
            w.writerows(data)
    if not args.limit:
        write_report(rows, summary, usage, model)
    for s in summary:
        print(s)
    print(f"tokens used: {usage['input']:,} input, {usage['output']:,} output ({model})")


if __name__ == "__main__":
    main()
