"""Article text for Yahoo Finance stories. Yahoo's news search gives only a headline, so the News agent reads the story's page
for what it actually says: the paragraphs of the article body (`div.body-wrap`) without the promo lines, embedded posts and
sponsored blocks around them, else the page's description (a one-line teaser for stories Yahoo only links to). The excerpt
is kept on the story in the news index for `news_index.article_ttl_days` (src/rag/news.py)."""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
MIN_PARAGRAPH = 40                     # shorter <p>s are captions, bylines and buttons
# Lines that aren't the story: links to other articles, disclosures, embedded posts. "Read Next" and sponsored blocks come
# after the story, so the excerpt stops there.
_SKIP = re.compile(r"^(trending|see also|also read|related|recommended|don't miss|story continues)\b|may earn commission|"
                   r"pic\.twitter\.com|^—\s|^©|all rights reserved|does not provide investment advice", re.I)
_STOP = re.compile(r"^(read next|read more|more from|sponsored|advertisement)\b|accredited investors|starting (at|with as little as) \$", re.I)


def is_yahoo(url: str) -> bool:
    host = urlparse(url or "").netloc.lower()
    return host == "finance.yahoo.com" or host.endswith(".finance.yahoo.com")


def extract(html: str, max_chars: int) -> str:
    """The story's text from a Yahoo Finance article page, cut at a sentence end near `max_chars`; '' when the page has none."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    body, kept = soup.select_one("div.body-wrap"), []
    for p in body.find_all("p") if body else []:
        line = " ".join(p.get_text(" ", strip=True).split())
        if _STOP.search(line):
            break
        linked = sum(len(a.get_text(strip=True)) for a in p.find_all("a"))
        if (len(line) >= MIN_PARAGRAPH and not _SKIP.search(line) and linked < 0.6 * len(line)   # mostly a link: a promo
                and not p.find_parent("blockquote")):                                                    # an embedded post
            kept.append(line)
    if not kept:
        meta = soup.find("meta", attrs={"name": "description"})
        kept = [" ".join(meta["content"].split())] if meta and meta.get("content") else []
    text = " ".join(kept)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    end = max(cut.rfind(". "), cut.rfind(".\" "), cut.rfind(".” "))
    return cut[:end + 1] if end > max_chars // 2 else cut.rsplit(" ", 1)[0] + "…"


def fetch_article(url: str, max_chars: int = 1500, timeout: float = 8.0) -> str:
    """The story's text, or '' if the page can't be read. Never raises."""
    try:
        r = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=timeout)
        if r.status_code != 200:
            log.info("article %s: HTTP %s", url, r.status_code)
            return ""
        return extract(r.text, max_chars)
    except Exception as e:  # noqa: BLE001 — a page that won't load just leaves the headline
        log.info("article %s: %s", url, type(e).__name__)
        return ""
