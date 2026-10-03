"""Intent classification + entity extraction for the orchestrator.
`classify` is the keyword/regex fallback (spec §5.3) used when no LLM is available or its reply can't be parsed."""
import json
import re

from src.core.market_service import INSTRUMENTS

INTENT_PATTERNS = {
    "tax": r"\b(tax|taxes|taxable|401\(?k\)?|ira|roth|capital gains?|deduction)\b",
    "portfolio": r"\b(my portfolio|my holdings|my investments|allocation|diversif\w*|rebalanc\w*|expense ratio)\b",
    "market": r"\b(watchlist|price of|quote|stock market|market today|index|indices|s&p|nasdaq|dow|trend|moving average)\b",
    "goal": r"\b(goal|retire\w*|save for|saving for|how much (should|do) i (save|invest)|down payment|college|nest egg)\b",
    "news": r"\b(news|headlines?|latest (on|about|news)|what happened|what('s| is| has been| have been)? (happening|said|going on)|in the news|"
            r"(recent|latest) (updates?|developments?|reports?) (on|about|in))\b",
    "calc": r"\b(calculate|calculation|compute|work out|how much (will|would|do|does) .{0,40}\b(grow|be worth|have|cost|pay)|"
            r"how long (will|would|does|to) .{0,30}doubl\w*|doubl\w* my money|monthly payment|grow to|be worth in|"
            r"real return|apy|current yield)\b",
}
INTENTS = ["qa", "portfolio", "market", "news", "goal", "tax", "calc"]
AGENT_FOR_INTENT = {"qa": "Finance Q&A", "portfolio": "Portfolio Analysis", "market": "Market Analysis",
                    "goal": "Goal Planning", "tax": "Tax Education", "calc": "Calculator", "example": "Calculator", "news": "News", "clarify": "Finnie"}

COMPANY_ALIASES = {"apple": "AAPL", "microsoft": "MSFT", "nvidia": "NVDA", "jpmorgan": "JPM", "johnson & johnson": "JNJ"}
INDEX_ALIASES = {"s&p 500": "^GSPC", "s&p": "^GSPC", "nasdaq": "^IXIC", "dow jones": "^DJI", "the dow": "^DJI", "dow": "^DJI"}
_LEADING = re.compile(r"^\s*(please\s+)?(can you |could you )?(what('s| is| are| does| do)|who is|how (does|do|is|are)|"
                      r"explain|tell me about|define|what do you mean by)\s+(an?\s+|the\s+)?", re.I)
_PRONOUN = re.compile(r"\b(that|it|this|those|they|them|these)\b", re.I)


# Cues that must be case-sensitive (tickers) or need structure (amounts + horizons); these are NOT run with IGNORECASE.
_TICKER_CUE = re.compile(r"\$[A-Z]{1,5}\b|\b[A-Z]{2,5}\s+(stock|shares|price)\b|\bhow is\s+[A-Z]{2,5}\b")
_GOAL_CUE = re.compile(r"(\$[\d,.]+\s*(k|m|million|thousand)?\b.*\b\d{1,2}\s*(years?|yrs?)\b|\b\d{1,2}\s*(years?|yrs?)\b.*\$[\d,.]+|"
                       r"\bsaving\s+\$|\$[\d,.]+\s*(a|per|/|each)\s*month)", re.I)


def classify(text: str) -> list[str]:
    found = [i for i, p in INTENT_PATTERNS.items() if re.search(p, text, re.IGNORECASE)]
    if "market" not in found and (_TICKER_CUE.search(text) or extract_entities(text)["tickers"]):
        found.append("market")
    if "goal" not in found and "calc" not in found and _GOAL_CUE.search(text):    # "$X ... N years" is a calculation if asked as one
        found.append("goal")
    return found or ["qa"]


_ADVICE_REQUEST = re.compile(r"\bshould i (buy|sell|invest|put|move|dump|hold|short|switch)\b|\b(good|right) time to (buy|sell|invest)\b|"
                             r"\b(worth|good) (buying|selling)\b|\bwhat should i (buy|sell|invest)\b", re.I)


def is_advice_request(text: str) -> bool:
    return bool(_ADVICE_REQUEST.search(text))


def is_gibberish(text: str) -> bool:
    return not re.findall(r"[A-Za-z]{2,}", text)


def clean_topic(text: str) -> str:
    text = _LEADING.sub("", text.strip()).strip(" ?!.")
    return re.sub(r"\b(mean|work|works)$", "", text, flags=re.I).strip() or text


def _amount(num: str, unit: str | None) -> float:
    value = float(num.replace(",", ""))
    mult = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}.get((unit or "").lower(), 1)
    return value * mult


def extract_entities(text: str, history: list[dict] | None = None) -> dict:
    lower = text.lower()
    tickers = [t for t in re.findall(r"\$?\b([A-Z]{2,5})\b", text) if t in INSTRUMENTS and not t.startswith("^")]
    tickers += [sym for name, sym in COMPANY_ALIASES.items() if name in lower]
    indices = []
    for name, sym in INDEX_ALIASES.items():
        if name in lower and sym not in indices:
            indices.append(sym)
    amounts = [(_amount(m.group(1), m.group(2)), m.end()) for m in
               re.finditer(r"\$\s?([\d,]+(?:\.\d+)?)\s*(k|m|thousand|million)?\b", text, re.I)]
    monthly = next((a for a, end in amounts if re.match(r"\s*(/|per|a|each)?\s*(month|mo\b|monthly)", lower[end:end + 15])), None)
    target = max((a for a, _ in amounts if a != monthly), default=None)
    years = re.search(r"\b(\d{1,2})\s*(?:years?|yrs?)\b", lower)

    topic = clean_topic(text)
    prev_user = next((m["content"] for m in reversed(history or []) if m["role"] == "user"), None)
    if prev_user and _PRONOUN.search(text) and len(topic.split()) <= 8:      # follow-up like "how is that different from bonds?"
        topic = " ".join(f"{clean_topic(prev_user)} {_PRONOUN.sub('', topic)}".split())
    return {"tickers": list(dict.fromkeys(tickers)), "indices": indices, "wiki_query": topic,
            "advice_request": is_advice_request(text), "target_amount": target, "monthly_amount": monthly, "years": int(years.group(1)) if years else None}


def parse_llm_intents(reply: str) -> tuple[list[str], float] | None:
    """Parse {"intents": [...], "confidence": 0-1} from an LLM reply; None if unusable."""
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        intents = [i for i in data.get("intents", []) if i in INTENTS]
        return (intents, float(data.get("confidence", 1))) if intents else None
    except (ValueError, TypeError, AttributeError):
        return None
