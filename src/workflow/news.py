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
stock stocks share shares price prices quote quotes market markets ticker company companies please just also more other
summarize summarise summarized summary summaries recap roundup overview brief briefing rundown digest highlights top main biggest
am provide want wants wanted like looking interested need needs only general overall earlier earliest""".split())
_CASHTAG = re.compile(r"\$([A-Z]{1,5})\b")
_TICKER_NEWS = re.compile(r"\b([A-Z]{2,5})\s+(?:news|headlines?|stock(?!\s+(?:markets?|exchanges?|index))|shares)\b|\b(?:news|headlines?|latest|updates?)\s+(?:on|about|for)\s+([A-Z]{2,5})\b")
_DAYS = [(r"\btoday\b|\bthis morning\b|\btonight\b|\blast 24 hours\b", 1), (r"\byesterday\b", 2),
         (r"\bthis week\b|\bpast week\b|\blast week\b|\bpast 7 days\b|\blast 7 days\b", 7),
         (r"\bthis month\b|\bpast month\b|\blast month\b|\bpast 30 days\b|\blast 30 days\b", 30)]
_PAST_N_DAYS = re.compile(r"\b(?:(?:past|last|latest|recent|previous|prior)\s+(\d{1,2})\s+days?|(\d{1,2})\s+days?\s+(?:of|worth)\b)", re.I)
_NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                         "fifteen sixteen seventeen eighteen nineteen twenty".split())}
_N = r"(\d{1,2}|" + "|".join(_NUMBERS) + r")"
# "the latest 5 news", "5 latest headlines", "top three stories", "10 news items about AAPL"; never "10 days"
_COUNT = re.compile(r"\b" + _N + r"\s+(?:(?:latest|recent|newest|most\s+recent|top|new|biggest|main|news)\s+)*"
                    r"(?:news|stories|headlines|articles|items)\b", re.I)


_SECTOR_ASK = re.compile(r"\b(industry|sector)\b|\b(peers|competitors|rivals|similar companies|other companies)\b", re.I)


def asks_about_sector(text: str) -> bool:
    """"News from the same industry sector", "how are its competitors doing": about the company's peers, not the company."""
    return bool(_SECTOR_ASK.search(text))


def time_window(text: str, max_days: int = 14) -> int | None:
    """Days of history the question asks for ("today" → 1, "this week" → 7), capped at the retention window; None if it names none."""
    m = _PAST_N_DAYS.search(text)
    if m:
        return max(1, min(int(m.group(1) or m.group(2)), max_days))
    for pattern, days in _DAYS:
        if re.search(pattern, text, re.I):
            return min(days, max_days)
    return None


def count_asked(text: str, most: int = 15) -> int | None:
    """How many stories the question asks for ("show the latest 5 news" → 5), capped at `most`; None if it names no number."""
    m = _COUNT.search(text)
    if not m:
        return None
    n = _NUMBERS.get(m.group(1).lower()) if not m.group(1).isdigit() else int(m.group(1))
    return max(1, min(n, most)) if n else None


# ---- topic or just the latest, by similarity ----------------------------------------------------------------------
# A question is a plain request for the latest news when, with its companies, markets, time window and count taken out,
# it means the same as one of these. Anything less similar has a topic of its own ("the housing market", "export
# restrictions", "earnings"), whatever words it uses: no word list decides it. Measured with bge-small on real questions
# (mds/news-topic-similarity.md): plain requests score 0.82-0.96 against these, questions with a topic 0.70-0.79.
GENERIC_REQUESTS = ["latest news", "what is the latest news", "any news", "any updates", "recent headlines", "what's happening",
                    "what's new", "news updates", "show me the news", "what happened recently", "news about this company",
                    "news regarding it", "summarize today's news", "the latest headlines for this stock"]
GENERIC_MIN = 0.81

_embedder = "default"          # tests inject fn(texts) -> vectors, or None for no embeddings (then the word rules decide)
_generic_vectors: dict = {}


def set_news_embedder(fn) -> None:
    global _embedder
    _embedder = fn
    _generic_vectors.clear()


def _embed(texts: list[str]):
    import numpy as np
    if _embedder is None:
        return None
    if _embedder == "default":
        from src.rag.store import get_embedder
        vecs = np.array(list(get_embedder().embed(texts)))
    else:
        vecs = np.array(_embedder(texts), dtype=float)
    return vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)


