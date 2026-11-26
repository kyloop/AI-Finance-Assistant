"""Conversation context: what a turn worked out, saved with its answer and carried into the next turn.

Each answer stores `{question, intents, companies, markets, levels, tab, symbol, period, facts}` (see `build`): the corrected question,
the companies and markets (and the levels they cover: company, sector, region, market, asset class) and period the agents used, and
the figures they reported, and the worked example (`scenario`) the answer went through, if any. The next turn starts from it instead of re-reading old
messages: the proofread node rewrites a follow-up ("compare to starbucks") into a complete question with it, and the
router, market agent and calculator fill what the new message leaves out (`carried`). A message that isn't a
follow-up starts afresh, so companies and periods don't leak into unrelated questions. A message that points at the screen
("what about this?") after the user switched tabs, or picked another symbol on the same tab, is about what they are now
looking at, not the earlier answer (`screen`)."""
from __future__ import annotations

import re
from datetime import date

MAX_COMPANIES = 3
KEEPS_SUBJECT = {"calc"}          # turns that work with the conversation's figures without changing what it is about

# Without an LLM: a short message that points back or leaves something out ("what about AAPL?", "which did better?")
_FOLLOW_UP = re.compile(r"\b(what about|how about|what if|and what|compare\w*|vs|versus|instead|too|also|same|"
                        r"it|its|they|them|their|those|these|that|this|both|either|which|better|worse|best|worst)\b", re.I)
FOLLOW_UP_MAX_WORDS = 12
# A follow-up that names a company but keeps the earlier ones ("news on MSFT too?", "and SBUX?"); comparisons count as well
ADDS_TO = re.compile(r"\b(too|also|as well|and|plus|compare\w*|vs|versus|which|both|either|better|worse|outperform\w*)\b", re.I)


# A message with no subject of its own ("show example", "tell me more", "why?") can only be about the conversation.
# Narrower than _FOLLOW_UP on purpose: "can you give an example of compound interest?" names its subject.
SUBJECTLESS = re.compile(
    r"^\W*(please\s+)?(?:(?:can|could) you\s+)?(?:(?:show|give|walk)(?: me)?(?: through)?(?: an?| another| some| more| the)?\s*"
    r"(?:example|examples|details?|more|steps?)|(?:explain|tell me)(?: it| that| this)?(?: more| further| again| in more detail)?"
    r"|more(?: details?)?|go on|continue|elaborate|why|how so|in what way|like what|such as)\W*$", re.I)
SUBJECTLESS_MAX_WORDS = 6


def subjectless(text: str) -> bool:
    return len((text or "").split()) <= SUBJECTLESS_MAX_WORDS and bool(SUBJECTLESS.match((text or "").strip()))


def looks_like_follow_up(text: str) -> bool:
    return subjectless(text) or (len(text.split()) <= FOLLOW_UP_MAX_WORDS and bool(_FOLLOW_UP.search(text)))


def points_back(text: str) -> bool:
    """Its wording leans on what came before, whatever its length."""
    return bool(_FOLLOW_UP.search(text) or ADDS_TO.search(text))


# A message that names the previous answer's case as its subject ("how would the tax change in this case?", "what about
# that scenario?", "what about tax here?"): it can only be about the earlier turn, whatever the model makes of it.
REFERS_BACK = re.compile(
    r"\b(in|for|with|under|about|on)\s+(this|that|the same|such an?|your)\s+(case|scenario|example|situation|one)\b(?!\s+stud)|"
    r"\b(this|that|the same|the above|your|the)\s+(case|scenario|example|situation)\b(?!\s+stud)|"
    r"\b(in|for)\s+(this|that)\b\s*[?.!]*$|"
    r"\b(what|how)\s+about\b.{0,40}\bhere\b|\bhere\s*[?.!]*$", re.I)


def refers_back(text: str) -> bool:
    return bool(REFERS_BACK.search(text or ""))


def carried(state: dict) -> dict:
    """The previous turn's context when this message follows on from it, else {}."""
    return (state.get("context_in") or {}) if state.get("follow_up") else {}


# A message that points at what is on screen: "what about this?", "explain this", "how is this stock doing?", "how am I doing?".
# "that", "it" and "they" are left out: they usually point back at the conversation, not the page.
_SCREEN_NOUN = r"(stock|share|fund|etf|company|ticker|plan|goal|portfolio|holding|chart|graph|table|page|tab|screen|one|data|number|figure)s?"
POINTS_AT_SCREEN = re.compile(
    rf"\b(this|these|current|selected)\s+{_SCREEN_NOUN}\b|"
    r"\b(this|these)\b(?=\s*([?.!,]|$|\s+(mean|means|say|says|show|shows|tell|is|are|look|looks|doing|going|work|works|"
    r"good|bad|ok|okay|right|normal|high|low)\b))|"
    r"\b(here|on screen|how am i doing|am i on track)\b", re.I)
