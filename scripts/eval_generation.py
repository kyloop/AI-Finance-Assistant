"""Generation evaluation: answer each question from its top-5 retrieved chunks, then score the answer with an LLM judge.

  python -m scripts.eval_retrieval  --category bonds      # first: builds the eval_<category>_max<N> collections
  python -m scripts.eval_generation --category bonds      # then: answers + judges for max 512 and max 250
  python -m scripts.eval_generation --category bonds --limit 2          # quick check on the first 2 questions

Metrics (per answer):
  relevance     1-5  does the answer address the question that was asked?
  faithfulness  0-1  share of the answer's claims supported by the retrieved chunks (the hallucination check);
                     blank when the answer declines, since a decline makes no factual claims (declines are counted separately)
  correctness   1-5  do the answer's facts agree with the reference answer (no contradictions or wrong figures)?
  completeness  0-1  share of the reference key points the answer covers
Out-of-scope questions have a reference that says the answer should decline; `declined` records whether it did.

Inputs:  tests/data/retrieval_eval_<category>.yaml (questions, reference, key_points), the eval Qdrant collections.
Outputs: mds/data/eval_<category>_generation.csv (answers, scores, judge reasons), eval_<category>_generation_summary.csv.
Needs OPENAI_API_KEY; each run makes 2 LLM calls per question per variant.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics as st
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient

from src.core.config import get_config
from src.rag.store import search

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "mds" / "data"
QDRANT_PATH = ROOT / "src" / "data" / "qdrant_eval"
K = 5

ANSWER_SYSTEM = """You are Finnie, a personal-finance education assistant for beginners.
Answer the question using ONLY the numbered sources below. Do not use outside knowledge.
If the sources don't contain the answer, say that the sources don't cover it and stop; don't guess.
Be clear and concise (at most 150 words). Don't give personal buy/sell recommendations."""

JUDGE_SYSTEM = """You grade answers from a retrieval-augmented finance assistant. Be strict and literal.
You get: the question, the retrieved SOURCES the assistant was given, the assistant's ANSWER, a REFERENCE answer and
numbered KEY POINTS.

- claims: split the ANSWER into its individual factual claims. For each, supported = true only if the SOURCES state or
  directly imply it. A statement that the sources don't cover the question is not a claim. Ignore disclaimers.
- relevance (1-5): how directly the ANSWER addresses the question (5 = fully on point, 1 = off-topic). An honest "the
  sources don't cover this" scores 5 only if the reference says the question is out of scope.
- correctness (1-5): agreement of the ANSWER's facts with the REFERENCE (5 = all consistent, 3 = minor errors,
  1 = wrong or contradicts it). Missing information lowers completeness, not correctness, unless the answer declines
  a question the reference answers (then 1).
- key_points_covered: the numbers of the KEY POINTS the ANSWER states or clearly conveys.
- declined: true if the ANSWER says the sources don't cover the question instead of answering it.
Give a one-sentence reason."""


# The answer prompt tells the model to say the sources don't cover a question; detect that from the text, because the
# judge's own `declined` flag proved inconsistent (identical declines labelled differently).
DECLINE = re.compile(r"sources?\b[^.]{0,40}\b(do not|don't|does not|doesn't)\s+(cover|address|provide|contain|include)", re.I)


def is_decline(answer: str) -> bool:
    return bool(DECLINE.search(answer)) and len(answer.split()) < 60


class Claim(BaseModel):
    claim: str
    supported: bool


class Grade(BaseModel):
    claims: list[Claim] = Field(description="factual claims in the answer, each checked against the sources")
    relevance: int = Field(ge=1, le=5)
    correctness: int = Field(ge=1, le=5)
    key_points_covered: list[int]
    declined: bool
    reason: str


