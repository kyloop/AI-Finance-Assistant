"""Deterministic compliance checks applied to every answer (spec §4). Cheap regexes, not an LLM judge."""
import re

from src.core.config import DISCLAIMER

ADVICE_PATTERNS = [
    r"\byou\s+(should|must|need to|ought to)\s+(buy|sell|short|dump|invest in|put)\b",
    r"\b(i|we)\s+(recommend|suggest|advise)\s+(that\s+)?(you\s+)?(buy|sell|buying|selling)\b",
    r"\b(buy|sell)\s+(half|all|some|more)?\s*(of\s+)?your\b",
    r"\bguarantee[sd]?\b.{0,30}\b(returns?|profits?|gains?)\b",
    r"\bwill\s+(definitely\s+|certainly\s+)?(make|earn|return|grow)\b.{0,25}\d+\s*%",
]
REFUSAL_NOTE = "I can explain how these things work, but I can't tell you what to buy or sell."


def filter_advice(text: str) -> tuple[str, int]:
    """Drop sentences that read like personal investment advice or promised returns. Returns (text, removed_count)."""
    kept, removed = [], 0
    for block in text.split("\n"):
        sentences = re.split(r"(?<=[.!?])\s+", block)
        good = [s for s in sentences if not any(re.search(p, s, re.I) for p in ADVICE_PATTERNS)]
        removed += len(sentences) - len(good)
        kept.append(" ".join(good))
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    if removed:
        cleaned = f"{cleaned}\n\n{REFUSAL_NOTE}".strip()
    return cleaned, removed


def finalize(text: str) -> tuple[str, int]:
    cleaned, removed = filter_advice(text)
    return f"{cleaned}\n\n{DISCLAIMER}", removed
