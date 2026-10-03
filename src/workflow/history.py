"""The slice of the conversation that LLM prompts and follow-up heuristics see: the last `workflow.history_window` messages,
each cut to `workflow.history_chars` characters (config.yaml)."""
from __future__ import annotations

from src.core.config import get_config


def recent(history: list[dict] | None) -> list[dict]:
    """The last few messages, oldest first."""
    return (history or [])[-int(get_config()["workflow"].get("history_window", 4)):]


def transcript(history: list[dict] | None) -> str:
    """The recent messages as "role: text" lines for a prompt; empty when there are none."""
    chars = int(get_config()["workflow"].get("history_chars", 1000))
    return "\n".join(f"{m['role']}: {m['content'][:chars]}" for m in recent(history))
