"""Build the knowledge-base vector index (spec §5.4, mds/rag-data-design.md).

  python -m src.rag.build_index                  # categories in rag.categories (config.yaml): fetch missing pages, chunk, rebuild
  python -m src.rag.build_index --category basics stocks   # these categories instead
  python -m src.rag.build_index --refresh        # re-fetch every page from Wikipedia first
  python -m src.rag.build_index --offline        # use only pages already saved under src/data/raw/wikipedia/

Pages listed in src/data/kb_topics.yaml are saved in full (not truncated) to src/data/raw/wikipedia/<category>/<slug>.md,
then chunked one section per chunk (max `rag.max_tokens`) and written to the `rag.collection` Qdrant collection.
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics as st
from pathlib import Path

from src.core.config import DATA_DIR, ROOT, get_config
from src.kb.ingest import load_topics
from src.kb.wiki import WikiClient, WikiError, slugify

from .chunker import Chunk, chunk_document
from .store import build_collection, get_client

RAW_DIR = DATA_DIR / "raw" / "wikipedia"
CHUNKS_CSV = ROOT / "mds" / "data" / "kb_index_chunks.csv"


def save_page(path: Path, title: str, url: str, revision: int, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n<!-- {url} | revision {revision} -->\n\n{text}\n")


def read_page(path: Path) -> tuple[str, str, str]:
    head, body = path.read_text().split("-->", 1)
    return head.split("\n", 1)[0][2:].strip(), re.search(r"<!-- (\S+)", head).group(1), body


def collect_pages(categories: list[str], *, refresh: bool, offline: bool) -> tuple[list[tuple[str, Path]], list[tuple[str, str]]]:
    """Returns ([(category, page_path)], [(title, error)]) for the given kb_topics.yaml categories."""
    topics = load_topics()
    unknown = set(categories) - set(topics)
    if unknown:
        raise SystemExit(f"unknown categories: {', '.join(sorted(unknown))} (see src/data/kb_topics.yaml)")
    client = None if offline else WikiClient()
    pages, failed = [], []
    for category in categories:
        for title in topics[category]:
            path = RAW_DIR / slugify(category) / f"{slugify(title)}.md"
            if not path.exists() or refresh:
                if offline:
                    failed.append((title, "not saved yet (offline)"))
                    continue
                try:
                    p = client.get_page(title)
                except WikiError as e:
                    failed.append((title, str(e)))
                    continue
                save_page(path, p.title, p.url, p.revision_id, p.text)
                print(f"  fetched {category} / {p.title}")
            pages.append((category, path))
    return pages, failed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--category", nargs="+", help="kb_topics.yaml categories to index (default: rag.categories)")
    args = ap.parse_args()
    cfg = get_config()["rag"]

    pages, failed = collect_pages(args.category or cfg["categories"], refresh=args.refresh, offline=args.offline)
    chunks: list[Chunk] = []
    for category, path in pages:
        title, url, body = read_page(path)
        chunks += chunk_document(slugify(title), title, category, url, body, max_tokens=cfg["max_tokens"],
                                 split_target=cfg["split_target_tokens"], overlap=cfg["overlap_tokens"])

    client = get_client(cfg)
    build_collection(client, cfg["collection"], chunks)
    stored = client.count(cfg["collection"]).count

    CHUNKS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(CHUNKS_CSV, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["category", "doc_id", "section", "section_tokens", "piece", "pieces", "tokens"])
        w.writerows([c.category, c.doc_id, c.section, c.section_tokens, c.piece + 1, c.pieces, c.tokens] for c in chunks)

    toks = [c.tokens for c in chunks]
    print(f"\ncollection '{cfg['collection']}': {stored} points from {len(pages)} documents "
          f"(chunk tokens median {int(st.median(toks))}, max {max(toks)}, over limit {sum(t > cfg['max_tokens'] for t in toks)})")
    by_cat: dict[str, list[Chunk]] = {}
    for c in chunks:
        by_cat.setdefault(c.category, []).append(c)
    for cat, cs in by_cat.items():
        print(f"  {cat:28s} {len({c.doc_id for c in cs}):3d} docs  {len(cs):4d} chunks")
    for title, err in failed:
        print(f"  FAILED {title}: {err}")
    print(f"chunk list: {CHUNKS_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
