"""Fetch the articles listed in src/data/kb_topics.yaml into src/data/knowledge_base/<category>/.

  python -m src.kb.ingest --dry-run              # check every title exists, show word counts, write nothing
  python -m src.kb.ingest                        # fetch all missing articles
  python -m src.kb.ingest --category taxes       # only categories whose name contains "taxes"
  python -m src.kb.ingest --force                # overwrite existing files
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import yaml

from src.core.config import DATA_DIR

from .wiki import WikiClient, WikiError, slugify, to_markdown

TOPICS_FILE = DATA_DIR / "kb_topics.yaml"
KB_DIR = DATA_DIR / "knowledge_base"


def load_topics(path: Path = TOPICS_FILE) -> dict[str, list[str]]:
    with open(path) as f:
        return yaml.safe_load(f)


def ingest(client: WikiClient, topics: dict[str, list[str]], out_dir: Path = KB_DIR, *, only: str | None = None,
           dry_run: bool = False, force: bool = False, max_words: int = 800) -> dict:
    """Returns {"written": [...], "skipped": [...], "failed": [(title, reason)]}."""
    result = {"written": [], "skipped": [], "failed": []}
    for category, titles in topics.items():
        if only and only.lower() not in category.lower():
            continue
        for title in titles:
            target = out_dir / slugify(category) / f"{slugify(title)}.md"
            if target.exists() and not force and not dry_run:
                result["skipped"].append(str(target))
                continue
            try:
                page = client.get_page(title)
            except WikiError as e:
                result["failed"].append((title, str(e)))
                continue
            if dry_run:
                result["written"].append(f"{category} / {page.title} ({page.word_count} words)")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(to_markdown(page, category, max_words))
            result["written"].append(str(target))
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--category")
    ap.add_argument("--max-words", type=int, default=800)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    client = WikiClient()
    try:
        r = ingest(client, load_topics(), only=args.category, dry_run=args.dry_run, force=args.force, max_words=args.max_words)
    finally:
        client.close()
    for line in r["written"]:
        print(("would fetch  " if args.dry_run else "wrote  ") + line)
    for line in r["skipped"]:
        print("exists  " + line)
    for title, why in r["failed"]:
        print(f"FAILED  {title}: {why}")
    print(f"\n{len(r['written'])} {'checked' if args.dry_run else 'written'}, {len(r['skipped'])} skipped, {len(r['failed'])} failed")


if __name__ == "__main__":
    main()
