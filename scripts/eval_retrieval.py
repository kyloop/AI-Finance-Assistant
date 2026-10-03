"""Retrieval evaluation: build one Qdrant collection per chunk-size variant and score labelled questions against each.

  python -m scripts.eval_retrieval --category basics                  # variants max 512 and max 250
  python -m scripts.eval_retrieval --category basics --max-tokens 512 384 250
  python -m scripts.eval_retrieval --category etfs-and-mutual-funds --chunks-only   # no questions yet: only write the chunk lists

Inputs:  tests/data/kb_snapshot/<category>/*.md, tests/data/retrieval_eval_<category>.yaml
Outputs: mds/data/eval_<category>_results.csv (one row per question x variant, with the top-5 sections),
         mds/data/eval_<category>_summary.csv, mds/data/eval_<category>_chunks_max<N>.csv
The local Qdrant store is src/data/qdrant_eval/ (git-ignored, rebuilt on every run).
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics as st
from pathlib import Path

import yaml
from qdrant_client import QdrantClient

from src.kb.wiki import slugify
from src.rag.chunker import chunk_document
from src.rag.store import build_collection, search

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "mds" / "data"
QDRANT_PATH = ROOT / "src" / "data" / "qdrant_eval"
K = 5


def load_pages(folder: Path) -> list[tuple[str, str, str]]:
    pages = []
    for f in sorted(folder.glob("*.md")):
        head, body = f.read_text().split("-->", 1)
        pages.append((head.split("\n", 1)[0][2:].strip(), re.search(r"<!-- (\S+)", head).group(1), body))
    return pages


def score_question(q: dict, hits: list[dict]) -> dict:
    keys = [f"{h['doc_id']} :: {h['section']}" for h in hits]
    rank = next((i + 1 for i, key in enumerate(keys) if key in q["expect"]), None)
    norm = lambda s: " ".join(s.lower().split())
    hint_rank = next((i + 1 for i, h in enumerate(hits)
                      if any(norm(s) in norm(h["text"]) for s in q["hints"])), None) if q["hints"] else None
    return {"rank": rank, "hint_rank": hint_rank, "top1_score": round(hits[0]["score"], 4),
            "top1": f"{keys[0]} [{hits[0]['piece'] + 1}/{hits[0]['pieces']}]",
            "context_tokens": sum(h["tokens"] for h in hits), "top5": " | ".join(keys)}


def summarise(rows: list[dict], label: str) -> dict:
    ans = [r for r in rows if r["expect"]]
    none = [r for r in rows if not r["expect"]]
    rr = [1 / r["rank"] if r["rank"] else 0 for r in ans]
    return {
        "variant": label, "questions": len(ans),
        "hit@1": sum(r["rank"] == 1 for r in ans), "hit@3": sum(bool(r["rank"]) and r["rank"] <= 3 for r in ans),
        "hit@5": sum(bool(r["rank"]) for r in ans), "mrr": round(st.mean(rr), 3) if rr else 0,
        "hint@5": sum(bool(r["hint_rank"]) for r in ans),
        "mean_top1_answerable": round(st.mean(r["top1_score"] for r in ans), 3) if ans else 0,
        "min_top1_answerable": round(min(r["top1_score"] for r in ans), 3) if ans else 0,
        "max_top1_no_answer": round(max(r["top1_score"] for r in none), 3) if none else "",
        "mean_context_tokens": int(st.mean(r["context_tokens"] for r in rows)),
    }


def write_chunks(chunks, category: str, label: str) -> None:
    with open(OUT_DIR / f"eval_{category}_chunks_{label}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["doc_id", "section", "section_tokens", "piece", "pieces", "tokens", "starts_with"])
        w.writerows([c.doc_id, c.section, c.section_tokens, c.piece + 1, c.pieces, c.tokens, c.text[:80]] for c in chunks)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--category", default="basics")
    ap.add_argument("--max-tokens", type=int, nargs="+", default=[512, 250])
    ap.add_argument("--split-target", type=int, default=350)
    ap.add_argument("--overlap", type=int, default=50)
    ap.add_argument("--chunks-only", action="store_true", help="only write the chunk lists (no questions file or Qdrant needed)")
    args = ap.parse_args()

    pages = load_pages(ROOT / "tests" / "data" / "kb_snapshot" / args.category)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.chunks_only:
        for mx in args.max_tokens:
            chunks = [c for title, url, body in pages
                      for c in chunk_document(slugify(title), title, args.category, url, body,
                                              max_tokens=mx, split_target=args.split_target, overlap=args.overlap)]
            write_chunks(chunks, args.category, f"max{mx}")
            print(f"max{mx}: {len(chunks)} chunks, {len({(c.doc_id, c.section) for c in chunks if c.pieces > 1})} sections split")
        return
    questions = yaml.safe_load(open(ROOT / "tests" / "data" / f"retrieval_eval_{args.category}.yaml"))
    client = QdrantClient(path=str(QDRANT_PATH))

    results, summary = [], []
    for mx in args.max_tokens:
        label = f"max{mx}"
        chunks = [c for title, url, body in pages
                  for c in chunk_document(slugify(title), title, args.category, url, body,
                                          max_tokens=mx, split_target=args.split_target, overlap=args.overlap)]
        name = f"eval_{args.category}_{label}"
        build_collection(client, name, chunks)
        write_chunks(chunks, args.category, label)

        rows = []
        for q in questions:
            hits = search(client, name, q["q"], k=K, category=args.category)
            rows.append({"variant": label, "id": q["id"], "band": q["band"], "question": q["q"],
                         "expect": " | ".join(q["expect"]), **score_question(q, hits)})
        results += rows
        summary.append({"chunks": len(chunks), "sections_split": len({(c.doc_id, c.section) for c in chunks if c.pieces > 1}),
                        **summarise(rows, label)})

    with open(OUT_DIR / f"eval_{args.category}_results.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, results[0].keys())
        w.writeheader()
        w.writerows(results)
    with open(OUT_DIR / f"eval_{args.category}_summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, summary[0].keys())
        w.writeheader()
        w.writerows(summary)

    for s in summary:
        print(s)
    labels = [f"max{m}" for m in args.max_tokens]
    print(f"\n{'id':4s} {'band':4s} " + "  ".join(f"{lab + ' rank/hint/score':>24s}" for lab in labels))
    for q in questions:
        cells = []
        for lab in labels:
            r = next(r for r in results if r["variant"] == lab and r["id"] == q["id"])
            cells.append(f"{str(r['rank'] or '-'):>6s} {str(r['hint_rank'] or '-'):>5s} {r['top1_score']:>11.3f}")
        print(f"{q['id']:4s} {q['band']:4s} " + "  ".join(cells))


if __name__ == "__main__":
    main()
