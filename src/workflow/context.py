"""Conversation context: what a turn worked out, saved with its answer and carried into the next turn.

Each answer stores `{question, intents, companies, period, facts}` (see `build`): the corrected question, the companies
and period the agents used, and the figures they reported. The next turn starts from it instead of re-reading old
messages: the proofread node rewrites a follow-up ("compare to starbucks") into a complete question with it, and the
router, market agent and calculator fill what the new message leaves out (`carried`). A message that isn't a
follow-up starts afresh, so companies and periods don't leak into unrelated questions."""
from __future__ import annotations

import re
from datetime import date

MAX_COMPANIES = 3
KEEPS_SUBJECT = {"calc"}          # turns that work with the conversation's figures without changing what it is about

# Without an LLM: a short message that points back or leaves something out ("what about AAPL?", "which did better?")
_FOLLOW_UP = re.compile(r"\b(what about|how about|and what|compare\w*|vs|versus|instead|too|also|same|"
                        r"it|its|they|them|their|those|these|that|this|both|either|which|better|worse|best|worst)\b", re.I)
FOLLOW_UP_MAX_WORDS = 12
# A follow-up that names a company but keeps the earlier ones ("news on MSFT too?", "and SBUX?"); comparisons count as well
ADDS_TO = re.compile(r"\b(too|also|as well|and|plus|compare\w*|vs|versus|which|both|either|better|worse|outperform\w*)\b", re.I)


def looks_like_follow_up(text: str) -> bool:
    return len(text.split()) <= FOLLOW_UP_MAX_WORDS and bool(_FOLLOW_UP.search(text))


def carried(state: dict) -> dict:
    """The previous turn's context when this message follows on from it, else {}."""
    return (state.get("context_in") or {}) if state.get("follow_up") else {}


def period_of(ctx: dict) -> tuple[date, str] | None:
    p = ctx.get("period") or {}
    try:
        return date.fromisoformat(p["start"]), p["label"]
    except (KeyError, TypeError, ValueError):
        return None


def _money(x) -> str:
    return f"${x:,.2f}" if isinstance(x, (int, float)) else "?"


def describe(ctx: dict | None) -> str:
    """The context as short lines for a prompt; empty when there is none."""
    if not ctx:
        return ""
    lines = []
    if ctx.get("question"):
        lines.append(f"Previous question: {ctx['question']}")
    if ctx.get("companies"):
        lines.append("Companies: " + ", ".join(f"{c.get('name') or c['symbol']} ({c['symbol']})" for c in ctx["companies"]))
    if ctx.get("period"):
        lines.append(f"Period: {ctx['period']['label']} (from {ctx['period']['start']})")
    for sym, f in (ctx.get("facts") or {}).items():
        bits = []
        if "price" in f:
            bits.append(f"price {_money(f['price'])}" + (f" on {f['as_of']}" if f.get("as_of") else ""))
        if "return" in f:
            bits.append(f"{f.get('period', 'period')} return {f['return'] * 100:+.1f}% ({_money(f.get('start_price'))} → {_money(f.get('end_price'))})")
        if bits:
            lines.append(f"{sym}: " + "; ".join(bits))
    return "\n".join(lines)


def merge_turn(a: dict | None, b: dict | None) -> dict:
    """Reducer for what parallel agents report about this turn: companies are merged in order, facts per symbol."""
    out = dict(a or {})
    for k, v in (b or {}).items():
        if k == "companies":
            seen = {c["symbol"] for c in out.get("companies", [])}
            out["companies"] = [*out.get("companies", []), *(c for c in v if c["symbol"] not in seen)]
        elif k == "facts":
            facts = dict(out.get("facts") or {})
            for sym, f in v.items():
                facts[sym] = {**facts.get(sym, {}), **f}
            out["facts"] = facts
        else:
            out[k] = v
    return out


def build(state: dict) -> dict:
    """The context to save with this answer: this turn's companies, period and figures, falling back to the carried ones
    for a follow-up (so "which did better?" keeps both companies and the period for the turn after)."""
    prev, turn = carried(state), state.get("turn_context") or {}
    if not prev and set(state.get("intent") or []) <= KEEPS_SUBJECT:         # "if SBUX rose 2%…": a sum about the same subject
        prev = state.get("context_in") or {}
    e = state.get("entities") or {}
    named = [{"symbol": c["symbol"], "name": c.get("name") or c["symbol"]} for c in e.get("companies") or []]
    named += [{"symbol": t, "name": t} for t in e.get("tickers") or [] if all(t != c["symbol"] for c in named)]
    companies = (turn.get("companies") or named or prev.get("companies") or [])[:MAX_COMPANIES]
    symbols = {c["symbol"] for c in companies}
    facts = merge_turn({"facts": prev.get("facts") or {}}, {"facts": turn.get("facts") or {}})["facts"]
    return {"question": state.get("question", ""), "intents": state.get("intent") or [], "companies": companies,
            "period": turn.get("period") or prev.get("period"),
            "facts": {s: f for s, f in facts.items() if s in symbols}}
