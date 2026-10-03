"""News index evaluation: token statistics of real stories, then retrieval scored against labelled questions, for two ways of indexing a story.

  python -m scripts.eval_news

Inputs:  tests/data/news_snapshot.json (frozen real Yahoo stories), tests/data/news_eval.yaml (questions, expected stories, hints)
Outputs: mds/data/news_eval_results.csv (one row per question x variant), mds/data/news_eval_summary.csv, mds/news-eval.md
Variants: "title+summary" is what the index stores; "title only" shows what the summary adds. Each runs on an in-memory Qdrant with the
real embedder, through src.rag.news (the same ingest and search the API uses). Metrics are those of mds/kb-token-stats-*.md: hit@1, hit@5,
hint@5 (the answer phrase is in a retrieved story's text), MRR, and the tokens sent to the LLM for the top 5.
Text between the <!-- findings:start --> / <!-- generation:start --> markers of mds/news-eval.md (hand-written findings; the section
scripts.eval_news_generation writes) is kept.
"""
from __future__ import annotations

import csv
import json
import statistics as st
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml
from qdrant_client import QdrantClient

from src.core.config import get_config
from src.rag import news
from src.rag.store import get_embedder

ROOT = Path(__file__).resolve().parent.parent
K = 5
VARIANTS = ("title+summary", "title only")
BANDS = (("S", "< 40"), ("M", "40-79"), ("L", ">= 80"))          # tokens of title + summary of the expected story
norm = lambda s: " ".join(s.lower().split())


def pct(values: list[float], p: float) -> float:
    return st.quantiles(values, n=100, method="inclusive")[int(p) - 1] if len(values) > 1 else values[0]


def dist(values: list[float]) -> str:
    v = sorted(values)
    return f"{v[0]:.0f} | {pct(v, 25):.0f} | {st.median(v):.0f} | {pct(v, 75):.0f} | {pct(v, 95):.0f} | {v[-1]:.0f}"