SYMBOL_TABS = ("Live Market", "Research")     # tabs that show one symbol the chat can call "this" (App.tsx SYMBOL_TABS)
SCREEN_SHORT_WORDS = 6        # a message this short that points at the screen is only about the screen ("what about this?")


def screen_subject(state: dict) -> dict | None:
    """What the tab the user is on shows, as {intents, label, symbol}; None when it shows nothing the agents can read."""
    view = state.get("view") or {}
    tab, symbol = view.get("tab") or "", view.get("selected")
    if tab == "Portfolio" and state.get("holdings"):
        return {"intents": ["portfolio"], "label": "your portfolio on the Portfolio tab", "symbol": None}
    if tab == "Goals" and state.get("saved_goal"):
        return {"intents": ["goal"], "label": "your saved plan on the Goals tab", "symbol": None}
    if tab in SYMBOL_TABS and symbol:
        return {"intents": ["market"], "label": f"{symbol} on the {tab} tab", "symbol": symbol}
    return None


def screen(state: dict, text: str) -> dict | None:
    """The screen subject when this message is about what is on screen rather than the conversation: it points at the screen and
    either the user has moved since the last answer (another tab, or another symbol on the same tab) or there is no earlier
    answer to follow on from. A follow-up on the same tab and symbol keeps the conversation's context. `switched` says what
    the last answer was given on ("the Portfolio tab", "AAPL"), when the user has moved away from it."""
    if not POINTS_AT_SCREEN.search(text):
        return None
    subject = screen_subject(state)
    prev = state.get("context_in") or {}
    prev_tab, tab = prev.get("tab"), (state.get("view") or {}).get("tab")
    switched = None
    if prev_tab and tab and prev_tab != tab:
        switched = f"the {prev_tab} tab"
    elif subject and subject["symbol"] and prev.get("symbol") and prev["symbol"] != subject["symbol"]:
        switched = prev["symbol"]
    if subject is None or not (switched or not state.get("context_in")):
        return None
    return {**subject, "switched": switched}


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
    if ctx.get("markets"):
        lines.append("Markets: " + ", ".join(m["name"] for m in ctx["markets"]))
    if ctx.get("levels"):
        lines.append("Level: " + ", ".join(ctx["levels"]))
    if ctx.get("period"):
        lines.append(f"Period: {ctx['period']['label']} (from {ctx['period']['start']})")
    if ctx.get("tax"):                                # in full digits, so a rewritten follow-up keeps the user's amounts
        t = ctx["tax"]
        status = {"single": "single", "married_joint": "married filing jointly"}.get(t.get("filing_status") or "", "not given")
        lines.append(f"Tax estimate ({t.get('year')}, filing status {status}): "
                     + "; ".join(f"{i['text']} ({i['amount']:.0f}, {i['kind']})" for i in t.get("items") or [])
                     + (f"; federal total {t['total_federal']:.0f}" if t.get("total_federal") is not None else ""))
    if ctx.get("scenario"):                           # the worked example the answer gave, in full digits like the tax figures
        lines.append(scenario_line(ctx["scenario"]))
    for sym, f in (ctx.get("facts") or {}).items():
        bits = []
        if "price" in f:
            bits.append(f"price {_money(f['price'])}" + (f" on {f['as_of']}" if f.get("as_of") else ""))
        if "return" in f:
            moved = f" ({_money(f['start_price'])} → {_money(f.get('end_price'))})" if f.get("start_price") is not None else ""
            bits.append(f"{f.get('period', 'period')} return {f['return'] * 100:+.1f}%{moved}")
        # in full digits, which the calculator's no-invented-numbers guard reads ("NVIDIA's market cap at $215?")
        if f.get("market_cap"):
            bits.append(f"market cap ${f['market_cap']:,.0f}")
        if f.get("shares_outstanding"):
            bits.append(f"shares outstanding {f['shares_outstanding']:,.0f}")
        if f.get("trailing_pe") is not None:
            bits.append(f"P/E (trailing) {f['trailing_pe']:.2f}")
        if f.get("dividend_yield") is not None:
            bits.append(f"dividend yield {f['dividend_yield'] * 100:.2f}%")
        if bits:
            lines.append(f"{sym}: " + "; ".join(bits))
    return "\n".join(lines)