def context_block(hits: list[dict]) -> str:
    return "\n\n".join(f"[{i}] {h['doc_title']} > {h['section']}\n{h['text']}" for i, h in enumerate(hits, 1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--category", default="basics")
    ap.add_argument("--max-tokens", type=int, nargs="+", default=[512, 250])
    ap.add_argument("--limit", type=int, help="only the first N questions (quick check)")
    args = ap.parse_args()

    from langchain_openai import ChatOpenAI
    model = get_config()["llm"]["models"]["openai"]
    answerer = ChatOpenAI(model=model, temperature=0)
    judge = ChatOpenAI(model=model, temperature=0).with_structured_output(Grade, include_raw=True)

    questions = yaml.safe_load(open(ROOT / "tests" / "data" / f"retrieval_eval_{args.category}.yaml"))[:args.limit]
    client = QdrantClient(path=str(QDRANT_PATH))
    rows, usage = [], {"input": 0, "output": 0}
    for mx in args.max_tokens:
        name = f"eval_{args.category}_max{mx}"
        if not client.collection_exists(name):
            raise SystemExit(f"collection {name} missing: run python -m scripts.eval_retrieval --category {args.category}")
        for q in questions:
            hits = search(client, name, q["q"], k=K, category=args.category)
            ctx = context_block(hits)
            reply = answerer.invoke([("system", ANSWER_SYSTEM), ("human", f"SOURCES:\n{ctx}\n\nQUESTION: {q['q']}")])
            answer = reply.content.strip()
            points = "\n".join(f"{i}. {p}" for i, p in enumerate(q["key_points"], 1))
            out = judge.invoke([("system", JUDGE_SYSTEM), ("human",
                f"QUESTION: {q['q']}\n\nSOURCES:\n{ctx}\n\nANSWER:\n{answer}\n\nREFERENCE:\n{q['reference']}\n\nKEY POINTS:\n{points}")])
            g: Grade = out["parsed"]
            for msg in (reply, out["raw"]):
                usage["input"] += (msg.usage_metadata or {}).get("input_tokens", 0)
                usage["output"] += (msg.usage_metadata or {}).get("output_tokens", 0)
            covered = {i for i in g.key_points_covered if 1 <= i <= len(q["key_points"])}
            declined = is_decline(answer)
            claims = len(g.claims)
            rows.append({
                "variant": f"max{mx}", "id": q["id"], "band": q["band"], "in_scope": bool(q["expect"]), "question": q["q"],
                # a refused answerable question scores the floor, whatever the judge said (its scores for refusals varied)
                "relevance": 1 if declined and q["expect"] else g.relevance,
                "correctness": 1 if declined and q["expect"] else g.correctness,
                "faithfulness": "" if declined else round(sum(c.supported for c in g.claims) / claims, 3) if claims else 1.0,
                # a refused in-scope question covers nothing, whatever the judge matched (it can echo the question's words)
                "completeness": 0.0 if declined and q["expect"] else round(len(covered) / len(q["key_points"]), 3),
                "claims": claims, "unsupported_claims": json.dumps([c.claim for c in g.claims if not c.supported]),
                "declined": declined, "reason": g.reason, "answer": answer})
            print(f"  {rows[-1]['variant']} {q['id']}: rel {g.relevance} faith {rows[-1]['faithfulness'] or 'n/a'} "
                  f"corr {g.correctness} compl {rows[-1]['completeness']:.2f}{'  declined' if declined else ''}")

    summary = []
    for mx in args.max_tokens:
        v = [r for r in rows if r["variant"] == f"max{mx}"]
        ins, oos = [r for r in v if r["in_scope"]], [r for r in v if not r["in_scope"]]
        mean = lambda key, rs: round(st.mean(r[key] for r in rs if r[key] != ""), 3) if any(r[key] != "" for r in rs) else ""
        summary.append({"variant": f"max{mx}", "questions": len(ins), "relevance": mean("relevance", ins),
                        "faithfulness": mean("faithfulness", ins), "correctness": mean("correctness", ins),
                        "completeness": mean("completeness", ins),
                        "fully_faithful": sum(r["faithfulness"] == 1.0 for r in ins),
                        "wrongly_declined": sum(r["declined"] for r in ins),
                        "out_of_scope": len(oos), "out_of_scope_declined": sum(r["declined"] for r in oos)})

    suffix = "" if not args.limit else "_partial"
    for path, data in ((OUT_DIR / f"eval_{args.category}_generation{suffix}.csv", rows),
                       (OUT_DIR / f"eval_{args.category}_generation_summary{suffix}.csv", summary)):
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, data[0].keys())
            w.writeheader()
            w.writerows(data)
    print()
    for s in summary:
        print(s)
    print(f"tokens used: {usage['input']:,} input, {usage['output']:,} output ({model})")


if __name__ == "__main__":
    main()