def main() -> None:
    snap = json.loads((ROOT / "tests/data/news_snapshot.json").read_text())
    stories = snap["stories"]
    questions = yaml.safe_load((ROOT / "tests/data/news_eval.yaml").read_text())
    tok = get_embedder().model.tokenizer
    ntok = lambda t: len(tok.encode(t, add_special_tokens=False).ids) if t else 0           # noqa: E731
    by_prefix = {s["id"][:8]: s for s in stories}
    cfg = get_config()["news_index"]
    retention = cfg["retention_days"]
    cfg["retention_days"] = 100_000                           # the snapshot is a frozen sample: keep every story whatever its age
    captured = datetime.fromisoformat(snap["captured"].replace("Z", "+00:00"))

    # ---- token statistics ---------------------------------------------------------------------------------
    full = [ntok(f"{s['title']}\n{s['summary']}") for s in stories]
    title_t, summ_t = [ntok(s["title"]) for s in stories], [ntok(s["summary"]) for s in stories]
    chars = [len(s["summary"]) for s in stories]
    age_days = [(captured - datetime.fromisoformat(s["published"].replace("Z", "+00:00"))).total_seconds() / 86400 for s in stories]
    pubs = Counter(s["publisher"] for s in stories)
    band_of = lambda tokens: "S" if tokens < 40 else "M" if tokens < 80 else "L"               # noqa: E731

    # ---- retrieval ----------------------------------------------------------------------------------------
    results, summary, kept_stats = [], [], {}
    for variant in VARIANTS:
        client = QdrantClient(":memory:")
        news._ready = False
        items = [{"id": s["id"], "title": s["title"], "summary": s["summary"] if variant == "title+summary" else "",
                  "publisher": s["publisher"], "url": s["url"], "published": s["published"]} for s in stories]
        news.ingest("MARKET", items, client=client)
        rows = []
        for q in questions:
            hits = news.search(client, q["q"], days=100_000, k=K)
            ids = [h["story_id"][:8] for h in hits]
            rank = next((i + 1 for i, h in enumerate(ids) if h in q["expect"]), None)
            hint_rank = next((i + 1 for i, h in enumerate(hits)
                              if any(norm(x) in norm(f"{h['title']}\n{h['summary']}") for x in q["hints"])), None) if q["hints"] else None
            floor = max(cfg["min_score"], hits[0]["score"] - cfg["score_margin"])
            kept = [h for h in hits if h["score"] >= floor]
            rows.append({"variant": variant, "id": q["id"], "kind": q.get("kind", "answerable"), "question": q["q"],
                         "band": band_of(full[stories.index(by_prefix[q["expect"][0]])]) if q["expect"] else "",
                         "rank": rank, "hint_rank": hint_rank, "top1_score": round(hits[0]["score"], 3),
                         "context_tokens": sum(ntok(f"{h['title']}\n{h['summary']}") for h in hits),
                         "kept": len(kept), "kept_correct": sum(h["story_id"][:8] in q["expect"] for h in kept),
                         "top1": by_prefix.get(ids[0], {}).get("title", "")[:70]})
        results += rows
        ans = [r for r in rows if r["kind"] == "answerable"]
        rr = [1 / r["rank"] if r["rank"] else 0 for r in ans]
        top1 = lambda kind: [r["top1_score"] for r in rows if r["kind"] == kind]                 # noqa: E731
        summary.append({"variant": variant, "answerable": len(ans), "hit@1": sum(r["rank"] == 1 for r in ans),
                        "hit@3": sum(bool(r["rank"]) and r["rank"] <= 3 for r in ans), "hit@5": sum(bool(r["rank"]) for r in ans),
                        "mrr": round(st.mean(rr), 3), "hint@5": sum(bool(r["hint_rank"]) for r in ans),
                        "mean_context_tokens": int(st.mean(r["context_tokens"] for r in rows)),
                        "min_top1_answerable": min(r["top1_score"] for r in ans), "max_top1_out_of_scope": max(top1("out_of_scope")),
                        "max_top1_near_miss": max(top1("near_miss")),
                        "filter_answerable_with_correct": sum(r["kept_correct"] > 0 for r in ans),
                        "filter_answerable_empty": sum(r["kept"] == 0 for r in ans),
                        "filter_out_of_scope_empty": sum(r["kept"] == 0 for r in rows if r["kind"] == "out_of_scope"),
                        "filter_near_miss_empty": sum(r["kept"] == 0 for r in rows if r["kind"] == "near_miss"),
                        "filter_mean_kept": round(st.mean(r["kept"] for r in ans), 2),
                        "filter_precision": round(sum(r["kept_correct"] for r in ans) / max(1, sum(r["kept"] for r in ans)), 3)})

    out = ROOT / "mds" / "data"
    for name, rows in (("news_eval_results.csv", results), ("news_eval_summary.csv", summary)):
        with open(out / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, rows[0].keys())
            w.writeheader()
            w.writerows(rows)

    # ---- report -------------------------------------------------------------------------------------------
    S = {s["variant"]: s for s in summary}
    A, B = (S[v] for v in VARIANTS)
    n_ans, n_out, n_near = (sum(q.get("kind", "answerable") == k for q in questions) for k in ("answerable", "out_of_scope", "near_miss"))
    cell = lambda k, bold=True: f"{A[k]} | {B[k]}"                                              # noqa: E731
    L = []
    L += ["# News index: token statistics and retrieval test", "",
          "Measurements of real Yahoo Finance news stories and a retrieval test of two ways to index them, using the same metrics as the "
          "knowledge-base reports ([kb-token-stats-basics.md](kb-token-stats-basics.md)). Design: [news-index.md](news-index.md). "
          "Generated by `python -m scripts.eval_news`; only the findings are written by hand.", "",
          f"- **Sample:** {len(stories)} unique stories from the news cache of the MARKET, AAPL, NVDA, AMD, SPY, SPCX and AM feeds, captured "
          f"{snap['captured']}, frozen in [news_snapshot.json](../tests/data/news_snapshot.json). Titles and summaries are Yahoo's own text.",
          "- **Tokenizer:** `BAAI/bge-small-en-v1.5` (the embedding model), without `[CLS]`/`[SEP]`. Its input limit is 512 tokens.",
          f"- **Questions:** {len(questions)} in [news_eval.yaml](../tests/data/news_eval.yaml): {n_ans} answerable by one or more stories, {n_out} "
          f"out of scope (not finance) and {n_near} near-miss (finance, but the snapshot has no story on it).",
          "- **Variants:** *title+summary* is what the index stores (`\"{title}\\n{summary}\"`); *title only* indexes and returns the headline alone.",
          f"- **Search:** top {K}, no ticker or date filter (the snapshot is a frozen sample, so the date window is open). "
          "Raw results: [news_eval_results.csv](data/news_eval_results.csv), [news_eval_summary.csv](data/news_eval_summary.csv).", "",
          "## Reproduce", "", "```bash", "python -m scripts.eval_news", "```", "",
          "## Stories (tokens)", "", "| | min | p25 | median | p75 | p95 | max |", "|---|---|---|---|---|---|---|",
          f"| Title | {dist(title_t)} |", f"| Summary | {dist(summ_t)} |", f"| Title + summary (what is embedded) | {dist(full)} |",
          f"| Summary, characters | {dist(chars)} |", "",
          f"- Summaries under 100 characters: **{sum(c < 100 for c in chars)}** of {len(stories)}; empty: **{sum(c == 0 for c in chars)}**. "
          f"Stories over the model's 512 tokens: **{sum(t > 512 for t in full)}**.",
          f"- Age at capture (days): median **{st.median(age_days):.1f}**, oldest **{max(age_days):.0f}**; older than the {retention}-day "
          f"retention window: **{sum(a > retention for a in age_days)}** ({sum(a > retention for a in age_days) / len(stories):.0%}).",
          "- Publishers: " + ", ".join(f"{p} {n}" for p, n in pubs.most_common(6)) + f", and {len(pubs) - 6} more.", "",
          "## Retrieval test: title+summary vs title only", "",
          "- **hit@k:** one of the question's expected stories is in the top k. **hint@5:** the answer phrase itself is in the text of a retrieved "
          "story (title+summary, or the title alone for that variant). **MRR:** mean of 1/rank of the first expected story (0 if missed).", "",
          f"### Summary ({n_ans} answerable questions)", "", "| | title+summary | title only |", "|---|---|---|",
          f"| hit@1 | **{A['hit@1']} ({A['hit@1'] / n_ans:.0%})** | {B['hit@1']} ({B['hit@1'] / n_ans:.0%}) |",
          f"| hit@3 | **{A['hit@3']}** | {B['hit@3']} |",
          f"| hit@5 | **{A['hit@5']} ({A['hit@5'] / n_ans:.0%})** | {B['hit@5']} ({B['hit@5'] / n_ans:.0%}) |",
          f"| MRR | **{A['mrr']}** | {B['mrr']} |",
          f"| hint@5 (answer text retrieved) | **{A['hint@5']}** | {B['hint@5']} |",
          f"| Mean tokens sent to the LLM (top {K}) | {A['mean_context_tokens']:,} | {B['mean_context_tokens']:,} |", "",
          "### By size of the expected story (hit@1 / hit@5 / hint@5 / MRR)", "", "| Band (tokens) | n | title+summary | title only |", "|---|---|---|---|"]
    for b, label in BANDS:
        cells = []
        for v in VARIANTS:
            r = [x for x in results if x["variant"] == v and x["kind"] == "answerable" and x["band"] == b]
            cells.append(f"{sum(x['rank'] == 1 for x in r)} / {sum(bool(x['rank']) for x in r)} / {sum(bool(x['hint_rank']) for x in r)} / "
                         f"{st.mean([1 / x['rank'] if x['rank'] else 0 for x in r]):.2f}" if r else "-")
        n = len([x for x in results if x["variant"] == VARIANTS[0] and x["kind"] == "answerable" and x["band"] == b])
        L.append(f"| {b} ({label}) | {n} | {cells[0]} | {cells[1]} |")
    L += ["", "### Per question", "",
          "Each cell: **story rank / phrase rank** in the top 5 (1 is best; – = not in the top 5), then the top-1 score. Bold marks the better variant.", "",
          "| id | Band | Question | title+summary | title only |", "|---|---|---|---|---|"]
    for q in questions:
        if q.get("kind", "answerable") != "answerable":
            continue
        ra, rb = (next(r for r in results if r["variant"] == v and r["id"] == q["id"]) for v in VARIANTS)
        sc = lambda r: (r["rank"] or 99, r["hint_rank"] or 99)                                    # noqa: E731
        fmt = lambda r, win: ("**" if win else "") + f"{r['rank'] or '–'} / {r['hint_rank'] or '–'} ({r['top1_score']:.2f})" + ("**" if win else "")  # noqa: E731
        L.append(f"| {q['id']} | {ra['band']} | {q['q']} | {fmt(ra, sc(ra) < sc(rb))} | {fmt(rb, sc(rb) < sc(ra))} |")
    L += ["", "### Score threshold", "",
          "Top-1 cosine score. A good `min_score` sits between the lowest answerable score and the highest score of a question with no answer.", "",
          "| | title+summary | title only |", "|---|---|---|",
          f"| Lowest top-1, answerable | {A['min_top1_answerable']} | {B['min_top1_answerable']} |",
          f"| Highest top-1, out of scope ({n_out}) | {A['max_top1_out_of_scope']} | {B['max_top1_out_of_scope']} |",
          f"| Highest top-1, near-miss ({n_near}) | {A['max_top1_near_miss']} | {B['max_top1_near_miss']} |", "",
          f"### What the agent's filter returns (`min_score` {cfg['min_score']}, `score_margin` {cfg['score_margin']})", "",
          "| | title+summary | title only |", "|---|---|---|",
          f"| Answerable: kept a correct story | {A['filter_answerable_with_correct']} of {n_ans} | {B['filter_answerable_with_correct']} of {n_ans} |",
          f"| Answerable: wrongly returned nothing | {A['filter_answerable_empty']} | {B['filter_answerable_empty']} |",
          f"| Answerable: mean stories kept / share that are correct | {A['filter_mean_kept']} / {A['filter_precision']:.0%} | {B['filter_mean_kept']} / {B['filter_precision']:.0%} |",
          f"| Out of scope: correctly returned nothing | {A['filter_out_of_scope_empty']} of {n_out} | {B['filter_out_of_scope_empty']} of {n_out} |",
          f"| Near-miss: correctly returned nothing | {A['filter_near_miss_empty']} of {n_near} | {B['filter_near_miss_empty']} of {n_near} |", "",
          "Out-of-scope and near-miss questions, top-1 story and score (title+summary):", "", "| id | Question | Score | Top-1 story |", "|---|---|---|---|"]
    for r in results:
        if r["variant"] == VARIANTS[0] and r["kind"] != "answerable":
            L.append(f"| {r['id']} | {r['question']} | {r['top1_score']} | {r['top1']} |")
    L += ["", "## Generation test: answer quality", "", "<!-- generation:start -->", "<!-- generation:end -->", "",
          "## Findings", "", "<!-- findings:start -->", "<!-- findings:end -->", ""]

    path = ROOT / "mds" / "news-eval.md"
    text = "\n".join(L)
    if path.exists():
        old = path.read_text()
        for name in ("generation", "findings"):                  # hand-written or separately generated sections survive a re-run
            a, b = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
            if a in old:
                keep = old.split(a, 1)[1].split(b, 1)[0]
                text = text.replace(f"{a}\n{b}", f"{a}{keep}{b}")
    path.write_text(text)
    for s in summary:
        print(s)


if __name__ == "__main__":
    main()