# ---------------------------------------------------------------- the answer's worked example (scenario)
# An answer that works through an example ("a $300,000 house with 20% down: save $60,000 over 5 years") saves it as
# {kind, goal_type, text, figures}: `text` is one line in words, `figures` {name: number} the amounts it used. kind is
# "savings_goal" (a target saved for over years; goal_type as on the Goals tab) or "example" (any other worked example).
SCENARIO_FIGURE_WORDS = {"home_price": "home price", "down_payment_pct": "down payment share", "target": "target",
                         "years": "years", "monthly": "a month", "current_savings": "already saved",
                         "annual_return": "assumed yearly return", "loan_amount": "loan", "loan_rate": "loan rate",
                         "loan_years": "loan term in years"}


def _figure(name: str, value) -> str:
    if not isinstance(value, (int, float)):
        return f"{name} {value}"
    if name.endswith("_pct") or name in ("annual_return", "rate", "loan_rate"):
        return f"{SCENARIO_FIGURE_WORDS.get(name, name.replace('_', ' '))} {value * 100:g}%"
    if name == "loan_years":
        return f"loan over {value:g} years"
    if name == "years":
        return f"{value:g} years"
    return f"{SCENARIO_FIGURE_WORDS.get(name, name.replace('_', ' '))} {value:.0f}"


def scenario_line(s: dict) -> str:
    """The scenario as one prompt line: its words, then each figure in full digits (the proofread check reads them)."""
    figures = "; ".join(_figure(k, v) for k, v in (s.get("figures") or {}).items())
    return f"Worked example in the previous answer: {s.get('text') or ''}" + (f" (figures: {figures})" if figures else "")


def scenario_numbers(s: dict | None) -> set[float]:
    """The scenario's amounts, as the user could have typed them (20% as 20, a 0.04 return as 4)."""
    out = set()
    for k, v in ((s or {}).get("figures") or {}).items():
        if isinstance(v, (int, float)):
            out.add(round(float(v), 2))
            if k.endswith("_pct") or k in ("annual_return", "rate", "loan_rate"):
                out.add(round(float(v) * 100, 2))
    return out


def with_scenario(question: str, ctx: dict | None) -> str:
    """A question that points back at the previous answer's worked example ("how would the tax change in this case?"),
    completed with it, when the rewrite left the example out: the agents after the proofreader see only the question."""
    s = (ctx or {}).get("scenario")
    if not s or not s.get("text"):
        return question
    have = {round(float(n.replace(",", "")), 2) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", question)}
    if scenario_numbers(s) and scenario_numbers(s) & have:
        return question                                   # it already names the example's figures
    return f"{question.rstrip().rstrip('?.!')} (for the earlier example: {s['text'].rstrip('.')})?"


def merge_turn(a: dict | None, b: dict | None) -> dict:
    """Reducer for what parallel agents report about this turn: companies are merged in order, facts per symbol."""
    out = dict(a or {})
    for k, v in (b or {}).items():
        if k == "companies":
            seen = {c["symbol"] for c in out.get("companies", [])}
            out["companies"] = [*out.get("companies", []), *(c for c in v if c["symbol"] not in seen)]
        elif k == "markets":
            seen = {m["key"] for m in out.get("markets", [])}
            out["markets"] = [*out.get("markets", []), *(m for m in v if m["key"] not in seen)]
        elif k == "levels":
            out["levels"] = list(dict.fromkeys([*out.get("levels", []), *v]))
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
    companies = turn.get("companies") or named
    markets = turn.get("markets") or [{"key": m["key"], "name": m["name"]} for m in e.get("markets") or []]
    levels = turn.get("levels") or e.get("levels") or []
    if not companies and not markets:                                         # nothing named this turn: keep the subject
        companies, markets, levels = prev.get("companies") or [], prev.get("markets") or [], prev.get("levels") or []
    companies, markets = companies[:MAX_COMPANIES], markets[:MAX_COMPANIES]
    symbols = {c["symbol"] for c in companies}
    facts = merge_turn({"facts": prev.get("facts") or {}}, {"facts": turn.get("facts") or {}})["facts"]
    return {"question": state.get("question", ""), "intents": state.get("intent") or [], "companies": companies, "markets": markets,
            "levels": levels,
            "tab": (state.get("view") or {}).get("tab") or None,              # so the next turn can tell the user switched tabs
            "symbol": (state.get("view") or {}).get("selected") or None,      # ... or picked another symbol on the same tab
            "period": turn.get("period") or prev.get("period"),
            # the tax agent's last estimate, for "what if I'm married?" (tax_calc): kept until a new estimate replaces it,
            # also through a question about something else; it is only used when a message may change it
            "tax": turn.get("tax") or prev.get("tax") or (state.get("context_in") or {}).get("tax"),
            # the worked example this answer gave (or, for a follow-up, the one it went on discussing): "how would the tax
            # change in this case?" is about it
            "scenario": turn.get("scenario") or state.get("answer_scenario") or state.get("scenario_now") or prev.get("scenario"),
            "facts": {s: f for s, f in facts.items() if s in symbols},
            # topic memory (mds/topic-memory.md): the topic node's choice when it ran, else only a follow-up stays in the
            # previous turn's topic. A calculation that doesn't point back ("how much will $10,000 grow at 7%?" after "what
            # is an ETF?") keeps the subject above but starts a topic of its own. None = a new topic, numbered after the
            # turn (topics.record_turn)
            "topic_id": (state["topic"].get("topic_id") if state.get("topic") else carried(state).get("topic_id")),
            "related": list((state.get("topic") or {}).get("related") or []),
            "linked": list((state.get("topic") or {}).get("linked") or []),
            "source_ids": list(dict.fromkeys(s["id"] for s in state.get("sources") or [] if isinstance(s, dict) and s.get("id")))}


# ---------------------------------------------------------------- a follow-up that changes the example
# "what would be the diff if I borrow 200000 from bank and pay 1.5 interest": the house example with that loan
_LOAN = re.compile(r"\b(borrow\w*|loan\w*|mortgage\w*|financ\w*|lend\w*)\b", re.I)
_AMOUNT = re.compile(r"\$?\s?(\d[\d,]*(?:\.\d+)?)\s*(k\b|thousand\b|m\b|million\b)?", re.I)
_RATE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*(?:%|percent\b|per cent\b|(?:a year |annual |yearly )?(?:interest|apr|rate)\b)|"
                   r"\b(?:at|rate of|interest of)\s+(\d{1,2}(?:\.\d+)?)\b(?!\s*(?:years?|yrs?|k\b|thousand))", re.I)
