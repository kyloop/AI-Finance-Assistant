"""Token statistics for knowledge-base source pages, per document / section / paragraph (see mds/kb-token-stats-<category>.md).

  python -m scripts.kb_token_stats --category basics       # fetch the category's pages from Wikipedia, write CSVs
  python -m scripts.kb_token_stats --pages-dir some/dir    # use already-saved pages (<name>.md: "# Title", "-->", body)

Writes mds/data/<category>_{docs,sections,paragraphs}.csv and prints a summary. Tokens are counted with the
BAAI/bge-small-en-v1.5 tokenizer, without [CLS]/[SEP]. "clean" = Wikipedia's MathML text dumps collapsed to inline LaTeX.
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics as st
from pathlib import Path

from src.rag.text import clean, sections

OUT_DIR = Path(__file__).resolve().parent.parent / "mds" / "data"


def fetch_pages(category: str) -> list[tuple[str, str, str]]:
    from src.kb.ingest import load_topics            # imported lazily: --pages-dir needs no network
    from src.kb.wiki import WikiClient
    client = WikiClient()
    pages = [client.get_page(t) for t in load_topics()[category]]
    return [(p.title, p.url, p.text) for p in pages]


def read_pages(folder: Path) -> list[tuple[str, str, str]]:
    pages = []
    for f in sorted(folder.glob("*.md")):
        raw = f.read_text()
        head, body = raw.split("-->", 1)
        url = re.search(r"<!-- (\S+)", head)
        pages.append((head.split("\n", 1)[0][2:].strip(), url.group(1) if url else "", body))
    return pages


def measure(pages, tokenizer):
    tok = lambda s: len(tokenizer.encode(s, add_special_tokens=False).ids) if s.strip() else 0
    words = lambda s: sum(1 for w in s.split() if w.strip("#"))
    docs, secs, paras = [], [], []
    for title, url, raw in pages:
        body = clean(raw)
        doc_secs = []
        for path, depth, text in sections(body):
            ps = [p for p in text.split("\n\n") if p.strip()]
            if not words(text):
                continue
            pt = [tok(p) for p in ps]
            for j, (p, t) in enumerate(zip(ps, pt)):
                paras.append(dict(doc=title, section=path, paragraph=j, words=words(p), tokens=t, has_math="$" in p and "\\" in p))
            doc_secs.append(dict(doc=title, section=path, depth=depth, paragraphs=len(ps), words=words(text), tokens=tok(text),
                                 max_paragraph_tokens=max(pt), has_math="$" in text and "\\" in text))
        secs += doc_secs
        w, tc = words(body), tok(body)
        docs.append(dict(doc=title, url=url, sections=len(doc_secs), paragraphs=sum(s["paragraphs"] for s in doc_secs), words=w,
                         tokens_raw=tok(raw), tokens_clean=tc, tokens_per_word=round(tc / max(w, 1), 2),
                         math_sections=sum(s["has_math"] for s in doc_secs)))
    return docs, secs, paras


def dist(v: list[int]) -> str:
    q = lambda n, i: int(st.quantiles(v, n=n, method="inclusive")[i]) if len(v) > 1 else v[0]
    return f"min {min(v)}  p25 {q(4, 0)}  median {int(st.median(v))}  p75 {q(4, 2)}  p90 {q(10, 8)}  max {max(v)}  mean {int(st.mean(v))}"


def buckets(v: list[int], edges=(150, 250, 400, 512)) -> str:
    labels = [f"<{edges[0]}"] + [f"{a}-{b}" for a, b in zip(edges, edges[1:])] + [f">={edges[-1]}"]
    counts = [sum(x < edges[0] for x in v)] + [sum(a <= x < b for x in v) for a, b in zip(edges, edges[1:])] + [sum(x >= edges[-1] for x in v)]
    return "  ".join(f"{lab}: {c}" for lab, c in zip(labels, counts))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--category", default="basics", help="kb_topics.yaml category; also the CSV name prefix")
    ap.add_argument("--pages-dir", type=Path, help="read saved pages instead of fetching from Wikipedia")
    args = ap.parse_args()

    from src.rag.text import get_tokenizer
    tokenizer = get_tokenizer()
    pages = read_pages(args.pages_dir) if args.pages_dir else fetch_pages(args.category)
    docs, secs, paras = measure(pages, tokenizer)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in (("docs", docs), ("sections", secs), ("paragraphs", paras)):
        with open(OUT_DIR / f"{args.category}_{name}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, rows[0].keys())
            w.writeheader()
            w.writerows(rows)

    for d in docs:
        print(f"{d['doc'][:28]:28s} sections {d['sections']:3d}  paragraphs {d['paragraphs']:4d}  words {d['words']:6d}  "
              f"tokens raw {d['tokens_raw']:6d} clean {d['tokens_clean']:6d}  t/w {d['tokens_per_word']}")
    for label, rows in (("sections", secs), ("paragraphs", paras)):
        v = [r["tokens"] for r in rows]
        print(f"\n{label} ({len(v)}): {dist(v)}\n  {buckets(v)}")
    print(f"\nwrote {OUT_DIR}/{args.category}_{{docs,sections,paragraphs}}.csv")


if __name__ == "__main__":
    main()