def residual(text: str, mentions: list[str] = ()) -> str:
    """The question without the companies and markets it names, its time window and its count: what is left is either a
    plain request for news or a topic."""
    rest = text
    for m in sorted({m for m in mentions if m}, key=len, reverse=True):
        rest = re.sub(rf"(?<![A-Za-z0-9]){re.escape(m)}(?![A-Za-z0-9])", " ", rest, flags=re.I)
    for pattern, _ in _DAYS:
        rest = re.sub(pattern, " ", rest, flags=re.I)
    rest = _PAST_N_DAYS.sub(" ", rest)
    rest = _COUNT.sub(" news ", rest)
    rest = re.sub(r"\(\s*\)|\$(?=\s|$)", " ", rest)
    rest = re.sub(r"\b(?:from|over|in|for|during)\s+(?:the\s+)?(?=[?.!]|$)", " ", rest)
    return " ".join(rest.split())


def generic_score(text: str, mentions: list[str] = ()) -> float | None:
    """How close the question (without its subjects, time and count) is to a plain request for the latest news, 0-1;
    None without embeddings."""
    rest = residual(text, mentions)
    if not rest:
        return 1.0
    try:
        if "v" not in _generic_vectors:
            _generic_vectors["v"] = _embed(GENERIC_REQUESTS)
        protos, q = _generic_vectors["v"], _embed([rest])
    except Exception:  # noqa: BLE001 — no embeddings: the word rules decide
        return None
    if protos is None or q is None:
        return None
    return float((protos @ q[0]).max())


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
    lower = _COUNT.sub(" ", lower)                             # "the latest 5 news" asks for a number of stories, not a topic
    for m in mentions:                                         # the company the user named is the subject, not the topic
        lower = lower.replace(m.lower(), " ")
    skip = _STOPWORDS | {t.lower() for t in tickers} | {"wall", "street", "dow", "nasdaq", "s&p", "500", "jones", "week", "month", "day", "days", "past", "last"}
    names = {w for m in mentions for w in re.findall(r"[a-z0-9&]+", m.lower()) if len(w) >= 4}
    misspelt = lambda w: len(w) >= 4 and bool(difflib.get_close_matches(w, names, n=1, cutoff=0.75))      # noqa: E731  "nvdia" for NVIDIA
    return [w for w in re.findall(r"[a-z0-9&]+", lower) if w not in skip and len(w) > 1 and not misspelt(w)]


def parse_time(published: str | None) -> float | None:
    """A story's ISO publish time as a Unix timestamp; None if missing or unreadable."""
    try:
        return datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _when(published: str | None) -> str:
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (AttributeError, ValueError):
        return ""
    return f"{dt:%b} {dt.day}, {dt:%H:%M} UTC"


def format_story(s: dict, summary_chars: int = 220) -> str:
    """'- **Title** (Publisher, Oct 30, 01:17 UTC): summary', the summary cut to `summary_chars` (0 = the headline alone)."""
    summary = " ".join((s.get("summary") or "").split()) if summary_chars else ""
    if len(summary) > summary_chars:
        summary = summary[:summary_chars].rsplit(" ", 1)[0] + "…"
    byline = ", ".join(x for x in (s.get("publisher"), _when(s.get("published"))) if x)
    return f"- **{s['title']}**" + (f" ({byline})" if byline else "") + (f": {summary}" if summary else "")


SUMMARY_SYSTEM = (
    "You summarize one news article for a beginner investor. Write 2-3 plain sentences saying what the article reports: "
    "who did what, the key figures and dates, and why it matters to the companies named, using ONLY the article text "
    "given. Do not add facts, opinions, predictions or advice, do not start with 'The article', and do not repeat the "
    "headline word for word. If the text is only a one-line teaser, write one sentence from it. Reply with the summary only.")


def summarize_story(title: str, text: str) -> str | None:
    """An LLM's 2-3 sentence summary of a story's article text; None without an LLM or when the call fails."""
    from src.core.llm import ask_llm
    reply = ask_llm(SUMMARY_SYSTEM, f"Headline: {title}\n\nArticle text:\n{text}")
    return " ".join(reply.split()) if reply else None


def story_source(s: dict) -> dict:
    return {"id": f"news:{s.get('story_id') or s['id']}", "title": f"{s['title']} ({s['publisher']})" if s.get("publisher") else s["title"],
            "url": s["url"]}