_TERM = re.compile(r"\b(\d{1,2})[- ]?(?:years?|yrs?)\b", re.I)


def scenario_change(text: str, s: dict | None, default_rate: float = 0.065, default_years: int = 30) -> dict | None:
    """The previous answer's house example with the loan the message describes, or None when it describes none. The home
    price stays; the loan replaces the mortgage, so the down payment to save becomes price − loan (and its monthly saving is
    recomputed at the example's return). `previous` keeps the example's figures before the change for the comparison."""
    if not s or s.get("kind") != "savings_goal" or s.get("goal_type") != "house" or not _LOAN.search(text or ""):
        return None
    f = dict(s.get("figures") or {})
    price = float(f.get("home_price") or 0) or (float(f["target"]) / float(f.get("down_payment_pct") or 0.2) if f.get("target") else 0)
    amounts = []
    for m in _AMOUNT.finditer(text):
        n = float(m.group(1).replace(",", ""))
        n *= {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}.get((m.group(2) or "").lower(), 1)
        if n >= 1000:
            amounts.append(n)
    if not price or not amounts:
        return None
    loan = max(amounts)
    if loan >= price:
        return None
    rm = _RATE.search(text)
    rate = float(rm.group(1) or rm.group(2)) / 100 if rm else None
    tm = _TERM.search(text)
    term = int(tm.group(1)) if tm and 1 <= int(tm.group(1)) <= 40 and int(tm.group(1)) != int(f.get("years") or 0) else None
    from src.core.calculators import project_goal
    years = int(f.get("years") or 5)
    target = price - loan
    monthly = project_goal(target, years, 0, 0, float(f.get("annual_return") or 0.04))["required_monthly"]
    before = s.get("previous") or {"target": f.get("target"), "monthly": f.get("monthly"),
                                   "loan_amount": f.get("loan_amount") or price - float(f.get("target") or 0),
                                   "loan_rate": f.get("loan_rate") or default_rate, "loan_years": f.get("loan_years") or default_years}
    f.update({"home_price": price, "target": target, "down_payment_pct": round(target / price, 4), "monthly": round(monthly),
              "loan_amount": loan, "loan_rate": rate if rate is not None else default_rate,
              "loan_years": term or default_years})
    assumed = [] if rate is not None else [f"the loan's rate isn't given: {default_rate * 100:g}% assumed"]
    rate_words = f"{f['loan_rate'] * 100:g}%"
    return {**s, "figures": f, "previous": before, "assumed": assumed, "changed": True,
            "text": f"saving ${target:,.0f} over {years} years (about ${monthly:,.0f} a month) for a ${price:,.0f} house, "
                    f"borrowing ${loan:,.0f} at {rate_words} over {f['loan_years']} years"}


def current_scenario(state: dict) -> dict:
    """The example this turn works with: the one the message changes, else the previous answer's for a follow-up."""
    return state.get("scenario_now") or carried(state).get("scenario") or {}
