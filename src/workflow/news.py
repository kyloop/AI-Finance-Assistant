"""News agent helpers: decide between the live headline feed and the indexed-story search, and format stories.

"Latest on AAPL" or "market news" is answered from the live (5-minute cached) feed; anything with a topic in it
("what's been said about chip export restrictions this week?") goes to vector search over the indexed stories."""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone

from .router import COMPANY_ALIASES

_STOPWORDS = set("""a an the and or of on in at to for from with about around into over this that these those it its is are was were be been
what whats what's how when where who which any anything some there their they them me my you your i we us do does did has have had
can could would should will tell show give get grab pull fetch check see know find latest recent recently lately new newest news headline headlines
story stories article articles update updates happening happened going said saying been being today now currently right
stock stocks share shares price prices quote quotes market markets ticker company companies please just also more other""".split())
_CASHTAG = re.compile(r"\$([A-Z]{1,5})\b")
_TICKER_NEWS = re.compile(r"\b([A-Z]{2,5})\s+(?:news|headlines?|stock|shares)\b|\b(?:news|headlines?|latest|updates?)\s+(?:on|about|for)\s+([A-Z]{2,5})\b")
_DAYS = [(r"\btoday\b|\bthis morning\b|\btonight\b|\blast 24 hours\b", 1), (r"\byesterday\b", 2),
         (r"\bthis week\b|\bpast week\b|\blast week\b|\bpast 7 days\b|\blast 7 days\b", 7),
         (r"\bthis month\b|\bpast month\b|\blast month\b|\bpast 30 days\b|\blast 30 days\b", 30)]
_PAST_N_DAYS = re.compile(r"\b(?:past|last)\s+(\d{1,2})\s+days?\b", re.I)


_SECTOR_ASK = re.compile(r"\b(industry|sector)\b|\b(peers|competitors|rivals|similar companies|other companies)\b", re.I)


def asks_about_sector(text: str) -> bool:
    """"News from the same industry sector", "how are its competitors doing": about the company's peers, not the company."""
    return bool(_SECTOR_ASK.search(text))


def time_window(text: str, max_days: int = 14) -> int | None:
    """Days of history the question asks for ("today" → 1, "this week" → 7), capped at the retention window; None if it names none."""
    m = _PAST_N_DAYS.search(text)
    if m:
        return min(int(m.group(1)), max_days)
    for pattern, days in _DAYS:
        if re.search(pattern, text, re.I):
            return min(days, max_days)
    return None


def tickers_in(text: str, entities: dict) -> list[str]:
    """Tickers the user names: the router's known ones plus cashtags ($TSLA) and "TSLA news" / "news on TSLA" patterns."""
    found = list(entities.get("tickers") or [])
    for m in _CASHTAG.finditer(text):
        found.append(m.group(1))
    for m in _TICKER_NEWS.finditer(text):
        found.append(m.group(1) or m.group(2))
    return list(dict.fromkeys(found))


def topic_words(text: str, tickers: list[str], mentions: list[str] = ()) -> list[str]:
    """Words left once the generic news phrasing, ticker, company names (even misspelt) and time window are removed. Empty means the user wants the
    latest headlines for the ticker (or the market) rather than a specific topic."""
    lower = text.lower()
    for name in COMPANY_ALIASES:
        lower = lower.replace(name, " ")
    for pattern, _ in _DAYS:
        lower = re.sub(pattern, " ", lower)
    lower = _PAST_N_DAYS.sub(" ", lower)
    for m in mentions:                                         # the company the user named is the subject, not the topic
        lower = lower.replace(m.lower(), " ")
    skip = _STOPWORDS | {t.lower() for t in tickers} | {"wall", "street", "dow", "nasdaq", "s&p", "500", "jones", "week", "month", "day", "days", "past", "last"}
    names = {w for m in mentions for w in re.findall(r"[a-z0-9&]+", m.lower()) if len(w) >= 4}
    misspelt = lambda w: len(w) >= 4 and bool(difflib.get_close_matches(w, names, n=1, cutoff=0.75))      # noqa: E731  "nvdia" for NVIDIA
    return [w for w in re.findall(r"[a-z0-9&]+", lower) if w not in skip and len(w) > 1 and not misspelt(w)]


def _when(published: str | None) -> str:
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (AttributeError, ValueError):
        return ""
    return f"{dt:%b} {dt.day}, {dt:%H:%M} UTC"


def format_story(s: dict, summary_chars: int = 220) -> str:
    summary = " ".join((s.get("summary") or "").split())
    if len(summary) > summary_chars:
        summary = summary[:summary_chars].rsplit(" ", 1)[0] + "…"
    byline = ", ".join(x for x in (s.get("publisher"), _when(s.get("published"))) if x)
    return f"- **{s['title']}**" + (f" ({byline})" if byline else "") + (f": {summary}" if summary else "")


def story_source(s: dict) -> dict:
    return {"id": f"news:{s.get('story_id') or s['id']}", "title": f"{s['title']} ({s['publisher']})" if s.get("publisher") else s["title"],
            "url": s["url"]}
