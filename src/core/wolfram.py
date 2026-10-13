"""Wolfram|Alpha LLM API client: supplies formulas for the Calculator agent's equations, for calculations its Python
functions don't cover (IRR of a series of cash flows, solving for a rate or a number of years...).

Only the symbolic "solve <equation> for <unknown>" is sent, never the numbers, the user's message or the conversation;
src/core/equations.py puts the numbers into the formula and computes the result. Needs WOLFRAM_APP_ID (or
WOLFRAM_ALPHA_APP_ID) in .env (an AppID from developer.wolframalpha.com) and `wolfram.enabled` in config.yaml; without them
`wolfram_enabled()` is False and the Calculator solves its equations numerically. Tests inject a fake with
`set_wolfram_client` and never reach the network."""
from __future__ import annotations

import os
import re

import httpx

from src.core.config import get_config

API_URL = "https://www.wolframalpha.com/api/v1/llm-api"


class WolframUnavailable(Exception):
    """Network trouble, a timeout, a bad AppID or any other failure: the caller falls back to asking the user."""


class WolframNoResult(Exception):
    """Wolfram|Alpha understood nothing it could compute from the query (HTTP 501)."""


_client = None                     # tests: fn(query) -> response text, or raise WolframNoResult / WolframUnavailable


def set_wolfram_client(fn) -> None:
    """Tests inject `fn(query) -> LLM API response text`; None restores the real API."""
    global _client
    _client = fn


def _app_id() -> str:
    return os.environ.get("WOLFRAM_APP_ID") or os.environ.get("WOLFRAM_ALPHA_APP_ID") or ""


def wolfram_enabled() -> bool:
    cfg = get_config().get("wolfram") or {}
    return bool(cfg.get("enabled", True)) and (_client is not None or bool(_app_id()))


def _fetch(query: str, transport: httpx.BaseTransport | None = None) -> str:
    cfg = get_config().get("wolfram") or {}
    params = {"input": query, "appid": _app_id(), "maxchars": int(cfg.get("max_chars", 2000))}
    try:
        with httpx.Client(timeout=float(cfg.get("timeout_seconds", 10)), transport=transport) as http:
            r = http.get(API_URL, params=params)
    except httpx.HTTPError as e:
        raise WolframUnavailable(type(e).__name__) from e
    if r.status_code == 501:
        raise WolframNoResult(query)
    if r.status_code == 403:
        raise WolframUnavailable("AppID rejected (check WOLFRAM_APP_ID)")
    if r.status_code != 200:
        raise WolframUnavailable(f"HTTP {r.status_code}")
    return r.text


_HEADING = re.compile(r"^([A-Z][^\n:]{1,60}):\s*$", re.M)
_LONG_DECIMAL = re.compile(r"(\.\d{8})\d+\.*")
_URL = re.compile(r"https://www\.wolframalpha\.com/input\?i=\S+")
RESULT_SECTIONS = ("Result", "Results", "Exact result", "Decimal approximation", "Solution", "Solutions", "Real solution",
                   "Real solutions", "Value")


def parse(text: str) -> dict:
    """The LLM API's text as {"interpretation", "result", "url", "sections"}: sections are "Heading:" lines followed by
    their content; the result is the first result-like section."""
    url = _URL.search(text)
    body_text = text.split("Wolfram|Alpha website result", 1)[0]     # the trailer: a link back to the website, not an answer
    sections, marks = {}, list(_HEADING.finditer(body_text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body_text)
        body = body_text[m.end():end].strip()
        if body and m[1] not in sections:
            sections[m[1]] = body
    result = next((sections[k] for k in RESULT_SECTIONS if k in sections), None)
    decimal = sections.get("Decimal approximation")
    if result and decimal and decimal != result:     # an exact form like (3/2)^(1/5) - 1: show its decimal value too
        result = f"{result} ≈ " + _LONG_DECIMAL.sub(r"\1...", decimal)
    if result is None:                       # no "Result" heading: the first section that isn't the echo of the query
        result = next((v for k, v in sections.items() if k not in ("Query", "Input", "Input interpretation") and not _URL.match(v)), None)
    return {"interpretation": sections.get("Input interpretation") or sections.get("Input"), "result": result,
            "url": url.group(0) if url else None, "sections": sections}


def ask_wolfram(query: str, transport: httpx.BaseTransport | None = None) -> dict:
    """Ask Wolfram|Alpha one computational query; returns parse()'s dict. Raises WolframNoResult or WolframUnavailable."""
    text = _client(query) if _client is not None else _fetch(query, transport)
    out = parse(text)
    if not out["result"]:
        raise WolframNoResult(query)
    return out
