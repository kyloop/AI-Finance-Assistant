"""Provider-agnostic chat model factory. The orchestrator works without an LLM (keyword router + extractive answers);
when a key is present the router and synthesizer use it. Providers are imported lazily so only the one you use
needs installing:  pip install langchain-anthropic | langchain-openai | langchain-google-genai"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from .config import get_config

log = logging.getLogger(__name__)

_PROVIDERS = {  # name -> (env var, pip package, import path)
    "anthropic": ("ANTHROPIC_API_KEY", "langchain-anthropic", ("langchain_anthropic", "ChatAnthropic")),
    "openai": ("OPENAI_API_KEY", "langchain-openai", ("langchain_openai", "ChatOpenAI")),
    "gemini": ("GOOGLE_API_KEY", "langchain-google-genai", ("langchain_google_genai", "ChatGoogleGenerativeAI")),
}
_override: dict = {}      # tests / callers can force a model (or None)
_health: dict = {"error": None}   # last LLM call outcome, so the UI can say "connected but failing"


def _friendly(e: Exception) -> str:
    msg = str(e)
    if "insufficient_quota" in msg or "credit" in msg.lower():
        return "The AI provider reports no credits remaining. Add credits or use a different API key."
    if "401" in msg or "invalid_api_key" in msg or "authentication" in msg.lower():
        return "The AI provider rejected the API key. Check the key in .env."
    if "429" in msg or "rate" in msg.lower():
        return "The AI provider is rate-limiting requests. Try again shortly."
    return f"The AI provider returned an error ({type(e).__name__})."


def set_llm(model) -> None:
    _override["llm"] = model


def clear_llm_override() -> None:
    _override.clear()
    _health['error'] = None
    get_llm.cache_clear()


@lru_cache
def get_llm():
    """Returns a LangChain chat model, or None when no provider is usable."""
    cfg = get_config()["llm"]
    provider = cfg.get("provider", "auto")
    if provider == "none":
        return None
    candidates = list(_PROVIDERS) if provider == "auto" else [provider]
    for name in candidates:
        env, package, (module, cls) = _PROVIDERS[name]
        if not os.getenv(env):
            continue
        try:
            chat = getattr(__import__(module, fromlist=[cls]), cls)
            return chat(model=cfg["models"][name], temperature=cfg.get("temperature", 0.2))
        except ImportError:
            log.warning("%s key found but `%s` is not installed; run: pip install %s", name, module, package)
        except Exception as e:  # bad key format, etc.
            log.warning("could not start %s model: %s", name, e)
    return None


def current_llm():
    return _override["llm"] if "llm" in _override else get_llm()


def llm_status() -> dict:
    llm = current_llm()
    if llm is None:
        return {"enabled": False, "provider": None, "model": None}
    model = getattr(llm, "model", None) or getattr(llm, "model_name", None) or type(llm).__name__
    return {"enabled": True, "provider": type(llm).__name__, "model": str(model), "last_error": _health["error"]}


def ask_llm(system: str, user: str) -> str | None:
    """One-shot call; returns None if there is no model or the call fails (callers fall back to non-LLM behaviour)."""
    llm = current_llm()
    if llm is None:
        return None
    try:
        reply = llm.invoke([("system", system), ("human", user)])
        text = reply.content if isinstance(reply.content, str) else "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in reply.content)
        _health["error"] = None
        return text.strip() or None
    except Exception as e:
        log.warning("LLM call failed: %s", e)
        _health["error"] = _friendly(e)
        return None
