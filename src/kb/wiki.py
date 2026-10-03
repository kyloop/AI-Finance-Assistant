"""Wikipedia client for pulling source articles into the knowledge base (spec §3.4, FR-K6/K7).

Thin layer over the `Wikipedia-API` package (https://pypi.org/project/Wikipedia-API/), which provides HTTP, retries with
backoff and section parsing. This module adds what the knowledge base needs: our error types, disambiguation detection,
dropping boilerplate sections, a polite delay, word-limit truncation and article rendering with attribution.

Wikipedia text is CC BY-SA 4.0: keep source_url / revision_id / license with every article, and keep text derived
from it under the same licence."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date

import httpx
import wikipediaapi

log = logging.getLogger(__name__)

USER_AGENT = "FinnieKB/0.1 (educational finance assistant; contact: kc.kevin.ying@gmail.com)"  # Wikimedia UA policy
DROP_SECTIONS = {"references", "see also", "external links", "further reading", "notes", "footnotes", "citations",
                 "sources", "bibliography", "explanatory notes"}


class WikiError(Exception):
    """Base class for wiki client failures."""


class PageNotFound(WikiError):
    pass


class DisambiguationPage(WikiError):
    pass


class WikiUnavailable(WikiError):
    """Network/HTTP failure after the library's retries."""


def count_words(text: str) -> int:
    return sum(1 for w in text.split() if w.strip("#"))       # Markdown heading markers aren't words


@dataclass(frozen=True)
class WikiSite:
    name: str
    license: str
    license_url: str


WIKIPEDIA = WikiSite("Wikipedia", "CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/")


@dataclass
class WikiPage:
    title: str
    text: str                # Markdown: lead paragraph(s), then "## Heading" sections
    url: str
    revision_id: int
    site: WikiSite = WIKIPEDIA

    @property
    def word_count(self) -> int:
        return count_words(self.text)


def render_sections(sections, skip: set[str] = DROP_SECTIONS) -> str:
    """Nested Wikipedia sections -> Markdown, dropping non-content sections (and everything under them)."""
    parts: list[str] = []
    for sec in sections:
        if sec.title.strip().lower() in skip:
            continue
        parts.append(f"{'#' * min(sec.level + 1, 6)} {sec.title.strip()}")
        if sec.text.strip():
            parts.append(sec.text.strip())
        nested = render_sections(sec.sections, skip)
        if nested:
            parts.append(nested)
    return "\n\n".join(parts)


def truncate_words(text: str, max_words: int) -> tuple[str, bool]:
    """Cut at a paragraph boundary at or under max_words; never leaves a dangling heading."""
    if count_words(text) <= max_words:
        return text, False
    kept, count = [], 0
    for block in text.split("\n\n"):
        n = count_words(block)
        if count + n > max_words:
            break
        kept.append(block)
        count += n
    while kept and kept[-1].lstrip().startswith("#"):
        kept.pop()
    if kept:
        return "\n\n".join(kept), True
    sentences, taken, count = re.split(r"(?<=[.!?])\s+", text.strip()), [], 0
    for sent in sentences:                          # one paragraph over the limit: cut at a sentence boundary
        n = count_words(sent)
        if taken and count + n > max_words:
            break
        taken.append(sent)
        count += n
    out = " ".join(taken)
    return (out if count <= max_words * 1.5 else " ".join(out.split()[:max_words]) + "…"), True


class WikiClient:
    def __init__(self, *, language: str = "en", delay: float = 1.0, retries: int = 3, retry_wait: float = 1.0,
                 timeout: float = 15.0, transport: httpx.BaseTransport | None = None):
        self.delay = delay
        self._last = 0.0
        kwargs = {"transport": transport} if transport else {}
        self._wiki = wikipediaapi.Wikipedia(
            user_agent=USER_AGENT, language=language, extract_format=wikipediaapi.ExtractFormat.WIKI,
            max_retries=retries, retry_wait=retry_wait, timeout=timeout, **kwargs)

    def close(self) -> None:
        pass  # the library manages its own connection

    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get_page(self, title: str) -> WikiPage:
        self._throttle()
        try:
            page = self._wiki.page(title)
            if not page.exists():
                raise PageNotFound(title)
            if any("disambiguation" in c.lower() for c in page.categories):
                raise DisambiguationPage(f"“{title}” is a disambiguation page; pick a specific title")
            lead = page.summary.strip()
            body = render_sections(page.sections)
            url, revision, resolved = page.canonicalurl, page.lastrevid, page.title
        except wikipediaapi.WikipediaException as e:
            raise WikiUnavailable(f"Wikipedia API failed: {e}") from e
        text = "\n\n".join(x for x in (lead, body) if x)
        if not text:
            raise PageNotFound(f"{title} (no text content)")
        return WikiPage(title=resolved, text=text, url=url, revision_id=revision)

    def search(self, query: str, limit: int = 5) -> list[str]:
        try:
            return [p.title for p in self._wiki.search(query, limit=limit).pages.values()]
        except wikipediaapi.WikipediaException as e:
            raise WikiUnavailable(f"Wikipedia API failed: {e}") from e


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def to_markdown(page: WikiPage, category: str, max_words: int = 800, reviewed: date | None = None) -> str:
    """Render a page as a knowledge-base article with the front-matter the RAG/seed code expects."""
    body, truncated = truncate_words(page.text, max_words)
    q = lambda v: '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
    front = [
        "---",
        f"title: {q(page.title)}",
        f"category: {q(category)}",
        f"source_name: {q(page.site.name)}",
        f"source_url: {q(page.url)}",
        f"last_reviewed: {(reviewed or date.today()).isoformat()}",
        f"license: {q(page.site.license)}",
        f"revision_id: {page.revision_id}",
        f"truncated: {str(truncated).lower()}",
        "---",
    ]
    footer = (f"\n\n---\n*Source: [{page.title}]({page.url}) on {page.site.name}, revision {page.revision_id}, "
              f"licensed under [{page.site.license}]({page.site.license_url}).*")
    return "\n".join(front) + "\n" + body + footer + "\n"
