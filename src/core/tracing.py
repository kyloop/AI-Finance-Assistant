"""Langfuse tracing: each chat turn becomes one trace, with a span per graph node and per LLM call.

Needs LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env (LANGFUSE_BASE_URL picks the region) and `langfuse.enabled` in
config.yaml; without them, or without the langfuse package, `run_callbacks()` is empty and nothing is sent. Tests remove
the keys, so they never reach the API.

What leaves the app: personal fields (holdings, profile, saved goal, chat history) are replaced by "<masked>" before a
span is sent, and the session id, which is the only key to a session's data, is sent as a hash that still groups a
session's turns. Text the agents write from that data (e.g. the Portfolio agent's "worth about $X") is not masked."""
from __future__ import annotations

import hashlib
import logging
import os
from functools import lru_cache

from src.core.config import get_config

log = logging.getLogger(__name__)

MASKED_KEYS = frozenset({"holdings", "profile", "saved_goal", "history"})


def tracing_enabled() -> bool:
    return bool((get_config().get("langfuse") or {}).get("enabled", True)) and bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def mask(*, data, **_):
    """Langfuse mask function: blank the personal fields wherever they appear in a span's input, output or metadata."""
    if isinstance(data, dict):
        return {k: "<masked>" if k in MASKED_KEYS else mask(data=v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [mask(data=v) for v in data]
    return data


def session_hash(session_id) -> str:
    """Stable, non-reversible stand-in for a session id: same session, same hash, but it can't open the session."""
    return hashlib.sha256(str(session_id).encode()).hexdigest()[:16]


@lru_cache
def _client():
    """The process's one Langfuse client, created with the mask so every handler's spans pass through it."""
    from langfuse import Langfuse
    return Langfuse(mask=mask)


def run_callbacks() -> list:
    """LangChain callbacks for one graph run: a Langfuse handler, or none when tracing is off or unavailable."""
    if not tracing_enabled():
        return []
    try:
        from langfuse.langchain import CallbackHandler
        _client()
        return [CallbackHandler()]
    except ImportError as e:
        log.warning("LANGFUSE keys are set but tracing is off: %s (pip install langfuse langchain)", e)
    except Exception:  # noqa: BLE001 — tracing must never stop a chat
        log.exception("langfuse setup failed; tracing is off for this turn")
    return []


def run_metadata(session_id=None, conversation_id=None) -> dict:
    """Groups a session's turns in Langfuse (Sessions view) and tags each trace with its conversation."""
    meta: dict = {"langfuse_tags": ["finnie-chat"]}
    if session_id is not None:
        meta["langfuse_session_id"] = session_hash(session_id)
    if conversation_id is not None:
        meta["conversation_id"] = str(conversation_id)
    return meta


def flush() -> None:
    """Send buffered spans before the process exits (spans are exported in the background)."""
    if tracing_enabled() and _client.cache_info().currsize:
        try:
            _client().flush()
        except Exception:  # noqa: BLE001 — tracing must never break shutdown
            log.exception("langfuse flush failed")
