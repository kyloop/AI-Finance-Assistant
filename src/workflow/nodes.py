"""LangGraph nodes: router -> agents (parallel) -> verifier -> research / replan -> ... -> synthesizer -> compliance (see
graph.py). Every agent node is wrapped so a failure is recorded in state instead of crashing the graph (spec §5.3 fallbacks)."""
from __future__ import annotations

import difflib
import json
import logging
import re
from datetime import date, datetime, timezone
from functools import wraps

from langchain_core.runnables import RunnableConfig
from sqlalchemy.orm import Session as DBSession

from src.core import calc_plan as PLAN
from src.core.calculators import analyze_portfolio, project_goal
from src.core.config import get_config
from src.core.llm import ask_llm, current_llm
from src.core.market_service import SymbolNotFound
from src.core.portfolio_data import portfolio_dividends, portfolio_history, portfolio_instruments, with_purchase_prices
from src.core.tavily import WebSearchUnavailable, web_news, web_news_enabled, web_search, web_search_enabled
from src.kb.wiki import WikiUnavailable
from src.rag import markets as MK

from . import calc as CALC
from . import calc_pipeline as CP
from . import context as CTX
from . import history as H
from . import market_tools as MT
from . import news as NEWS
from . import portfolio_report as PR
from . import router as R
from . import symbols as SYM
from . import tax_calc as TAXC
from . import tax_tools as TT
from . import tax_whatif as TW
from . import topics as TOP
from .jsonreply import first_json
from .safety import finalize
from .state import AgentOutput, FinanceState
from .tools import (industry_peers, is_finance, kb_fetch, kb_search, news_index_now, news_latest, news_recent, news_search, story_articles, wiki_search,
                    wiki_topic)

log = logging.getLogger(__name__)

WORDS_BY_LEVEL = {"beginner": 1.0, "intermediate": 0.7, "advanced": 0.4}     # more experienced readers need less explanation
LENGTH_BY_LEVEL = {"beginner": "explain terms in plain words, with a short example if the context has one",
                   "intermediate": "skip the basic definitions and keep it to a short paragraph or a few bullets",
                   "advanced": "assume the basics are known: give only the key points, in two or three sentences or bullets"}
SYMBOL_OK = re.compile(r"^[A-Z0-9.\-=^]{1,15}$")
ORDER = ["portfolio", "market", "news", "calc", "goal", "tax", "qa", "example", "clarify", "read_only", "off_topic"]
FALLBACK_MESSAGE = "I'm having trouble answering that right now. Please try again in a moment."
CLARIFY_MESSAGE = ("I didn't quite catch that. You could ask things like “What is an ETF?”, “How does a Roth IRA work?”, "
                   "“What is the S&P 500 doing?” or “Is my portfolio diversified?”")


def _db(config: RunnableConfig):
    return (config or {}).get("configurable", {}).get("db")


def _out(agent: str, content: str, *, sources=None, data_info=None, confidence="high", trace: str = "", error=None,
         status: str = "answered", **extra) -> dict:
    o: AgentOutput = {"agent": agent, "content": content, "sources": sources or [], "data_info": data_info,
                      "confidence": confidence, "error": error, "status": status, **extra}
    return {"agent_outputs": {agent: o}, "trace": [trace] if trace else []}


def safe(agent: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(state: FinanceState, config: RunnableConfig):
            try:
                return fn(state, config)
            except Exception as e:  # noqa: BLE001 — contain every failure, report it in state
                log.exception("%s node failed", agent)
                res = _out(agent, "", confidence="low", error=str(e), trace=f"{agent}: failed ({type(e).__name__})")
                res["errors"] = [f"{agent}: {type(e).__name__}"]
                return res
        return wrapper
    return deco


# ---------------------------------------------------------------- proofread
PROOFREAD_SYSTEM = (
    "You are the proofreader in front of a personal-finance assistant. Rewrite the user's latest message with spelling, grammar and "
    "abbreviations fixed, so the agents after you can read it: \"yrs\" -> \"years\", \"mo\" -> \"months\", \"tsla\" -> \"TSLA\", "
    "\"nvdia\" -> \"NVIDIA\", \"wht abt\" -> \"what about\". Keep the meaning, every number and every ticker symbol; never answer "
    "the message, add facts or drop a request. Keep what each amount is: \"I'm borrowing $350,000 for a house\" is a $350,000 "
    "loan (\"a $350,000 mortgage\"), never \"a $350,000 house\"; a price, a loan, a deposit and a saving are different "
    "figures. If a word may be a ticker or name you don't know, leave it unchanged. "
    "If the message says what the user does NOT want, rewrite it as what they do want and leave out what they ruled out: "
    "\"I am not looking for DHSB news. I just want earlier news of today\" -> \"What were the market headlines earlier today?\"; "
    "\"not Apple, show me Microsoft's price\" -> \"What is Microsoft's stock price?\".\n"
    "You may be given the CONTEXT of the conversation so far (the previous question, its companies, period and figures) and the "
    "RECENT CONVERSATION. If the message continues it, or an earlier question there (it points back with \"it\", \"them\", "
    "\"which\", \"compare to\", \"what about X\", \"what if X is Y\", or leaves out a company, period or figure it relies on), "
    "rewrite it as a complete question that names them, using ticker symbols from the CONTEXT: "
    "\"compare to starbucks\" after TSLA over the last month -> \"Compare TSLA and Starbucks over the last month.\"; "
    "\"which did better?\" -> \"Which did better over the last month, TSLA or SBUX?\"; \"what if it's $20000?\" after how much "
    "$10,000 grows at 8% a year for 5 years -> \"How much does $20,000 grow at 8% a year for 5 years?\". \"Also\", \"on top of that\" or \"as well\" adds to the earlier situation, so keep every earlier figure: \"what if I "
    "also add $300 a month at 5%?\" after $25,000 at 7% for 20 years -> \"How much will $25,000 plus $300 a month grow to "
    "at 5% a year over 20 years?\". A reply to the "
    "assistant's last message (\"yes\", \"confirm\", \"the first one\", \"no, 6%\", or a value it asked for) answers it: rewrite it "
    "as the complete question the assistant proposed or asked about, with the value given; that is the question to answer "
    "itself (the calculation), never a question about the assumption it confirms: \"yes, confirm\" or \"yes, no extra "
    "contributions\" after \"You want to know how much $30,000 grows at 7% a year over 10 years; is 7% the yearly rate?\" -> "
    "\"How much does $30,000 grow at 7% a year over 10 years with no extra contributions?\", not \"Is 7% the yearly rate?\"; "
    "\"3%\" after \"what risk-free rate should I use?\" -> the earlier question with a 3% risk-free rate. "
    "A message about the previous answer's worked example (\"in this case\", \"that scenario\", \"here\") names the example "
    "with its figures: \"how would the tax change in this case?\" after an example of saving $60,000 over 5 years for a 20% "
    "down payment on a $300,000 house -> \"How would federal tax apply to saving $60,000 over 5 years for a 20% down payment "
    "on a $300,000 house?\". "
    "Set follow_up to true then. If the message starts a new topic, only correct it and set follow_up to false; never replace the subject "
    "it names with an earlier one (\"What's the latest technology sector news?\" after a question about the Pentagon is about the "
    "technology sector). A message that states every "
    "company, period and figure it needs is a new question even on the same subject (\"How much would $2,500 grow to at 7% a "
    "year over 10 years?\" after a 7% example). Take companies, periods and numbers "
    "only from the message, the CONTEXT or the RECENT CONVERSATION.\n"
    'Reply with ONLY JSON: {"question": "<the corrected message>", "follow_up": true}')
_TICKER_TOKEN = re.compile(r"\b[A-Z]{2,5}\b")
_NAME_WORD = re.compile(r"\b[A-Z][A-Za-z&.\-]+")          # a capitalised word: a ticker or a name the rewrite must not invent
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_LOAN_WORD = re.compile(r"\b(?:borrow\w*|loans?|lend\w*|owe[sd]?|owing|debts?|principal)\b", re.I)   # an amount that is a loan
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")         # "$20,000" and "$20000" are the same number
PROOFREAD_MAX_CHARS = 500                  # longer messages go to the router as typed
FOLLOW_UP_EXTRA_CHARS = 200                # room a completed follow-up may add (company names, the period)


def _typed_acronym_typo(original: str, market_key: str) -> bool:
    """A market found only through a short acronym alias typed in lower case ("how much tsx i need to pay": TSX, the
    Toronto index, for "tax"): a typo the proofreader may fix, unlike "TSX" in capitals or the market's name."""
    e = next((x for x in MK.entries() if x.get("key", x.get("symbol")) == market_key or x.get("symbol") == market_key), None)
    if e is None:
        return False
    names = [e.get("name") or "", *(e.get("aliases") or [])]
    hits = [a for a in names if re.search(rf"(?<!\w){re.escape(a)}(?!\w)", original, re.I)]
    return bool(hits) and all(a.isupper() and len(a) <= 4 and not re.search(rf"(?<!\w){re.escape(a)}(?!\w)", original) for a in hits)


def _proofread_ok(original: str, fixed: str, ctx: dict | None = None, recent: str = "") -> bool:
    """A correction, not a different message: no number or capitalised ticker lost, not much longer, and similar text; or,
    for a follow-up completed from the context or the recent conversation, anything added (tickers, numbers) comes from
    there."""
    if not fixed:
        return False
    original, fixed = _THOUSANDS.sub("", original), _THOUSANDS.sub("", fixed)
    if any(n not in fixed for n in _NUMBER.findall(original)):
        return False
    if _LOAN_WORD.search(original) and not _LOAN_WORD.search(fixed) and not re.search(r"\bmortgage of\b|\$[\d.]+[km]? mortgage", fixed, re.I):
        return False                                      # "borrowing $350,000 for a house" must not become "a $350,000 house"
    ruled_out = SYM.excluded(original)                    # "not looking for DHSB news": the rewrite may drop DHSB
    if any(t not in fixed for t in _TICKER_TOKEN.findall(original) if not original.isupper() and t.lower() not in ruled_out):
        return False
    lost = {m["key"] for m in MK.in_text(SYM.without_excluded(original))} - {m["key"] for m in MK.in_text(fixed)}
    if any(not _typed_acronym_typo(original, key) for key in lost):
        return False                                      # the market the message names is its subject: never swapped for an earlier one
    if ctx is not None:
        known = _THOUSANDS.sub("", f"{original} {CTX.describe(ctx)} {recent}").upper()
        return (len(fixed) <= len(original) + FOLLOW_UP_EXTRA_CHARS
                and all(t in known for t in _TICKER_TOKEN.findall(fixed))
                and set(_NUMBER.findall(fixed)) <= set(_NUMBER.findall(known)))     # whole numbers: 9 isn't in 14693.28
    if len(fixed) > 2 * len(original) + 40:
        return False
    if ruled_out:                                         # "not X, just Y" -> "Y?": a different sentence, so check what it names
        return not SYM.excluded(fixed) & ruled_out and not any(t.lower() in ruled_out for t in re.findall(r"[\w&.\-]+", fixed)) \
            and all(w.lower() in original.lower() for w in _NAME_WORD.findall(fixed.split(" ", 1)[-1]))
    return difflib.SequenceMatcher(None, original.lower(), fixed.lower()).ratio() >= 0.5


def _own_subject(q: str) -> bool:
    """The message names a market and nothing in it leans on the conversation ("What's the latest technology sector news?"): a new question."""
    return bool(MK.in_text(q)) and not CTX.points_back(q)


def _proofread_reply(q: str, ctx: dict | None, recent: str, topic_summary: str = "") -> tuple[str, bool] | None:
    """(corrected question, follow-up?) from the LLM; None if it gave nothing usable. A plain-text reply counts as a correction.
    `topic_summary` is the current topic so far (mds/topic-memory.md), so a follow-up two turns from its subject still resolves."""
    described = CTX.describe(ctx) + (f"\nTopic so far: {topic_summary}" if ctx and topic_summary else "") if ctx else ""
    prompt = ((f"CONTEXT:\n{described}\n\n" if ctx else "")
              + (f"RECENT CONVERSATION:\n{recent}\n\n" if recent else "") + f"Message: {q}")
    reply = ask_llm(PROOFREAD_SYSTEM, prompt)
    if not reply:
        return None
    data = _json(reply)
    if data is None:
        fixed = reply.strip().strip('"“”').strip()
        return (fixed, False) if fixed else None
    fixed = str(data.get("question") or "").strip()
    return (fixed, bool(data.get("follow_up")) and bool(ctx or recent)) if fixed else None


def _topic_summary(state: FinanceState, ctx: dict | None) -> str:
    """The summary of the topic the previous turn belongs to, when topic memory loaded it."""
    tid = (ctx or {}).get("topic_id")
    return next((t.get("summary") or "" for t in (state.get("topics_in") or {}).get("current") or [] if tid and t.get("topic_id") == tid), "")


def proofread_node(state: FinanceState, config: RunnableConfig):
    """Fix spelling, grammar and abbreviations before routing ("tsla last 10 yrs" -> "TSLA over the last 10 years"), and turn
    a follow-up into a complete question from the previous answer's context ("compare to starbucks" -> "Compare TSLA and
    Starbucks over the last month"). The rewrite replaces `question` for every later node; `original_question` keeps what
    the user typed. `follow_up` tells the router and agents to carry the context's companies, period and figures over.
    Without an LLM the message is kept and a follow-up is recognised by its wording (context.looks_like_follow_up).
    A message about what is on screen after a tab switch ("what about this?") is not a follow-up: `screen` says what it means."""
    q, ctx = state["question"], state.get("context_in") or None
    on_screen = CTX.screen(state, q)
    # "how would the tax change in this case?": about the previous answer whatever the model says, and completed with
    # its worked example when the rewrite leaves it out (the agents only see the question)
    back = not on_screen and bool(ctx) and CTX.refers_back(q)
    # "what if I borrow 200000 at 1.5%?": the example with that change, for the goal and tax agents (and the next turn)
    a = get_config().get("tax_assumptions") or {}
    changed = None if on_screen or not ctx else CTX.scenario_change(q, ctx.get("scenario"), float(a.get("mortgage_rate", 0.065)),
                                                                    int(a.get("mortgage_years", 30)))
    back = back or bool(changed)
    base = {"original_question": q, "screen": on_screen, "scenario_now": changed,
            "follow_up": not on_screen and bool(ctx or state.get("history")) and (CTX.looks_like_follow_up(q) or back)}
    note = " (follow-up: carrying the earlier context)" if base["follow_up"] else ""
    if on_screen:
        note = f" (about {on_screen['label']}" + (f"; switched from {on_screen['switched']})" if on_screen["switched"] else ")")
        ctx = None
    if not get_config()["workflow"].get("proofread", True) or current_llm() is None:
        if back and (completed := CTX.with_scenario(q, ctx)) != q:
            base["question"], note = completed, note + " (completed with the earlier example)"
        return {**base, "trace": [("proofread: skipped (no LLM)" if current_llm() is None else "proofread: off") + note]}
    if R.is_gibberish(q) or len(q) > PROOFREAD_MAX_CHARS:
        return {**base, "trace": ["proofread: left as typed" + note]}
    if on_screen:                                    # spelling only: the earlier conversation must not fill in "this"
        fixed = (_proofread_reply(q, None, "") or (q, False))[0]
        if fixed == q or not _proofread_ok(q, fixed):
            return {**base, "trace": ["proofread: no changes" + note]}
        return {**base, "question": fixed, "trace": [f"proofread: “{q}” → “{fixed}”{note}"]}
    recent = H.transcript(state.get("history"))
    got = _proofread_reply(q, ctx, recent, _topic_summary(state, ctx))
    if got is None:
        return {**base, "trace": ["proofread: no reply, left as typed" + note]}
    fixed, follow_up = got
    follow_up = (follow_up and not _own_subject(q)) or back
    if not _proofread_ok(q, fixed, (ctx or {}) if follow_up else None, recent if follow_up else ""):
        log.info("proofread rewrite rejected: %r -> %r", q, fixed)
        if back and (completed := CTX.with_scenario(q, ctx)) != q:
            return {**base, "question": completed, "trace": [f"proofread: rewrite rejected; “{q}” → “{completed}” (the earlier example)"]}
        return {**base, "trace": ["proofread: rewrite rejected, left as typed" + note]}
    if back:
        fixed = CTX.with_scenario(fixed, ctx)
    tag = " (follow-up of the previous question)" if follow_up else ""
    if fixed == q:
        return {**base, "follow_up": follow_up, "trace": [f"proofread: no changes{tag}"]}
    return {"question": fixed, "original_question": q, "follow_up": follow_up, "scenario_now": changed,
            "trace": [f"proofread: “{q}” → “{fixed}”{tag}"] + ([f"example changed: {changed['text']}"] if changed else [])}


# ---------------------------------------------------------------- router
ROUTER_SYSTEM = """You are the router for a personal-finance EDUCATION assistant. Decide which specialist agents must work on the user's message. Choose ALL agents whose job is needed to fully answer it.

AGENTS AND THEIR RESPONSIBILITIES
- qa: Explains financial concepts, definitions, how things work, WHY something happens, drivers/risks/pros-cons, and "what should I consider" questions. Knowledge-base driven. No live data, no user holdings.
- portfolio: Analyzes the USER'S OWN holdings (allocation, diversification, concentration, risk, performance of what they own). Only when the message refers to "my portfolio / my stocks / my holdings" or supplied holdings.
- market: Live and recent market DATA at every level. A company or fund: prices, quotes, valuation (P/E, dividend yield, market cap), performance over a period, comparisons between tickers. A sector: its return against the S&P 500 and how its largest companies moved. A sector's industries and what it is made of. A region or country: its stock index. The US market as a whole: the main indices, every sector ranked, the largest companies, today's most active stocks, whether the market is open. Asset classes: rates, commodities, currencies, crypto. Anything about the current STATE or PERFORMANCE of a security, sector, region, market or asset class.
- news: Recent headlines and developments ("latest", "recent", "what happened", "what's being reported", "any news") about a company, sector, region, topic or the whole market. Summarizes and gives context.
- goal: Builds a savings plan: monthly amount needed to reach a target amount by a date (risk appetite may apply). Only when they want a plan or "how much should I save". Also reads and explains the plan the user saved on the Goals tab whenever they ask about "my plan", "my goal(s)", "the plan" or whether they are on track.
- tax: Tax rules and account types (401k, IRA, Roth, HSA, 529), contribution limits, capital gains, deductions, tax treatment of investments. Also works out anyone's own taxes from their figures: income, taxable income, rental income and expenses, deductions, credits, the tax owed, what-ifs.
- calc: Computes a specific number: future value, loan/mortgage payment, doubling time, present value, real return, APY, bond yield, how long savings last with yearly withdrawals, or any other finance formula. Use when the user wants a figure calculated, not explained.

ROUTING RULES
0. qa is the DEFAULT. Use goal, portfolio or tax only when the message itself explicitly asks for that agent's job: a savings plan or how much to save (goal), an analysis of the user's own holdings (portfolio), tax treatment, tax rules or tax-advantaged accounts (tax). Mentioning retirement, saving, investing or an amount of money is not by itself a request for any of them: "I plan to retire with $1 million and need $50,000 a year" asks nothing about a savings plan, so it is not goal.
1. A message can need several agents. Return every intent whose responsibility is required; usually 1-3, never more than 4.
2. Performance or condition of a sector, region, market or asset class ("how are tech stocks doing", "just the tech sector?", "how is Japan's market doing", "state of the bond market") -> market. The market agent supplies the figures; add qa only when the message also asks for an explanation (what drives it, why it matters, what it means, how it works). Add news if they ask about recent events/causes or use "lately/this week/why now". The market as a whole, with no specific market named (a market update, overview, recap or insights, "how's the market", "what are stocks doing") -> market + news, even when phrased as a fragment rather than a question.
3. "Why did X move / why is X up/down" -> market + news (+ qa if they also ask what the concept means).
4. Split compound messages. If a message has several parts (joined by "and", "also", a comma, or a second question), classify EACH part separately and return the union of intents. A definition plus a live figure for a named company or index ("What is a P/E ratio and what is TSLA's?") -> qa + market. Never let one part hide the other. But "and" alone does not mean two agents: add an agent only if the second part needs a different agent's job.
5. A pure price/quote request ("price of NVDA") -> market only. A pure definition ("what is an ETF") -> qa only. Only use a single intent when the WHOLE message is that one thing. Do not add agents that contribute nothing.
6. "Should I buy/invest in X" or "is X a good investment" -> qa + market (+ portfolio if they mention their holdings). Education only, never personal advice.
7. Questions about what to consider or how something works (buying a house, mortgages, retirement accounts) -> qa. Add goal only if they ask for a savings plan, calc only if they ask for a number, tax only if tax treatment is asked.
8. "How much will I have / what is my payment" -> calc. A request to SEE a calculation worked through ("show me an example of how to calculate WACC", "how do you calculate APY? walk me through it") -> calc, even without numbers: the calculator explains the formula with sample numbers. "How much must I save each month to reach $X by <date>" -> goal. If both a number and an explanation are requested, calc + qa.
8b. A question about the user's own saved plan or goal ("explain my Goals plan", "am I on track?") -> goal. A figure worked out FROM that plan ("how much tax will I pay if the plan runs as planned?", "what if I add $200 a month?") -> goal + calc, plus the agent that explains the idea (tax for tax, qa otherwise): goal supplies the plan, calc the number, the other the explanation.
9. Tax-related investing questions ("how are dividends taxed", "Roth vs traditional") -> tax (+ qa if broad concept explanation is also requested).
10. Follow-ups: pronouns or references to the earlier subject ("them", "it", "the same sector", "grab the recent news") inherit the intents the conversation is about. A short "what about X?" repeats ALL intents of the previous question for the new subject (price and news for NVDA, then "what about NU?" -> market + news).
11. Anything unclear or very general about money/investing -> qa, with lower confidence.
12. Finnie can only READ. If the message asks Finnie itself to CHANGE something (add/remove/edit holdings, goals or the profile, place a trade, move money, change settings, data or the system) -> ["read_only"] alone. Asking whether or how to do it ("should I sell?", "how do I add holdings?") only needs reading and is routed as usual.
13. Finnie only covers personal finance, investing, markets, the economy and money matters. A message about anything else (sport, cooking, travel, health, celebrities, coding, homework, general trivia, jokes, poems or stories) -> ["off_topic"] alone. If one part of the message is about finance, route that part as usual and leave off_topic out. A follow-up to a finance conversation ("why?", "and the year before?") is not off-topic, and neither is a money question about any subject ("how much does a wedding cost to save for?", "is Nike stock up?").

EXAMPLES
"How is the tech sector doing?" -> ["market"]
"What about just the tech sector?" (after a question about the stock market) -> ["market"]
"How is the energy sector doing and what drives it?" -> ["market","qa"]
"How are bank stocks doing and what's in the news?" -> ["market","news"]
"Why are tech stocks down this week?" -> ["market","news"]
"What is a P/E ratio?" -> ["qa"]
"What is a P/E ratio? And what is TSLA's P/E ratio?" -> ["qa","market"]
"Explain dividend yield and show me KO's" -> ["qa","market"]
"What's a Roth IRA and what's the contribution limit this year?" -> ["tax"]
"Price of AAPL?" -> ["market"]
"Is my portfolio too concentrated in tech?" -> ["portfolio","qa"]
"What's the monthly payment on a $400k mortgage at 6.5% for 30 years?" -> ["calc"]
"I want $50k for a down payment in 4 years, how much per month?" -> ["goal"]
"Dana earns $90,000, gets $18,000 of rent and pays $6,000 of rental repairs and $4,000 of property tax on the rental. What is her net rental income?" -> ["tax"] (a tax situation: the tax agent works out its figures)
"If I split $600 a month equally into 3 accounts, how much goes into each and how much does it grow at 6%?" -> ["calc"] (two calculations, nothing to explain)
"Can you show me an example of how to calculate WACC?" -> ["calc"]
"I plan to retire with $1 million and need $50,000 a year" -> ["calc","qa"] (how long the money lasts, not a savings plan)
"How should I plan for retirement?" -> ["qa"]
"How much should I save each month to retire with $1 million in 25 years?" -> ["goal"]
"Roth IRA or 401k, and how are the gains taxed?" -> ["tax","qa"]
"Can you explain my Goals plan?" -> ["goal"]
"How much tax do I need to pay if my plan runs as planned?" -> ["goal","tax","calc"]
"Should I invest in real estate right now?" -> ["qa","market"]
"Put 20 Apple shares in my portfolio" -> ["read_only"]
"Who won the 2022 World Cup?" -> ["off_topic"]
"Give me a recipe for banana bread" -> ["off_topic"]

Reply with ONLY JSON: {"intents": ["qa"], "confidence": 0.0-1.0}. Intents must come from: qa, portfolio, market, news, goal, tax, calc, read_only, off_topic. Confidence reflects how sure you are that the intent SET is complete and correct."""


def _resolved_label(c: dict) -> str:
    """“NUU” → NU (closest match; also NUE, NUV): a guess at a mistyped ticker or name says so."""
    label = f"“{c['mention']}” → {c['symbol']}"
    if c.get("match") != "fuzzy":
        return label
    others = ", ".join(a["symbol"] for a in c.get("alternatives", []))
    return f"{label} (closest match{'; also ' + others if others else ''})"


def _with_listed_tickers(intents: list[str], text: str) -> list[str]:
    """A message that names a listed ticker ("what about the company with ticker SDEV?") needs the market agent, whatever the router guessed
    (after a Q&A turn the LLM reads "what about X?" as Q&A, and news alone never fetches the quote). The Q&A agent only knows the
    knowledge base, so in a short message it is replaced by the market agent; in a longer one it stays, as there may be a concept to explain too."""
    if "market" in intents or not (SYM.ticker_mentions(text) or SYM.lowercase_mentions(text)):     # "ho'ws tesla stock doing?" too
        return intents
    if set(intents) <= {"qa", "news"} and len(text.split()) <= SHORT_QUESTION_WORDS:
        return [*(i for i in intents if i != "qa"), "market"]
    return [*intents, "market"]


SHORT_QUESTION_WORDS = 12
_MARKET_STATE = re.compile(r"\b(doing|performing|trading|status|price|prices|rate|rates|quote|level|up|down|today|now|worth)\b", re.I)


def _with_market_words(intents: list[str], text: str) -> list[str]:
    """Without an LLM: a short question about a market's current state ("how is the yen doing today?", "gold price") needs the
    market agent, not Q&A; "what is forex?" stays a concept question."""
    if intents != ["qa"] or len(text.split()) > SHORT_QUESTION_WORDS or not _MARKET_STATE.search(text) or not MK.in_text(text):
        return intents
    return ["market"]


def _routed(res: dict, state: FinanceState) -> dict:
    """Add what a market or news question is about: its companies, markets ("forex", "gold"), topic and what it rules out. Found
    once here, with the conversation, so "nvdia" is corrected to NVIDIA and "them" means the company discussed earlier; the market
    and news agents read `entities["companies"]`, `["markets"]`, `["topic"]` and `["excluded"]`."""
    e = res["entities"]
    if not {"market", "news"} & set(res["intent"]):
        e["tickers"] = [t for t in e["tickers"] if t.lower() not in SYM.excluded(state["question"])]
        return res
    known = bool(e["tickers"] or e["indices"])                # the router's own list named them: no model call needed
    subj = SYM.subjects(state["question"], use_llm=not known, history=state.get("history"))
    ruled_out = subj["excluded"] | SYM.excluded(state.get("original_question") or "")     # the proofreader may have dropped it
    e["tickers"] = [t for t in e["tickers"] if t.lower() not in ruled_out]     # "not looking for DHSB news"
    e.update(markets=subj["markets"], topic=subj["topic"], excluded=sorted(ruled_out))
    if not known:
        e["companies"] = subj["companies"]
        if e["companies"]:
            res["trace"] = [*res["trace"], "resolved " + ", ".join(_resolved_label(c) for c in e["companies"])]
    if e["markets"]:
        res["trace"] = [*res["trace"], "markets: " + ", ".join(_market_label(m) for m in e["markets"])]
    return _with_sector_figures(_with_levels(_with_carried_companies(res, state)))


def _with_sector_figures(res: dict) -> dict:
    """News about a sector comes with how the sector has done, so the market agent runs too (`_sector_lines` shows the result)."""
    if "sector" not in res["entities"]["levels"] or "news" not in res["intent"]:
        return res
    res["entities"]["sector_figures"] = True
    if "market" not in res["intent"]:
        res["intent"] = [*res["intent"], "market"]
        res["trace"] = [*res["trace"], "sector news: adding the market agent for its performance"]
    return res


def _with_levels(res: dict) -> dict:
    """`entities["levels"]`: what the subjects (named or carried) cover, company to market (symbols.levels)."""
    e = res["entities"]
    indices = [MK.market(s) for s in e.get("indices") or [] if MK.entry(s)]
    e["levels"] = SYM.levels([*(e.get("companies") or []), *e.get("tickers", [])], [*(e.get("markets") or []), *indices])
    if e["levels"]:
        res["trace"] = [*res["trace"], "level: " + ", ".join(e["levels"])]
    return res


def _market_label(m: dict) -> str:
    return f"{m['name']} ({m['symbol']})" if m["symbol"] else f"{m['name']} (all {m['group']})"


def _carried_markets(prev: dict) -> list[dict]:
    """The previous answer's markets, rebuilt from their saved keys (a market dropped from markets.yaml since is skipped)."""
    out = []
    for m in prev.get("markets") or []:
        key = m["key"]
        try:
            out.append(MK.group(key.removeprefix("group:")) if key.startswith("group:") else MK.market(key))
        except (KeyError, TypeError):
            continue
    return out


def _with_carried_companies(res: dict, state: FinanceState) -> dict:
    """A follow-up uses the companies and markets the previous answer was about: all of them when it names none ("which did
    better?", "any news on it?"), and alongside the new one when it compares or adds ("compare to Starbucks", "news on MSFT too?")."""
    prev, e = CTX.carried(state), res["entities"]
    if not (prev.get("companies") or prev.get("markets")) or not {"market", "news"} & set(res["intent"]):
        return res
    new, new_markets = e.get("companies") or [], e.get("markets") or []
    have = {*e["tickers"], *e["indices"], *(c["symbol"] for c in new), *(m["key"] for m in new_markets)}
    if have and not CTX.ADDS_TO.search(state["question"]):
        return res
    ruled_out = set(e.get("excluded") or ()) | SYM.excluded(state["question"])
    add = [{**c, "mention": "(earlier)"} for c in prev.get("companies") or [] if c["symbol"] not in have and not SYM.is_excluded(c, ruled_out)]
    add = add[:max(0, CTX.MAX_COMPANIES - len(have))]
    if add:
        e["companies"] = [*add, *new]
        res["trace"] = [*res["trace"], "from the previous answer: " + ", ".join(c["symbol"] for c in add)]
    markets = [m for m in _carried_markets(prev) if m["key"] not in have and not SYM._ruled_out_market(m, ruled_out)]
    if markets:
        e["markets"] = [*markets, *new_markets][:CTX.MAX_COMPANIES]
        res["trace"] = [*res["trace"], "markets from the previous answer: " + ", ".join(m["name"] for m in markets)]
    return res


# Words that make a message about the user's own money. Without one, a market question keeps no portfolio intent: after
# "summary of my portfolio?" the LLM router sent "how about nvda vs market trending today?" to the portfolio agent too.
_OWN_MONEY = re.compile(r"\b(my|mine|i own|i hold|i have|i bought|our|portfolio|holdings?|positions?|diversif\w*|allocation|"
                        r"rebalanc\w*|am i)\b", re.I)


def _without_stray_portfolio(intents: list[str], state: FinanceState) -> list[str]:
    """Drop the portfolio intent the LLM router carried over from an earlier turn, when the message is a market question that
    never mentions the user's own holdings (the router's rule: portfolio only when the message asks for that job)."""
    q = f"{state.get('original_question') or ''} {state['question']}"
    if "portfolio" in intents and "market" in intents and not _OWN_MONEY.search(q):
        return [i for i in intents if i != "portfolio"]
    return intents


def _with_screen(intents: list[str], state: FinanceState) -> list[str]:
    """A message about the tab on screen also goes to the agent that reads it (portfolio, goal, market). A short one
    ("what about this?", "explain this") the router could only call Q&A goes to that agent alone."""
    on_screen = state.get("screen")
    if not on_screen:
        return intents
    if set(intents) <= {"qa"} and len(state["question"].split()) <= CTX.SCREEN_SHORT_WORDS:
        return list(on_screen["intents"])
    return list(dict.fromkeys([*intents, *on_screen["intents"]]))


# "how is my plan cost me on the tax?" asks for a figure as much as "how much tax?" does
_FIGURE_ASKED = re.compile(r"\b(how much|how many dollars|estimate|work out|calculat\w*|figure out|cost(s|ing)? me|owe|"
                           r"(do|will|would|must|should) i (need to |have to )?pay)\b", re.I)


_TAX_TOPIC = re.compile(r"\b(tax|taxes|taxed|taxable|irs|deduct\w*|itemi[sz]\w*|salt|401\(?k\)?|403\(?b\)?|\bira\b|roth|hsa|"
                        r"rmd|required minimum|capital gains?|gift tax|estate tax|w-?2|1099|withholding|refund|section 121|"
                        r"home[- ]sale|cost basis|adjusted basis)\b", re.I)


def _tax_scenario(text: str) -> bool:
    """Amounts of income or tax-deductible costs with tax words: someone's tax situation, whoever it's about."""
    return bool(TAXC.amounts(text) and _TAX_TOPIC.search(text) and TAXC._FIGURE.search(text))


def _tax_to_tax_agent(intents: list[str], state: FinanceState) -> list[str]:
    """A question about a tax rule goes to the tax agent rather than Q&A: it states this year's figures (the router LLM
    sent "What is the SALT deduction cap?" to Q&A, which repeated Wikipedia's out-of-date $10,000)."""
    q = f"{state.get('original_question') or ''} {state['question']}"
    if "qa" in intents and _TAX_TOPIC.search(q):            # with the tax agent there, Q&A would only repeat it
        return list(dict.fromkeys(["tax" if i == "qa" else i for i in intents]))
    return intents


def _with_income_tax(intents: list[str], state: FinanceState) -> list[str]:
    """"I earn $200,000 ... how much tax do I pay?" is the tax agent's: it works out the figure with its tools and explains
    each step, so the calculator and Q&A would only repeat it."""
    plain = set(intents) <= {"qa", "tax", "calc", "goal", "clarify"}
    typed = state.get("original_question") or state["question"]
    follows_estimate = plain and (bool(_last_estimate(state)) or TAXC.states_tax_figure(typed)
                                  or bool(TAXC.missing_amount(typed, None) and (state.get("context_in") or {}).get("tax")))
    # a whole tax situation with its figures ("David earns $120,000, rent received $30,000 ... his net rental income?"):
    # the router LLM sent it to the calculator, which can't place a dozen tax figures
    scenario = plain and (TAXC.is_scenario(typed) or TAXC.is_scenario(state["question"]))
    if not TAXC.asks_income_tax(state["question"]) and not follows_estimate and not scenario:
        if "tax" in intents and TW.TAX_FIGURE.search(state["question"]) and TAXC.amounts(state["question"]):
            return [i for i in intents if i not in ("calc", "qa")]  # Roth vs traditional for $10k, a sale's gain: the tax tools
        return intents
    rest = [i for i in intents if i not in ("tax", "calc", "qa")]
    if not R.refers_to_plan(state.get("original_question") or state["question"]):
        rest = [i for i in rest if i != "goal"]          # "retired", "my son's college": a tax question, not a savings plan
    return ["tax", *rest]


_GENERIC_TAX = {"tax", "taxes", "taxed", "taxable"}


def _about_the_example(typed: str) -> bool:
    """A tax question with no tax subject of its own ("how is that taxed?", "what about taxes?"), or one that points back
    at the earlier case: it asks about the example. "What about Roth IRA limits?" names its own subject."""
    found = {m.group(0).lower() for m in _TAX_TOPIC.finditer(typed)}
    return CTX.refers_back(typed) or bool(found) and found <= _GENERIC_TAX


def _example_tax_to_tax_agent(intents: list[str], state: FinanceState) -> list[str]:
    """A tax question about the previous answer's savings example ("how would the tax change in this case?") is the tax
    agent's alone: it works out the example's tax from its figures, and the goal agent would only repeat the example."""
    q = f"{state.get('original_question') or ''} {state['question']}"
    if state.get("scenario_now") and set(intents) <= {"qa", "tax", "calc", "goal"}:
        return ["goal", "tax"]               # the changed example: the plan's new figures, and what the change does to tax
    scen = CTX.carried(state).get("scenario") or {}
    if (scen.get("kind") != "savings_goal" or not _TAX_TOPIC.search(q) or not _about_the_example(state.get("original_question") or q)
            or not set(intents) <= {"qa", "tax", "calc", "goal"}):
        return intents
    return ["tax"]


def _without_stray_goal(intents: list[str], state: FinanceState) -> list[str]:
    """The goal agent only for a message about a goal or savings plan: the router LLM adds it to "I earn $200,000 ...
    how much tax do I pay?" (its "how much tax ... my plan" example), and with no plan saved the goal agent then asks for
    a target amount."""
    q = f"{state.get('original_question') or ''} {state['question']}"
    if "goal" not in intents or R.mentions_goal(q) or "goal" in (CTX.carried(state).get("intents") or []):
        return intents
    return [i for i in intents if i != "goal"] or ["qa"]


def _with_saved_plan(intents: list[str], state: FinanceState) -> list[str]:
    """A message about the user's own plan ("explain my Goals plan", "if the plan runs as planned") goes to the goal agent,
    which reads the plan saved on the Goals tab: the router LLM tends to call it Q&A, which has no way to see the plan."""
    q = f"{state.get('original_question') or ''} {state['question']}"
    if not state.get("saved_goal") or not R.refers_to_plan(q):
        return intents
    if "goal" not in intents:
        intents = ["goal"] if intents == ["qa"] else [*intents, "goal"]   # Q&A alone can't add anything about their plan
    if "calc" not in intents and "tax" not in intents and _FIGURE_ASKED.search(q) and re.search(r"\btax", q, re.I):
        intents = [*intents, "tax"]                  # a tax figure on the plan: the tax agent works it out per account
    elif "tax" in intents:
        intents = [i for i in intents if i != "calc"]    # the tax agent's tools give the plan's tax figures
    return intents


def router_node(state: FinanceState, config: RunnableConfig):
    res = _route(state)
    res["tried_agents"] = [n.removesuffix("_agent") for n in route_after_router(res)]       # replan never re-runs these
    return res


def _route(state: FinanceState) -> dict:
    text = state["question"]
    entities = R.extract_entities(text, state.get("history"))
    write = R.write_request(state.get("original_question") or text) or R.write_request(text)
    if write:                                       # checked before the LLM, so basic mode flags it too
        return {"intent": ["read_only"], "entities": {**entities, "write_request": write}, "router_mode": "keywords",
                "trace": [f"router: asks to change something ({write}) → read_only guard"]}
    if R.is_gibberish(text):
        return {"intent": ["clarify"], "entities": entities, "router_mode": "keywords", "trace": ["router: no words found → clarify"]}
    on_screen = state.get("screen")
    if on_screen and on_screen["symbol"]:            # "how does this compare to MSFT?" on AAPL: both
        entities["tickers"] = list(dict.fromkeys([on_screen["symbol"], *entities["tickers"]]))
    if current_llm() is not None:
        recent = "" if on_screen else H.transcript(state.get("history"))
        shown = f"On screen: {on_screen['label']}; \"this\" and \"here\" in the message mean it.\n\n" if on_screen else ""
        reply = ask_llm(ROUTER_SYSTEM, f"{shown}Recent conversation:\n{recent or '(none)'}\n\nMessage: {text}")
        parsed = R.parse_llm_intents(reply) if reply else None
        if parsed:
            intents, confidence = parsed
            if confidence < 0.3:
                return {"intent": ["clarify"], "entities": entities, "router_mode": "llm", "trace": [f"router (LLM): low confidence {confidence:.1f} → clarify"]}
            pending = ((state.get("context_in") or {}).get("tax") or {}).get("pending")
            if "read_only" in intents and pending and TAXC.amounts(state.get("original_question") or text):
                intents = ["tax"]                    # "about $12,000 a year": the answer to the tax agent's question, not a change
            if "read_only" in intents:
                return {"intent": ["read_only"], "entities": {**entities, "write_request": "data"}, "router_mode": "llm",
                        "trace": ["router (LLM): asks to change something → read_only guard"]}
            if intents == ["off_topic"] and _tax_scenario(text):
                intents = ["tax"]                    # "Sarah is a single taxpayer ... salary $95,000": a tax scenario, not off topic
            if intents == ["off_topic"]:
                return {"intent": ["off_topic"], "entities": entities, "router_mode": "llm",
                        "trace": ["router (LLM): not about finance → off_topic guard"]}
            intents = [i for i in intents if i != "off_topic"] or ["qa"]       # a finance part is answered; the rest is left out
            intents = _example_tax_to_tax_agent(_with_income_tax(_tax_to_tax_agent(_with_saved_plan(_with_screen(_without_stray_goal(_without_stray_portfolio(_with_listed_tickers(intents, text), state), state), state), state), state), state), state)
            return _routed({"intent": intents, "entities": entities, "router_mode": "llm", "trace": [f"router (LLM): {', '.join(intents)}"]}, state)
        log.warning("router LLM reply unusable; falling back to keywords")
    intents = _example_tax_to_tax_agent(_with_income_tax(_tax_to_tax_agent(_with_saved_plan(_with_screen(_with_listed_tickers(_with_market_words(R.classify(text), text), text), state), state), state), state), state)
    if intents == ["qa"] and CTX.carried(state).get("companies"):                 # "which did better?" after a market answer
        intents = ["market"]
    return _routed({"intent": intents, "entities": entities, "router_mode": "keywords", "trace": [f"router (keywords): {', '.join(intents)}"]}, state)


def _writes_from_notes() -> bool:
    """Whether the reply can use earlier chats' notes: only the LLM synthesizer reads them."""
    return current_llm() is not None


def topic_node(state: FinanceState, config: RunnableConfig):
    """Which topic the message belongs to (mds/topic-memory.md): the previous turn's for a follow-up or a message with no
    subject of its own; an older topic of this chat it names again ("back to Tesla"), whose subject, period and figures then
    fill in what the message leaves out; or a new topic, linked to earlier chats about the same thing, whose dated
    summaries reach the synthesizer as background. Runs after the router so it matches on the router's resolved entities.
    A no-op when the run has no topic memory (run_chat without topics)."""
    pool = state.get("topics_in")
    if pool is None:
        return {"trace": ["topic: no topic memory for this run"]}
    if (state.get("intent") or []) in (["read_only"], ["off_topic"], ["clarify"]):
        return {"trace": ["topic: guard reply, no topic"]}
    cfg = get_config().get("topics") or {}
    try:
        got = TOP.choose(state, pool, embed=TOP.embed, same_chat=float(cfg.get("same_chat_similarity", 0.8)),
                         earlier_chat=float(cfg.get("earlier_chat_similarity", 0.86)), max_linked=int(cfg.get("max_linked", 3)))
    except Exception as e:  # noqa: BLE001 — topic memory must never break a turn
        log.warning("topic node failed: %s", e)
        return {"trace": [f"topic: skipped ({type(e).__name__})"]}
    out = {"topic": {k: got[k] for k in ("action", "topic_id", "related", "linked")}, "trace": [got["note"]]}
    if got["action"] == "reopen":
        out.update(context_in=got["context"], follow_up=True)
    elif got["action"] == "continue" and not state.get("follow_up") and state.get("context_in"):
        out["follow_up"] = bool(CTX.subjectless(state.get("original_question") or state["question"]))      # rule 2 only
    if got.get("background") and _writes_from_notes():
        out["topic_background"] = got["background"]
    elif got["linked"]:                         # basic mode writes no reply from the notes: link the topics, don't claim to use them
        out["topic"]["linked"] = []
    return out


def route_after_router(state: FinanceState) -> list[str]:
    intents = state.get("intent") or ["qa"]
    if intents in (["clarify"], ["read_only"], ["off_topic"]):
        return intents
    nodes = {f"{i}_agent" for i in intents if i in R.INTENTS}
    return sorted(nodes) or ["qa_agent"]


# ---------------------------------------------------------------- agents
# Every agent output carries a status the verifier acts on:
#   answered   content answers (part of) the question
#   not_found  nothing usable yet; `query` (and `prefix`) tell the research node what to look up on Wikipedia
#   need_info  content is a follow-up question for the user; the verifier attaches `choices` to pick from
NOT_FOUND_MESSAGE = ("I couldn't find a reliable article on that, so I'd rather not guess. Could you rephrase, or name the "
                     "specific term (for example “index fund” or “compound interest”)?")
UNAVAILABLE_MESSAGE = "I couldn't reach my knowledge source just now, so I can't look that up. Please try again shortly."
TAX_PREFIX = "_I can explain how this works in general, not what you personally should do._\n\n"
GOAL_ASK = ("To sketch a savings plan I need a target amount and a time horizon, for example "
            "“I want $500,000 in 30 years, saving $500 a month”. You can also use the **Goals** tab.")
GOAL_CHOICES = ["What should I consider before making a big purchase like a house?",
                "I want to save $50,000 in 5 years. How much is that a month?"]
STARTER_CHOICES = ["What is an ETF?", "How does compound interest work?", "What is a bond?"]


def _words(state: FinanceState) -> int:
    level = state.get("profile", {}).get("knowledge_level", "beginner")
    return int(get_config()["workflow"]["wiki_max_words"] * WORDS_BY_LEVEL.get(level, 1.0))


def _not_found(agent: str, query: str, trace: str, prefix: str = "") -> dict:
    return _out(agent, "", status="not_found", query=query, prefix=prefix, confidence="low", trace=trace)


def _reranked(fresh: list[dict], earlier: list[dict], k: int) -> list[dict]:
    """A fresh search and the topic's earlier sections in one list, by similarity to the question, each chunk once."""
    seen, out = set(), []
    for h in sorted([*fresh, *earlier], key=lambda h: h.get("score", 0), reverse=True):
        key = (h.get("doc_id"), h.get("section"), h.get("piece"))
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out[:k]


LOCAL_SOURCE = "Finnie note, from the IRS"


def _origin(hit: dict) -> str:
    """Where a knowledge-base chunk comes from, for its source label: our own notes (rag.local_categories) or Wikipedia."""
    return LOCAL_SOURCE if hit.get("category") in (get_config()["rag"].get("local_categories") or {}) else "Wikipedia"


def _kb_answer(agent: str, state: FinanceState, query: str, prefix: str = "", searches: list[str] | None = None,
               categories: tuple[str, ...] | None = None) -> dict:
    """Answer from the knowledge base (Qdrant). not_found (→ research on Wikipedia) when the index is missing or failing,
    or the best match is below rag.min_score (the topic probably isn't indexed yet). `searches` replace the question as
    the search text (the tax agent's searches for a saved plan); their hits are merged by score."""
    cfg = get_config()["rag"]
    try:
        hits = kb_search(state["question"], categories=categories) if not searches else \
            _reranked([h for s in searches for h in kb_search(s, categories=categories)], [], cfg["top_k"])
        earlier = [i for i in CTX.carried(state).get("source_ids") or [] if i.startswith("kb:")]
        if earlier:                     # a follow-up: the sections that answered the topic before, scored against this question
            try:
                hits = _reranked(hits, kb_fetch(state["question"], earlier), cfg["top_k"])
            except Exception as e:  # noqa: BLE001 — the fresh search still answers
                log.warning("re-fetching the topic's sources failed: %s", e)
    except Exception as e:  # noqa: BLE001 — a broken index must not break Q&A
        log.warning("knowledge-base search failed: %s", e)
        return _not_found(agent, query, f"kb_search → failed ({type(e).__name__})", prefix)
    if not hits:
        return _not_found(agent, query, "kb_search → no index or no matches", prefix)
    top = hits[0]
    if top["score"] < cfg["min_score"]:
        return _not_found(agent, query, f"kb_search → best {top['doc_title']} ({top['score']:.2f}) below {cfg['min_score']}", prefix)
    if current_llm() is not None:          # the synthesizer writes the answer from all top-k chunks
        body = "\n\n".join(f"**{h['doc_title']} › {h['section']}**\n{h['text']}" for h in hits)
    else:                                  # extractive mode: the best chunk, trimmed to the reader's level
        words = _words(state)
        text = " ".join(top["text"].split()[:words]) + ("…" if len(top["text"].split()) > words else "")
        body = f"**{top['doc_title']}**\n\n{text}"
    sources, seen = [], set()
    for h in hits:
        key = (h["doc_id"], h["section"])
        if key in seen:
            continue
        seen.add(key)
        anchor = "" if h["section"] == "(lead)" else "#" + h["section"].split(" > ")[-1].replace(" ", "_")
        label = h["doc_title"] if h["section"] == "(lead)" else f"{h['doc_title']} › {h['section'].split(' > ')[-1]}"
        sources.append({"id": f"kb:{h['doc_id']}#{h['section']}", "title": f"{label} ({_origin(h)})",
                        "url": h["source_url"] + ("" if _origin(h) != "Wikipedia" else anchor)})
    return _out(agent, prefix + body, sources=sources, query=query, prefix=prefix, origin="kb",
                confidence="high" if top["score"] >= cfg["min_score"] + 0.08 else "medium",
                trace=f"kb_search → {len(hits)} chunks, best {top['doc_title']} › {top['section']} ({top['score']:.2f})")


@safe("qa")
def qa_node(state: FinanceState, config: RunnableConfig):
    return _kb_answer("qa", state, state["entities"]["wiki_query"])


@safe("tax")
def tax_node(state: FinanceState, config: RunnableConfig):
    """The tax expert (mds/agent-tax-agent.md): works out the user's own tax with its tools when they give amounts or ask
    about their saved Goals plan, and explains the rules from the tax and retirement pages only."""
    q = state["entities"]["wiki_query"]
    q = q if "tax" in q.lower() or "ira" in q.lower() or "401" in q else f"{q} tax"
    question = state["question"]
    profile = _last_estimate(state)                  # the last estimate's figures, for "what if I'm married?"
    trace_first = []
    last = (state.get("context_in") or {}).get("tax") or {}
    typed_now = state.get("original_question") or question
    statement = not TAXC.is_question(typed_now) and not re.search(r"\bwhat if\b", typed_now, re.I)
    answering = bool(last.get("pending") and TAXC.amounts(typed_now)) or bool(
        last.get("choices") and TAXC.changes_estimate(typed_now, last) and statement) or bool(
        last.get("items") and statement and TAXC.states_tax_figure(typed_now))   # "We also gave $5,000 to charity": add it
    # "how would the tax change in this case?" after a worked example of saving for a house: the example's tax, worked
    # out from its figures (interest while saving, the first-home IRA rule, deductions after buying, the sale)
    scen = None if answering else _savings_scenario(state)
    if scen:
        try:
            text, did = TW.savings_goal_tax(scen, last or None)
            return _out("tax", text, verbatim=True, explains_itself=True, origin="tax_tools", scenario_goal=scen.get("goal_type"),
                        sources=TAXC.SOURCES + _tax_pages(EXAMPLE_TAX_PAGES.get(scen.get("goal_type"), question)),
                        trace=f"tax tool {did}")
        except TW.Refused as e:
            trace_first.append(f"tax tool savings_goal_tax refused ({e}) → the usual path")
    # the model picks a tool and its arguments; Python runs it. An answer to "how much mortgage interest?" goes straight
    # into the running estimate instead.
    picked = None if answering else _pick_tax_tool(state)
    if picked:
        name, args, note = picked
        trace_first.append(note)
        home = any(it.get("kind") == "home_sale_price" for it in (last.get("items") or [])) or bool(
            re.search(r"\b(home|house|residence|section 121)\b", f"{question} {typed_now}", re.I))
        if name == "capital_gain" and home:          # a home sale: the estimate works out basis, gain and Section 121
            trace_first.append("tax tool capital_gain skipped (a home sale) → the estimate")
            name, picked = "estimate_income_tax", ("estimate_income_tax", {}, note)
        if name in TW.WHATIFS:
            typed = state.get("original_question") or ""
            try:
                text, did = TW.WHATIFS[name](args, f"{question}\n{typed}", (state.get("context_in") or {}).get("tax"),
                                             **({"goal": state.get("saved_goal")} if name == "compare_accounts" else {}))
                return _out("tax", text, verbatim=True, explains_itself=True, origin="tax_tools",
                            sources=TAXC.SOURCES + _tax_pages(question), trace=f"tax tool {did}") | {"trace": [*trace_first, f"tax tool {did}"]}
            except TW.Refused as e:
                trace_first.append(f"tax tool {name} refused ({e}) → the usual path")
        elif name == "update_estimate" and not profile:
            profile = (state.get("context_in") or {}).get("tax")
        elif name == "explain_rules" and not (state.get("saved_goal") and saved_plan_figures(state)):
            profile = None if not CTX.carried(state).get("tax") else profile
    typed = state.get("original_question") or question
    if current_llm() is not None and (ask := TAXC.missing_amount(typed, profile or (state.get("context_in") or {}).get("tax"))):
        # "I have a monthly mortgage payment": ask for the yearly interest; the figures so far stay for the answer
        kept = {**((state.get("context_in") or {}).get("tax") or {"items": [], "year": None, "filing_status": None}),
                "pending": TAXC.pending_kind(typed)}
        res = _out("tax", ask, status="need_info", confidence="medium", trace=f"tax: asks for the amount ({kept['pending']})")
        res["turn_context"] = {"tax": kept}
        return res
    # the model picked the estimate ("Sarah is a single taxpayer ... salary $95,000 ..."): a scenario with no question
    # a question about a rule that mentions a figure ("I sold shares for $3,000 that cost $7,000 and bought them back:
    # can I deduct the loss?") is explained when the model picked explain_rules; an estimate there misread the sale
    rule_question = bool(picked and picked[0] == "explain_rules" and TAXC.is_question(typed) and not TAXC.asks_income_tax(question))
    figure = ((TAXC.states_tax_figure(typed) or TAXC.states_tax_figure(question)) and not rule_question) or TAXC.is_scenario(typed) or bool(
        picked and picked[0] == "estimate_income_tax" and TAXC.amounts(question))
    if current_llm() is not None and (profile or TAXC.asks_income_tax(question) or figure):
        est, note = None, ""
        if profile:
            est, note = TT.estimate_income_tax(question, profile=profile, typed=state.get("original_question") or "")
            trace_first.append(f"tax tool estimate_income_tax {note}")
        if est is None and (TAXC.asks_income_tax(question) or (figure and not profile)):   # new figures, or a first one
            recent = H.transcript(state.get("history")) if state.get("follow_up") else ""
            est, note = TT.estimate_income_tax(question, f"Recent conversation:\n{recent}" if recent else "", typed=typed)
            trace_first.append(f"tax tool estimate_income_tax: {note}")
        if est is not None:
            res = _out("tax", est.text, verbatim=True, explains_itself=True, origin="tax_tools",
                       sources=TAXC.SOURCES + (_named_pages(est.topics) or _tax_pages(question)), choices=est.choices,
                       asks_user=bool(est.choices))
            res["turn_context"] = {"tax": est.profile}
            res["trace"] = trace_first
            return res
    g = state.get("saved_goal")
    last_tax = (state.get("context_in") or {}).get("tax")
    # this year's limits (or the year of the user's last estimate), not Wikipedia's; and the user's own figures if the
    # question follows an estimate ("how are long-term gains taxed differently?" after Sarah's)
    yours = TAXC.estimate_facts(last_tax, f"{state.get('original_question') or ''} {question}")
    figures = yours + TT.current_figures(f"{state.get('original_question') or ''} {question}", (last_tax or {}).get("year"))
    if not (g and saved_plan_figures(state)):
        res = _kb_answer("tax", state, q, TAX_PREFIX + figures, categories=TT.TAX_CATEGORIES)
        out = res["agent_outputs"]["tax"]
        if yours and out.get("status") == "answered":
            out["verbatim_tail"] = yours.strip()        # the user's own figures, shown as worked out, never dropped
        res["trace"] = trace_first + ["tax tool search_tax_pages"] + res["trace"]
        return res
    # "how does my plan cost me on the tax?": the question alone finds pages about financial planning; search for how the
    # plan's kind of savings is taxed, give the synthesizer the plan's figures, and work out the tax per account
    searches = PLAN_TAX_SEARCHES.get(g.get("goal_type"), PLAN_TAX_SEARCHES["other"])
    res = _kb_answer("tax", state, q, TAX_PREFIX + figures + _plan_tax_facts(state, g), searches=searches,
                     categories=TT.TAX_CATEGORIES)
    table, note = TT.tax_on_plan(g, _saved_projection(state, g)[1])
    out = res["agent_outputs"]["tax"]
    if out.get("status") == "answered":
        out["verbatim_tail"] = table                 # the figures go after the written explanation, never reworded
    else:                                            # no pages: the figures still answer "how much"
        res = _out("tax", table, verbatim=True, origin="tax_tools", sources=TAXC.SOURCES, trace="")
    res["trace"] = [*trace_first, f"tax: saved {g.get('goal_type')} plan → tools search_tax_pages + tax_on_plan ({note})",
                    *res["trace"]]
    return res


# what the Read-more links behind a savings example's tax are searched for
EXAMPLE_TAX_PAGES = {"house": "mortgage interest deduction, property tax and the home sale exclusion",
                     "education": "How is a 529 plan taxed?", "retirement": "How are traditional and Roth IRA withdrawals taxed?",
                     "other": "How is interest on a savings account taxed?"}
_SAVING = re.compile(r"\b(sav(e|es|ed|ing|ings)|put(ting)? (aside|away)|down ?payment|goal)\b", re.I)


def _savings_scenario(state: FinanceState) -> dict | None:
    """The savings goal a tax question is about: the previous answer's worked example when the message follows on from it,
    else one the message states itself ("how is saving $60,000 over 5 years for a down payment taxed?"). None when the
    message brings income or other amounts of its own (the estimate works those out) or isn't about saving."""
    typed = state.get("original_question") or state["question"]
    if state.get("scenario_now"):                # the example as the message changes it ("if I borrow $200,000 at 1.5%")
        return state["scenario_now"]
    if TAXC.asks_income_tax(typed) or TAXC.is_scenario(typed) or TAXC.states_tax_figure(typed):
        return None
    scen = CTX.carried(state).get("scenario") or {}
    if scen.get("kind") == "savings_goal" and _about_the_example(typed):
        own = set(TAXC.amounts(typed)) - CTX.scenario_numbers(scen)
        return None if own else scen
    e, q = state.get("entities") or {}, f"{typed} {state['question']}"
    if e.get("target_amount") and e.get("years") and _SAVING.search(q) and _about_the_example(typed):
        kind = R.goal_kind(q)
        r = project_goal(float(e["target_amount"]), int(e["years"]), 0, 0, get_config()["risk_profiles"]["conservative"])
        return _goal_scenario(kind, float(e["target_amount"]), int(e["years"]), r["required_monthly"],
                              r["annual_return_assumption"])
    return None


def _pick_tax_tool(state: FinanceState) -> tuple[str, dict, str] | None:
    """(tool, arguments, trace) the model picks for the message (tax_whatif.TOOL_SPECS), or None without a tool-calling
    model, when it picks none, or when it fails: the agent then takes its usual path (estimate, follow-up, plan, pages)."""
    llm = current_llm()
    if llm is None or not hasattr(llm, "bind_tools"):
        return None
    last = (state.get("context_in") or {}).get("tax")
    about = [f"LAST ESTIMATE:\n{TAXC.describe_profile(last)}\nFederal total "
             + (f"{last['total_federal']:.0f}" if last.get("total_federal") is not None else "not worked out yet (no income)")
             if last else
             "LAST ESTIMATE: none"]
    if state.get("saved_goal") and saved_plan_figures(state):
        about.append("The message is about the user's saved Goals plan.")
    typed = state.get("original_question") or ""
    said = f"Message: {typed}\n(Reworded: {state['question']})" if typed and typed != state["question"] else f"Message: {state['question']}"
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        reply = llm.bind_tools(TW.TOOL_SPECS).invoke([SystemMessage(TW.CHOOSER_SYSTEM), HumanMessage("\n".join(about) + "\n\n" + said)])
    except Exception as e:  # noqa: BLE001 — the usual path still answers
        log.warning("tax tool choice failed: %s", e)
        return None
    calls = getattr(reply, "tool_calls", None) or []
    if not calls:
        return None
    name, args = calls[0]["name"], calls[0].get("args") or {}
    shown = ", ".join(f"{k}={v}" for k, v in args.items())
    return name, args, f"tax: model picked {name}({shown})"


def _last_estimate(state: FinanceState) -> dict | None:
    """The previous answer's tax figures when this message may change them: a follow-up, an answer button ("I held the
    shares a year or less") or a "what if" about them. The proofreader doesn't always mark a short answer as a follow-up."""
    prof = (state.get("context_in") or {}).get("tax")
    if not prof:
        return None
    return prof if CTX.carried(state).get("tax") or TAXC.changes_estimate(state.get("original_question") or state["question"], prof) \
        or TAXC.changes_estimate(state["question"], prof) else None


def _named_pages(titles: list[str], most: int = 3) -> list[dict]:
    """Links to the named tax pages (the credits and deductions an estimate used), found by title in the tax pages."""
    out = []
    for title in titles:
        if len(out) >= most:
            break
        try:
            hits = TT.search_tax_pages(title, 5)
        except Exception as e:  # noqa: BLE001 — the estimate stands without them
            log.warning("tax page search failed: %s", e)
            return out
        hit = next((h for h in hits if h["doc_title"].lower() == title.lower()), None)
        if hit and all(o["url"] != hit["source_url"] for o in out):
            out.append({"id": f"kb:{hit['doc_id']}#(lead)", "title": f"{hit['doc_title']} ({_origin(hit)})", "url": hit["source_url"]})
    return out


def _tax_pages(question: str, most: int = 3) -> list[dict]:
    """Links to the tax pages behind a worked estimate (read more), best first; none if the search fails."""
    try:
        hits = TT.search_tax_pages(question)
    except Exception as e:  # noqa: BLE001 — the estimate stands without them
        log.warning("tax page search failed: %s", e)
        return []
    out, seen = [], set()
    for h in hits:
        if h["doc_id"] in seen or h["score"] < get_config()["rag"]["min_score"]:
            continue
        seen.add(h["doc_id"])
        anchor = "" if h["section"] == "(lead)" else "#" + h["section"].split(" > ")[-1].replace(" ", "_")
        out.append({"id": f"kb:{h['doc_id']}#{h['section']}", "title": f"{h['doc_title']} ({_origin(h)})",
                    "url": h["source_url"] + ("" if _origin(h) != "Wikipedia" else anchor)})
    return out[:most]


PLAN_TAX_SEARCHES = {
    "retirement": ["How are traditional 401(k) and IRA contributions and withdrawals taxed?",
                   "Is investment growth in a Roth IRA taxed?",
                   "How are long-term capital gains taxed in a regular brokerage account?"],
    "education": ["How is a 529 plan taxed?", "How is a Coverdell education savings account taxed?",
                  "How are long-term capital gains taxed in a regular brokerage account?"],
    "other": ["How are long-term capital gains taxed?", "How are interest and dividends taxed?",
              "What is a tax-advantaged account?"],
}
PLAN_TAX_SEARCHES["house"] = PLAN_TAX_SEARCHES["other"]


def _plan_tax_facts(state: FinanceState, g: dict) -> str:
    """The saved plan's figures for the tax answer (computed here): what is paid in, what grows, and what isn't known."""
    _, r = _saved_projection(state, g)
    years, current, monthly = g["horizon_years"], g.get("current_savings", 0) or 0, g.get("monthly_contribution", 0) or 0
    paid_in = current + monthly * 12 * years
    growth = r["projected_value"] - paid_in
    return (f"**The user's {g['goal_type']} plan (Goals tab):** {CALC.money(paid_in)} paid in over {years} years "
            f"({CALC.money(current)} now + {CALC.money(monthly)} a month), projected to {CALC.money(round(r['projected_value']))}, so about "
            f"**{CALC.money(round(growth))} of investment growth**. The plan doesn't say which account the money is in, and the tax "
            f"depends on it: explain each case the sources cover for this money (and that the account type decides it); "
            f"don't compute a tax amount.\n\n")


_PRICE_ASK = re.compile(r"\b(price|quote|trading at|share price|worth today|how much is)\b", re.I)
MARKET_ASK = ("I couldn't tell which company or ticker you mean. Tell me the company name or its ticker symbol "
              "(for example “NVIDIA” or “NVDA”) and I'll look up its price.")
# Basic mode only (with an LLM, `symbols.subjects` decides): "the market" plus a word asking how it is doing now means the
# US indices. Both are required, so "time the market" or "market cap" stays a concept lookup.
_WHOLE_MARKET = re.compile(r"\b(?:the\s+)?(?:stock\s+)?markets?\b", re.I)
_MARKET_NOW = re.compile(r"\b(today|tonight|so far|right now|now|this (?:morning|afternoon|week)|doing|performing|going|moving|"
                         r"insights?|overview|update|recap|wrap(?:-?up)?)\b", re.I)


def _view_symbols(state: FinanceState) -> list[str]:
    """Symbols the user means without naming them: "my watchlist", or "this stock" while one is selected on the Live Market
    or Research tab."""
    view, q = state.get("view") or {}, state["question"]
    valid = lambda syms: [s for s in dict.fromkeys(str(x).strip().upper() for x in syms if x) if SYMBOL_OK.match(s)]  # noqa: E731
    if re.search(r"\b(watchlist|watching|tracking|following)\b", q, re.I):
        return valid(view.get("watchlist") or [])
    if view.get("selected") and re.search(r"\b(this|selected|current)\b", q, re.I):     # not "it"/"that": they usually mean something else
        return valid([view["selected"]])
    return []


_PERFORMANCE = re.compile(r"\b(perform\w*|better|worse|best|worst|compare\w*|versus|vs|returns?|gain\w*|grow\w*|done|doing|did)\b", re.I)
# Today's move, read from quotes (change vs previous close), not a period's return. "nvda vs market today?" once carried the
# previous answer's "last month" and compared NVDA's day with the indices' month.
_TODAY = re.compile(r"\b(today|today's|tonight|intraday|right now|this (?:morning|afternoon))\b", re.I)
# "NVDA vs the market": the US indices are a subject too, though the router named only the company (a chat's first message).
_VS_MARKET = re.compile(r"\b(?:vs\.?|versus|compared?\s+(?:to|with)|against|than|relative\s+to)\s+(?:the\s+)?"
                        r"(?:overall\s+|broader\s+|wider\s+|whole\s+)?(?:us\s+|u\.s\.\s+)?(?:stock\s+)?markets?\b", re.I)


def _period_for(state: FinanceState) -> tuple[date, str] | None:
    """The period this question asks about; for a follow-up ("which did better?", "what about AAPL?"), the one the previous
    answer used (its saved context). A plain price question, or one about today, gets none. Conversations saved before
    contexts existed fall back to looking for a period in the recent messages."""
    q = state["question"]
    if p := MT.asked_period(q):
        return p
    if _PRICE_ASK.search(q) or _TODAY.search(q):
        return None
    if state.get("context_in") is not None:
        return CTX.period_of(CTX.carried(state))
    if not _PERFORMANCE.search(q):
        return None
    return next((p for m in reversed(H.recent(state.get("history"))) if (p := MT.asked_period(m["content"]))), None)


MARKET_TOOL_SYSTEM = (
    "You fetch market data for a personal-finance EDUCATION assistant. Call the tools that supply the figures the question "
    "needs, for the companies, funds or markets it is about (use ticker symbols). Request everything in this one reply; you may "
    "call several tools at once. Match the level the question is about. Company or fund: get_quote gives today's price, change, "
    "volume and day range; get_performance a period's return, high/low and average volume; get_company_profile a company's "
    "sector, valuation (P/E, market cap, beta), earnings and dividends; get_fund_profile an ETF's or mutual fund's expense ratio, "
    "yield and holdings. Sector (\"the tech sector\", \"bank stocks\"): get_sector_performance for how it did, never a quote of the "
    "sector's fund; get_sector_profile for what it is made of; get_industry_performance for which of its industries did best or "
    "worst. One industry (\"semiconductors\"): get_industry. The market as a whole, or all sectors: get_market_overview; the "
    "largest companies: get_largest_companies; stock markets around the world, a region or a country: get_region_performance; "
    "today's most traded stocks: get_most_active; whether the market is open: get_market_status. Call each tool once per subject, "
    "for the period the question or conversation names; with none named, leave the period out (it defaults to the last month). "
    "A question about today (\"today\", \"right now\") is about today's move: get_quote, for the market too (its index "
    "symbols, e.g. ^GSPC, ^IXIC, ^DJI), never a period's return from get_performance or get_market_overview. "
    "Don't answer the question yourself.")


def _llm_fetch(llm, state: FinanceState, db, symbols: list[str], period: tuple[date, str] | None) -> tuple[dict, list[str]]:
    """Let the model choose tools and arguments (LangChain tool calling); Python runs them through market_tools, which read the
    cache. At most `workflow.market_tool_calls` calls in `workflow.market_tool_rounds` replies, so one question can't fan out."""
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    cfg = get_config()["workflow"]
    max_calls, rounds = int(cfg.get("market_tool_calls", 4)), int(cfg.get("market_tool_rounds", 1))
    names = {c["symbol"]: c.get("name") for c in state["entities"].get("companies") or []}
    names.update({s: m["name"] if m["symbol"] else f"{m['name']}: {s}" for m in state["entities"].get("markets") or [] for s in m["quotes"]})
    about = [f"Companies and markets: {', '.join(f'{names[s]} ({s})' if names.get(s) else s for s in symbols)}" if symbols else
             "Companies and markets: none named (a question about the market as a whole)"]
    if levels := state["entities"].get("levels") or []:
        about.append(f"Level: {', '.join(levels)}")
    if period:
        about.append(f"Period the conversation is about: {period[1]}")
    if known := CTX.describe(state.get("context_in")):
        about.append(f"Earlier in the conversation:\n{known}")
    messages = [SystemMessage(MARKET_TOOL_SYSTEM), HumanMessage("\n".join(about) + f"\n\nQuestion: {state['question']}")]
    bound, data, notes, calls, seen = llm.bind_tools(MT.TOOL_SPECS), {}, [], 0, set()
    for _ in range(rounds):
        reply = bound.invoke(messages)
        tool_calls = getattr(reply, "tool_calls", None) or []
        if not tool_calls:
            break
        messages.append(reply)
        for call in tool_calls:
            key = (call["name"], json.dumps(call.get("args") or {}, sort_keys=True))
            if key in seen:                     # the same call again (one overview per index listed): nothing new, not counted
                messages.append(ToolMessage("skipped: same call as before", tool_call_id=call["id"]))
                continue
            seen.add(key)
            if "company" in levels and (strays := _off_subject(call.get("args") or {}, symbols)):
                notes.append(f"{call['name']}({', '.join(strays)}) → skipped (not what the question is about)")
                messages.append(ToolMessage(f"skipped: {', '.join(strays)} is not one of the question's subjects", tool_call_id=call["id"]))
                continue
            if calls >= max_calls:
                notes.append(f"{call['name']} → skipped (limit of {max_calls} tool calls)")
                messages.append(ToolMessage("skipped: tool call limit reached", tool_call_id=call["id"]))
                continue
            calls += 1
            result, note = MT.run_tool(db, call["name"], call.get("args") or {})
            notes.append(note)
            data = MT.merge_market(data, {k: v for k, v in result.items() if not k.startswith("_")})
            messages.append(ToolMessage(json.dumps(result, default=str)[:4000], tool_call_id=call["id"]))
    return data, notes


def _off_subject(args: dict, symbols: list[str]) -> list[str]:
    """The symbols a tool call names that the question isn't about, checked when it names companies (a question about the
    market as a whole leaves the stocks to the model). The model sees the earlier conversation, and once turned "Gold" into
    the stock GOLD for a question about AAPL; a subject the router missed is better missing than invented."""
    asked = args.get("symbols") if "symbols" in args else args.get("symbol")
    named = [str(s).strip().upper().lstrip("$") for s in (asked if isinstance(asked, list) else [asked]) if s]
    return [s for s in named if s not in set(symbols)]


def _fill_in(db, data: dict, symbols: list[str], period: tuple[date, str] | None, *, quote_only=()) -> tuple[dict, list[str]]:
    """What every answer has, whatever the model chose (and all of it without an LLM): a quote for each company, and the
    asked or carried period's performance (not for `quote_only`: symbols whose period the market overview already gives)."""
    notes = []
    need = [s for s in symbols if "quote" not in data.get(s, {})]      # cached, so cheap even when the model chose other tools
    for i in range(0, len(need), MT.MAX_SYMBOLS):                      # the tool takes MAX_SYMBOLS at a time; all four US indices are 4
        part = need[i:i + MT.MAX_SYMBOLS]
        got = MT.get_quote(db, part)
        notes.append(f"get_quote({', '.join(part)}) → {_freshness(got)}")
        data = MT.merge_market(data, got)
    if period:
        need = [s for s in symbols if "quote" in data.get(s, {}) and "period" not in data[s] and s not in quote_only]
        if need:
            got = MT.performance(db, need, *period)
            notes.append(f"get_performance({', '.join(need)}, {period[1]}) → {_freshness(got)}")
            data = MT.merge_market(data, got)
    return data, notes


def _group_syms(markets: list[dict], group: str) -> set[str]:
    return {s for m in markets if m["group"] == group for s in m["quotes"]}


def _levels_asked(state: FinanceState, markets: list[dict], period: tuple[date, str] | None) -> tuple[list[str], bool]:
    """Figures above one company the question needs: (the sectors to measure against the S&P 500, whether to add the market
    overview). A sector gets its sector figures; "sectors" as a group, or how the whole market performed, the overview. A price
    asked for ("price of XLK") keeps the plain quote."""
    q = state["question"]
    if _PRICE_ASK.search(q):
        return [], False
    sectors = [m["symbol"] for m in markets if m.get("level") == "sector" and m["symbol"]]
    keys = {m["key"] for m in markets}
    over_time = bool(period) or (_PERFORMANCE.search(q) and not _TODAY.search(q))     # today: the indices' quotes say it
    overview = "group:sectors" in keys or ("group:us_indices" in keys and over_time)
    return sectors, overview


def _fill_levels(db, data: dict, sectors: list[str], overview: bool, period: tuple[date, str] | None) -> tuple[dict, list[str]]:
    """The sector and overview figures the model didn't fetch (all of them without an LLM), over the asked or carried period,
    else MT.DEFAULT_PERIOD."""
    start, label = period or MT.parse_period(MT.DEFAULT_PERIOD)
    notes = []
    for s in sectors:
        if "sector" not in data.get(s, {}):
            got = MT.sector_performance(db, s, start, label)
            notes.append(f"get_sector_performance({s}, {label}) → {_freshness(got)}")
            data = MT.merge_market(data, got)
    if overview and "overview" not in data.get(MT.OVERVIEW_KEY, {}):
        got = MT.market_overview(db, start, label)
        notes.append(f"get_market_overview({label}) → {_freshness(got)}")
        data = MT.merge_market(data, got)
    return data, notes


def _freshness(data: dict) -> str:
    fresh = {sec.get("freshness") for d in data.values() for sec in d.values() if isinstance(sec, dict)} - {None}
    return ", ".join(sorted(fresh)) or "no data"


def _key_facts(data: dict) -> dict:
    """What the next turn may refer back to (saved context): a few figures per symbol, each with its date."""
    facts = {}
    for sym, d in data.items():
        f = {}
        if q := d.get("quote"):
            f.update({"price": q["price"], "change_pct": q.get("change_pct"), "volume": q.get("volume"), "as_of": q["as_of"][:10]})
        if p := d.get("period"):
            f.update({"period": p["label"], "return": p["return"], "start_price": p["start_price"], "end_price": p["end_price"],
                      "start_date": p["start_date"], "end_date": p["end_date"], "avg_volume": p.get("avg_volume")})
        if pr := d.get("profile"):
            f.update({k: pr[k] for k in ("trailing_pe", "market_cap", "shares_outstanding", "dividend_yield") if pr.get(k) is not None})
        if fd := d.get("fund"):
            f.update({k: fd[k] for k in ("expense_ratio", "yield") if fd.get(k) is not None})
        if f:
            facts[sym] = {k: v for k, v in f.items() if v is not None}
    return facts


@safe("market")
def market_node(state: FinanceState, config: RunnableConfig):
    """Market data through tools (market_tools.py). With an LLM the model picks the tools and arguments for the question
    (quote, performance over a period, company or fund profile, sector performance, market overview); then, and without an LLM,
    every company gets a quote and the asked or carried period its performance, a sector (`entities["levels"]`) its return against
    the S&P 500 instead of its fund's quote, and the market as a whole the overview. All figures go to `market_data` for the
    synthesizer and the saved context."""
    e = state["entities"]
    symbols = e["tickers"] + e["indices"]
    view_syms = _view_symbols(state) if not symbols else []
    symbols = symbols or view_syms
    named = e.get("companies") or []        # "price of Palantir": looked up on Yahoo by the router; or carried from the previous answer
    markets = e.get("markets") or []        # "how is gold doing?": GC=F; "forex": the group's main pairs
    if not (symbols or named or markets) and current_llm() is None and _WHOLE_MARKET.search(state["question"]) and _MARKET_NOW.search(state["question"]):
        markets = [MK.group("us_indices")]
    if not markets and _VS_MARKET.search(state["question"]):
        markets = [MK.group("us_indices")]
    market_syms = [s for m in markets for s in m["quotes"]]
    symbols = list(dict.fromkeys([*symbols, *(r["symbol"] for r in named), *market_syms]))
    if not symbols and (wide := _market_wide(state, config)):                    # "most active stocks today?": no subject needed
        return wide
    if not symbols and _PRICE_ASK.search(state["question"]):                      # a quote for something we can't identify: ask, don't research
        return _out("market", MARKET_ASK, status="need_info", confidence="low", trace="market: price asked for, but no company or ticker recognised → ask")
    if not symbols:                        # a market concept rather than a quote: look it up
        return _not_found("market", e["wiki_query"], "market: no ticker or index → concept lookup")
    db = _db(config)
    if db is None:
        raise RuntimeError("no database session for market lookup")
    period = _period_for(state)
    sectors, overview = _levels_asked(state, markets, period)
    quoted = [s for s in symbols if s not in sectors and not (overview and s in _group_syms(markets, "sectors"))]
    data, notes, how = {}, [], "keywords"
    llm = current_llm()
    if llm is not None and hasattr(llm, "bind_tools"):
        try:
            data, notes = _llm_fetch(llm, state, db, symbols, period)
            how = "LLM tools"
        except Exception as ex:  # noqa: BLE001 — a model that can't call tools still gets the standard figures
            log.warning("market tool calling failed: %s", ex)
            notes.append(f"tool calling failed ({type(ex).__name__})")
    ov = data.get(MT.OVERVIEW_KEY, {}).get("overview")
    if ov and period is None and _TODAY.search(state["question"]) and ov["label"] != "last day":
        del data[MT.OVERVIEW_KEY]           # the model asked for a month's returns (the default) for a question about today
        quoted += [s for s in MT.OVERVIEW_INDICES if s not in quoted]
        notes.append(f"market overview ({ov['label']}) dropped: the question is about today → index quotes")
    data, more = _fill_in(db, data, quoted, period, quote_only=MT.OVERVIEW_INDICES if overview else ())
    notes += more
    data, more = _fill_levels(db, data, sectors, overview, period)
    notes += more
    data, more = _fill_wide(db, data, state["question"])
    notes += more
    data = {s: ({"sector": d["sector"]} if s in sectors and "sector" in d else d) for s, d in data.items()}   # the sector, not its fund's price
    return _market_result(data, notes, how, markets, market_syms, period)


# Basic mode (no LLM) for questions about the market as a whole that name no subject; with an LLM the model picks these tools.
_MARKET_WIDE = [(re.compile(r"\bmost (?:active|traded)\b", re.I), "get_most_active", "MOST_ACTIVE"),
                (re.compile(r"\b(?:biggest|largest) (?:\w+ )?(?:companies|stocks)\b", re.I), "get_largest_companies", "LARGEST"),
                (re.compile(r"\b(?:markets? (?:is )?(?:open|closed)|is the (?:stock )?market open|trading hours)\b", re.I), "get_market_status",
                 "MARKET_STATUS")]


def _fill_wide(db, data: dict, question: str) -> tuple[dict, list[str]]:
    """The market-wide figures the question's words ask for and the model didn't fetch (all of them without an LLM)."""
    notes = []
    for pattern, name, key in _MARKET_WIDE:
        if pattern.search(question) and key not in data:
            got, note = MT.run_tool(db, name, {})
            notes.append(note)
            data = MT.merge_market(data, got)
    return data, notes


def _market_wide(state: FinanceState, config: RunnableConfig) -> dict | None:
    """A question about the market as a whole that names no company or market ("most active stocks today?", "biggest companies?",
    "is the market open?"): the model picks the market-wide tools, or without one the words do. None when neither finds any."""
    db = _db(config)
    if db is None:
        return None
    period, llm, data, notes, how = _period_for(state), current_llm(), {}, [], "keywords"
    if llm is not None and hasattr(llm, "bind_tools"):
        try:
            data, notes = _llm_fetch(llm, state, db, [], period)
            how = "LLM tools"
        except Exception as ex:  # noqa: BLE001
            log.warning("market tool calling failed: %s", ex)
    data, more = _fill_wide(db, data, state["question"])
    notes += more
    if not any(len(d) > 1 or "error" not in d for d in data.values()):
        return None
    return _market_result(data, notes, how, [], [], period)


def _market_result(data: dict, notes: list[str], how: str, markets: list[dict], market_syms: list[str], period) -> dict:
    """The market agent's output from the figures: the answer lines, data info, `market_data` and the saved context."""
    lines = MT.describe_lines(data)
    quotes = [d["quote"] for d in data.values() if "quote" in d]
    if quotes:
        lines.append("\n_“% vs previous close” compares today's price with yesterday's closing price. A single day's move says little about the long term._")
    shown = quotes or [sec for d in data.values() for k in ("sector", "overview", *MT.YAHOO_LINES) if (sec := d.get(k)) and sec.get("as_of")]
    info = {"provider": shown[0]["source"], "fetched_at": shown[0]["as_of"], "freshness": shown[0]["freshness"]} if shown else None
    res = _out("market", "\n".join(lines), data_info=info, confidence="high" if shown else "low",
               trace=f"market ({how}): " + "; ".join(notes))
    res["market_data"] = data
    used = next((d[k] for d in data.values() for k in ("period", "sector", "overview") if k in d), None)
    companies = [{"symbol": s, "name": MT._name(d, s)} for s, d in data.items()
                 if ("error" not in d or len(d) > 1) and s not in market_syms and not MT.is_subject_key(s)][:CTX.MAX_COMPANIES]
    res["turn_context"] = {"companies": companies,
                           "markets": [{"key": m["key"], "name": m["name"]} for m in markets],
                           "levels": SYM.levels(companies, markets),
                           "facts": _key_facts(data),
                           **({"period": {"start": used["start"], "label": used["label"]}} if used else
                              {"period": {"start": period[0].isoformat(), "label": period[1]}} if period else {})}
    return res


NEWS_LIVE_MAX = 6                # stories shown when the question asks for no number ("show the latest 5 news" asks for 5)
NEWS_MAX_ASKED = 15              # the most stories one answer shows, whatever is asked
NEWS_SCREEN_MAX = 30             # newest headlines the relevance check looks through
NEWS_MARKET_READING = "the latest market-wide headlines, not news about any particular company"
NEWS_MARKET_ALTERNATIVES = ["What's in the news about interest rates and the Fed this week?",
                            "What's the latest technology sector news?", "What moved the stock market this week?"]


def _news_none(days: int, tried: list[str], trace: str, *, unavailable: bool = False) -> dict:
    """Nothing usable after the tools ran: say what was tried (never fall through to Wikipedia, which has no news) and don't offer follow-ups."""
    if unavailable:
        msg = "I can't search my news index right now, so I can't check recent stories. Please try again shortly."
    else:
        did = "; ".join(tried)
        msg = (f"I looked, and found no news matching that from the last {days} days ({did}). "
               "If you name a company, ticker or market, for example “news on NVDA” or “forex news”, I can pull its latest headlines.")
    return _out("news", msg, confidence="low", verbatim=True, no_results=True, trace=trace)


NEWS_FEEDS_MAX = 4               # feeds fetched for one question (a market group has up to four news terms)


def _live_envs(db, tickers: list[str]) -> list[tuple[str | None, dict]]:
    """Live (5-minute cached) headline feeds for the named tickers and market news terms, or the market feed when there are none."""
    envs = []
    for sym in tickers[:NEWS_FEEDS_MAX] or [None]:
        try:
            envs.append((sym, news_latest(db, sym)))
        except SymbolNotFound:
            continue
    return envs


def _fetched_note(envs: list[tuple[str | None, dict]], label: str) -> str:
    n = sum(len(env["data"]["items"]) for _, env in envs)
    return f"fetched {n} {label} headlines from Yahoo" if n else f"Yahoo returned no headlines for {label}"


def _with_articles(stories: list[dict]) -> tuple[list[dict], str]:
    """The stories with what their pages say as the summary where Yahoo gave only the headline, and a note for the trace."""
    try:
        texts = story_articles(stories)
    except Exception as e:  # noqa: BLE001 — without the articles the headlines still answer
        log.warning("reading story pages failed: %s", e)
        return stories, f"story pages → failed ({type(e).__name__})"
    if not texts:
        return stories, ""
    return [{**s, "summary": texts.get(s.get("story_id") or s["id"]) or s.get("summary", "")} for s in stories], \
        f"read {len(texts)} of {len(stories)} story pages"


def _news_out(intro: str, stories: list[dict], **kw) -> dict:
    """The stories, with their excerpts, as the agent's output."""
    chars = get_config()["news_index"]["summary_chars"]
    what = " with a summary of each story:" if current_llm() is not None else " with an excerpt of each story:"
    head = intro + (what if any(s.get("summary") for s in stories) else ":")
    return _out("news", head + "\n" + "\n".join(NEWS.format_story(s, chars) for s in stories),
                sources=[NEWS.story_source(s) for s in stories], **kw)


NEWS_ABOUT_SYSTEM = (
    "You screen news headlines for a question about specific companies or markets. Yahoo tags stories loosely, so a feed "
    "for a company also carries stories about other companies, general investing or the market. Keep a headline only if "
    "the story is mainly about one of the named subjects, or clearly reports something that directly involves it (its "
    "earnings, deals, executives, products, lawsuits, analyst calls on its stock). Drop stories about other companies that "
    "merely mention it, market-wide commentary, and personal-finance articles. When a question is given, keep only stories "
    "that answer it (for \"news related to the housing market\": home sales, mortgage rates, homebuilders, house prices), "
    "with or without subjects. Reply with ONLY JSON: {\"keep\": [numbers]}")


def _about(stories: list[dict], subjects: list[str], topic: str = "") -> tuple[list[dict], str]:
    """The stories mainly about `subjects` (company or market names) and, if given, the question's `topic`, judged from the
    headlines in one LLM call; all of them without an LLM or when the reply is unusable. Returns (stories, trace note)."""
    if not (subjects or topic) or not stories or current_llm() is None:
        return stories, ""
    listing = "\n".join(f"{i}. {s['title']}" + (f" ({s['publisher']})" if s.get("publisher") else "") for i, s in enumerate(stories, 1))
    ask = (f"Subjects: {', '.join(subjects)}\n" if subjects else "") + (f"Question: {topic}\n" if topic else "")
    reply = _json(ask_llm(NEWS_ABOUT_SYSTEM, f"{ask}\nHeadlines:\n{listing}"))
    keep = (reply or {}).get("keep") if isinstance(reply, dict) else None
    if not isinstance(keep, list):
        return stories, "relevance check → no usable reply, kept all"
    picked = {int(k) for k in keep if isinstance(k, (int, float)) or str(k).isdigit()}
    kept = [s for i, s in enumerate(stories, 1) if i in picked]
    return kept, f"relevance check → {len(kept)} of {len(stories)} headlines about {', '.join(subjects) or repr(topic)}"


def _ts(s: dict) -> float:
    return s.get("published_ts") or (NEWS.parse_time(s.get("published")) or 0)


def _day(s: dict) -> str:
    return datetime.fromtimestamp(_ts(s), timezone.utc).strftime("%Y-%m-%d")


def _by_day(stories: list[dict], n: int) -> list[dict]:
    """Up to `n` stories taking turns across the days they were published (newest day first, newest story first within a
    day), so a window of days shows each day's news rather than only the busiest, latest one."""
    days: dict[str, list[dict]] = {}
    for s in sorted(stories, key=_ts, reverse=True):
        days.setdefault(_day(s), []).append(s)
    out, queues = [], list(days.values())
    while len(out) < n and any(queues):
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop(0))
    return out


def _newest(envs: list[tuple[str | None, dict]], extra: list[dict], days: int | None) -> list[dict]:
    """The feeds' stories plus `extra` (indexed ones), one per story and title, within `days` if given, newest first; with
    several feeds they take turns, so one busy feed can't crowd out the others."""
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400 if days else None
    lists = [list(env["data"]["items"]) for _, env in envs]
    symbols = [sym for sym, _ in envs]
    for story in extra:                                   # an indexed story joins the feed of a ticker it is tagged with
        tags = set(story.get("tickers") or ())
        i = next((k for k, sym in enumerate(symbols) if sym and sym.upper() in tags), 0)
        if lists:
            lists[i].append(story)
        else:
            lists.append([story])

    ts = _ts
    seen, out = set(), []
    lists = [sorted((x for x in l if cutoff is None or ts(x) >= cutoff), key=ts, reverse=True) for l in lists]
    for row in range(max((len(l) for l in lists), default=0)):
        for l in lists:
            if row < len(l):
                s = l[row]
                key = (s.get("story_id") or s.get("id"), " ".join(s["title"].lower().split()))
                if key[0] in seen or key[1] in seen:
                    continue
                seen.update(key)
                out.append(s)
    return out if len(lists) > 1 else sorted(out, key=ts, reverse=True)


def _live_news(envs: list[tuple[str | None, dict]], label: str, intro: str = "", *, count: int | None = None,
               days: int | None = None, tags: list[str] = (), subjects: list[str] = ()) -> dict | None:
    """The newest stories across the feeds as an agent output, None if there are none. `count`: how many the question asked
    for (else NEWS_LIVE_MAX); `days`: the window it asked for, which also brings in the indexed stories for `tags` (the
    feeds hold only Yahoo's ~30 latest); `subjects`: the companies or markets asked about, whose off-topic stories are
    dropped before any page is read. Says so when fewer stories exist than were asked for."""
    steps = []
    extra = []
    if days and tags:
        try:
            extra = news_recent(list(tags), days)
            steps.append(f"news_recent({', '.join(tags)}, {days}d) → {len(extra)} indexed stories")
        except Exception as e:  # noqa: BLE001 — the feeds still answer
            log.warning("listing indexed news failed: %s", e)
            steps.append(f"news_recent → failed ({type(e).__name__})")
    candidates = _newest(envs, extra, days)
    if not candidates:
        return None
    spread = bool(days and days > 1 and not count)         # "the last 10 days of news": across the days, not just today's
    want = count or (min(NEWS_MAX_ASKED, max(NEWS_LIVE_MAX, days)) if spread else NEWS_LIVE_MAX)
    pool = _by_day(candidates, NEWS_SCREEN_MAX * 2) if spread else candidates[:max(NEWS_SCREEN_MAX, want * 2)]
    screened, note = _about(pool, list(subjects))
    if note:
        steps.append(note)
    if not screened:
        return None
    picked = _by_day(screened, want) if spread else screened[:want]
    if spread:
        steps.append(f"spread over {len({_day(s) for s in picked})} of the last {days} days")
    stories, read = _with_articles(sorted(picked, key=lambda s: _ts(s), reverse=True))
    span = f" from the last {days} day{'s' if days != 1 else ''}" if days else ""
    if count and len(stories) < count:
        intro += (f"You asked for {count} stories{span}; only {len(stories)} about {label} "
                  f"{'was' if len(stories) == 1 else 'were'} available, so all of them are below. ")
    elif spread:
        intro += (f"{len(stories)} stories{span} about {label}, spread across the days, newest first"
                  + ("; there are more, ask for a number to see more. " if len(screened) > len(stories) else ". "))
    info = {k: envs[0][1][k] for k in ("provider", "fetched_at", "freshness")} if envs else \
        {"provider": "yfinance", "fetched_at": datetime.now(timezone.utc).isoformat(), "freshness": "cached"}
    fed = sum(len(env["data"]["items"]) for _, env in envs)
    return _news_out(f"{intro}Latest headlines for {label} (Yahoo Finance, {info['freshness']}); cover every story listed", stories,
                     data_info=info,
                     trace="; ".join([f"news_latest({label}) → {fed} stories ({info['freshness']})", *steps,
                                      f"showing {len(stories)}" + (f" of {count} asked" if count else "")]
                                     + ([read] if read else [])))


def _relevant_news(text: str, tickers: list[str], days: int) -> list[dict]:
    """Indexed stories that answer the question: above the score floor and close to the best match."""
    cfg = get_config()["news_index"]
    hits = news_search(text, tickers or None, days)
    floor = max(cfg["min_score"], max((h["score"] for h in hits), default=0) - cfg["score_margin"])
    return [h for h in hits if h["score"] >= floor]


def _sector_news(symbol: str, config: RunnableConfig, steps: list[str]) -> dict:
    """Latest headlines from the largest companies in `symbol`'s industry (Yahoo's own classification)."""
    info = industry_peers(symbol)
    peers = [p["symbol"] for p in (info or {}).get("peers", []) if SYMBOL_OK.match(p["symbol"])][:3]
    if not peers:
        return _news_none(7, [f"looked for companies in {symbol}'s industry, found none"], "; ".join(steps + [f"sector_peers({symbol}) → none found"]))
    db = _db(config)
    if db is None:
        raise RuntimeError("no database session for news lookup")
    with DBSession(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as own:
        envs = _live_envs(own, peers)
    where = ", ".join(x for x in (info.get("industry"), info.get("sector")) if x) or "the same sector"
    names = ", ".join(f"{p['name']} ({p['symbol']})" for p in info["peers"] if p["symbol"] in peers)
    out = _live_news(envs, ", ".join(peers), f"{symbol} is in {where}. Its largest peers are {names}. ")
    if out:
        out["trace"] = steps + [f"sector_peers({symbol}) → {', '.join(peers)}"] + out["trace"]
        return out
    return _news_none(7, [f"found {symbol}'s industry peers ({', '.join(peers)}) but {_fetched_note(envs, 'their').lower()}"],
                      "; ".join(steps + [f"sector_peers({symbol}) → {', '.join(peers)}; no headlines"]))


@safe("news")
def news_node(state: FinanceState, config: RunnableConfig):
    """Headlines, found with tools rather than from what happens to be indexed. The company or ticker the user names is resolved
    on Yahoo (so "Palantir" works though the router has never heard of it). "Latest on AAPL" / "market news" come from the live
    cached feed; a question with a topic or a date range is answered from the indexed stories, and if none of that ticker's are indexed
    yet its headlines are fetched live, indexed on the spot and searched again. Only then does it say nothing was found, and it says
    what it tried. It never falls through to the Wikipedia research step."""
    text, tried, e = state["question"], [], state["entities"]   # the proofread question: corrected, and completed for a follow-up
    ruled_out = set(e.get("excluded") or ()) | SYM.excluded(text)     # "not looking for DHSB news": neither the ticker nor the topic
    text = SYM.without_excluded(text)
    tickers = [t for t in NEWS.tickers_in(text, e) if SYMBOL_OK.match(t) and t.lower() not in ruled_out]
    resolved = e.get("companies") or []                      # looked up by the router, or carried from the previous answer
    markets = e.get("markets") or []                         # "forex", "gold": fetched by their news terms
    if resolved:
        tickers = list(dict.fromkeys([*tickers, *(r["symbol"] for r in resolved)]))
    if resolved or markets:
        tried.append("matched " + ", ".join([*(f"{r['name']} ({r['symbol']})" for r in resolved), *(_market_label(m) for m in markets)]))
    if not markets:
        tickers = tickers or [t for t in _view_symbols(state) if t.lower() not in ruled_out]
    res = _news_answer(state, config, text, tickers, resolved, markets, tried)
    if tickers or markets:                                    # so "what about their earnings?" knows who "their" is
        names = {r["symbol"]: r.get("name") or r["symbol"] for r in resolved}
        res["turn_context"] = {"companies": [{"symbol": t, "name": names.get(t, t)} for t in tickers[:CTX.MAX_COMPANIES]],
                               "markets": [{"key": m["key"], "name": m["name"]} for m in markets]}
    return res


SECTOR_NEWS_COMPANIES = 3        # a sector's news: its fund's feed plus its largest companies' (NEWS_FEEDS_MAX in all)


def _sector_leaders(config: RunnableConfig, markets: list[dict], steps: list[str]) -> list[str]:
    """A sector named as the subject ("tech sector news") is reported on through its largest companies too, not just its fund:
    Yahoo's list for the sector, else the fund's top holdings. Empty for anything that isn't a sector, or with no data."""
    funds = [m["symbol"] for m in markets if m.get("level") == "sector" and m["symbol"]]
    db = _db(config)
    if not funds or db is None:
        return []
    out = []
    with DBSession(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as own:     # agents run in parallel threads
        for fund in funds:
            top, _ = MT.largest_in_sector(own, fund)
            picked = [c["symbol"] for c in top if SYMBOL_OK.match(str(c.get("symbol") or ""))][:SECTOR_NEWS_COMPANIES]
            if picked:
                steps.append(f"sector_companies({fund}) → {', '.join(picked)}")
            out += picked
    return out


def _news_answer(state: FinanceState, config: RunnableConfig, text: str, tickers: list[str], resolved: list[dict], markets: list[dict],
                 tried: list[str]) -> dict:
    """Companies are fetched by ticker and markets by their news terms ("feeds"); stored stories are searched by ticker and by
    market tag. The model's topic is used when there is one ("" = just the latest); without an LLM it is read from the words."""
    cfg, steps = get_config()["news_index"], []
    label = ", ".join([*tickers[:3], *(m["name"] for m in markets)][:4]) or "the market"
    if tickers and not markets and NEWS.asks_about_sector(text):
        return _sector_news(tickers[0], config, steps)
    leaders = _sector_leaders(config, markets, steps)
    feeds = list(dict.fromkeys([*tickers, *(t for m in markets for t in m["news"]), *leaders]))
    tags = list(dict.fromkeys([*tickers, *(t for m in markets for t in MK.search_tags(m)), *leaders]))
    llm_topic = state["entities"].get("topic")
    mentions = [x for r in resolved for x in (r["mention"], r["name"])] + [w for m in markets for w in MK.words(m)]
    # topic or just the latest: by how similar what's left of the question is to a plain request for news (no word list
    # and no model's say-so); without embeddings, by the words left over and the model's topic
    carried = [c.get("name") or "" for c in CTX.carried(state).get("companies") or []]        # a follow-up's company, by name
    named = [*mentions, *tickers, *leaders, *carried, *(r.get("name") or "" for r in resolved)]
    generic = NEWS.generic_score(text, named)
    if generic is None:
        topic = NEWS.topic_words(text if llm_topic is None else llm_topic, tickers, mentions)     # "tech sector news" is only the subject again
        query = (llm_topic if topic else "") or text                # the model's topic phrase searches better than the whole question
    else:
        rest = NEWS.residual(text, named)
        topic = [] if generic >= NEWS.GENERIC_MIN else [rest]
        query = (rest if tags and rest else text)                   # the ticker filter already names the company
        steps.append(f"topic check: {'latest news' if not topic else repr(rest)} (similarity to a plain news request {generic:.2f})")
    days = NEWS.time_window(text, cfg["retention_days"]) or cfg["default_days"]
    db = _db(config)
    if db is None:
        raise RuntimeError("no database session for news lookup")
    envs = None
    if not topic:
        with DBSession(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as own:     # agents run in parallel threads; a Session isn't shareable
            envs = _live_envs(own, feeds)
        subjects = [*(r.get("name") or r["symbol"] for r in resolved), *(t for t in tickers if t not in {r["symbol"] for r in resolved}),
                    *(m["name"] for m in markets), *leaders]
        live = _live_news(envs, label, count=NEWS.count_asked(text, NEWS_MAX_ASKED), days=NEWS.time_window(text, cfg["retention_days"]),
                          tags=tags, subjects=subjects if feeds else [])
        if live:
            live["trace"] = steps + live["trace"]
            if not feeds:                                         # no company or market named or carried: say so rather than pick one
                live["agent_outputs"]["news"].update(reading=NEWS_MARKET_READING, alternatives=NEWS_MARKET_ALTERNATIVES)
            return live
        tried.append(_fetched_note(envs, label))
    try:
        hits = _relevant_news(query, tags, days)
        tried.append("searched the indexed stories" + (f" for {label}" if tags else ""))
        if not hits and feeds:                                    # not indexed yet: fetch the headlines now, index them, search again
            if envs is None:
                with DBSession(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as own:
                    envs = _live_envs(own, feeds)
                tried.append(_fetched_note(envs, label))
            added = sum(news_index_now(sym, env["data"]["items"]) for sym, env in envs if sym and env["data"]["items"])
            steps.append(f"news_latest({label}) → {sum(len(e['data']['items']) for _, e in envs)} stories, {added} newly indexed")
            hits = _relevant_news(query, tags, days)
    except Exception as e:  # noqa: BLE001 — a broken index must not break chat
        log.warning("news search failed: %s", e)
        return _news_none(days, tried, f"news_search → failed ({type(e).__name__})", unavailable=True)
    if hits and topic and generic is not None:              # similar is not the same as about: keep the stories on the topic
        hits, note = _about(hits, [*[r.get("name") or r["symbol"] for r in resolved], *(m["name"] for m in markets)],
                            topic=NEWS.residual(text, named))
        if note:
            steps.append(note)
    web = []
    if len(hits) < cfg.get("web_min_stories", 3) and web_news_enabled():        # too little in the index and on Yahoo: the web
        web = _web_stories(" ".join(x for x in (label if feeds else "", llm_topic or text) if x), days, feeds, hits, steps, tried)
        hits = (hits + web)[:cfg["top_k"]]
    if not hits:
        fallback = _live_news(envs, label, f"I found no stories about that specifically in the last {days} days. ") if envs and feeds else None
        if fallback:                                              # the feed has stories, just none on this topic: show them, labelled
            fallback["confidence"] = "medium"
            fallback["trace"] = steps + [f"news_search({days}d, {label}) → no relevant stories; showing the latest headlines"]
            return fallback
        return _news_none(days, tried, "; ".join(steps + [f"news_search({days}d, {label}) → no relevant stories"]))
    fetched = datetime.fromtimestamp(max(h.get("ingested_at") or 0 for h in hits), timezone.utc).isoformat()
    where = "Yahoo Finance and web news search" if web else "Yahoo Finance"
    stories, read = _with_articles(hits)
    return _news_out(f"Stories from the last {days} days that match the question ({where})", stories,
                     data_info={"provider": "yfinance+tavily" if web else "yfinance", "fetched_at": fetched, "freshness": "cached"},
                     confidence="medium" if web else "high" if hits[0]["score"] >= cfg["min_score"] + 0.1 else "medium",
                     trace="; ".join(steps + [f"news_search({days}d, {label}) → {len(hits)} stories, best {hits[0]['score']:.2f}"]
                                     + ([read] if read else [])))


def _web_stories(query: str, days: int, feeds: list[str], have: list[dict], steps: list[str], tried: list[str]) -> list[dict]:
    """Recent articles from Tavily's news search that the index and Yahoo didn't have, indexed under the first feed (so the next
    question finds them without another paid search). Never raises: a failed web search just adds nothing."""
    try:
        found = web_news(query, days)
    except WebSearchUnavailable as e:
        steps.append(f"web_news → unavailable ({e})")
        return []
    seen = {h.get("url") for h in have}
    new = [{**w, "ingested_at": datetime.now(timezone.utc).timestamp()} for w in found if w["url"] not in seen]
    tried.append("searched web news")
    if new:
        try:
            news_index_now(feeds[0] if feeds else None, new)
        except Exception:  # noqa: BLE001 — indexing is best-effort
            log.warning("could not index web news stories", exc_info=True)
    steps.append(f"web_news({query!r}, {days}d) → {len(new)} new stories")
    return new


@safe("portfolio")
def portfolio_node(state: FinanceState, config: RunnableConfig):
    """Sections chosen by the question (portfolio_report.focus); a general or 'analyse my portfolio' question gets the full
    report, shown word for word so the synthesizer doesn't shorten it to a few headline numbers."""
    holdings = state.get("holdings") or []
    if not holdings:
        return _out("portfolio", "I don't see a portfolio yet. Add your holdings (or load a sample) on the **Portfolio** tab and ask me again.",
                    confidence="medium", trace="portfolio: no holdings")
    risk = state.get("profile", {}).get("risk_tolerance", "moderate")
    db = _db(config)                 # shared with the market agent's thread: every use goes through the market service, which serialises them
    holdings = with_purchase_prices(db, holdings)
    instruments, info = portfolio_instruments(db, [h["ticker"] for h in holdings])
    a = analyze_portfolio(holdings, instruments, risk)
    if a["empty"]:
        return _out("portfolio", "None of your holdings could be priced, so I can't analyse them yet.", confidence="low", trace="portfolio: nothing priced")
    sections = PR.focus(state["question"])
    perf = portfolio_history(db, a["holdings"]) if db is not None else None
    div = None
    if db is not None and "income" in sections:
        try:
            div = portfolio_dividends(db, a["holdings"])
        except Exception:  # noqa: BLE001 — dividends are optional: the section says they're unavailable
            log.warning("portfolio dividends unavailable", exc_info=True)
    full = sections == PR.SECTIONS
    return _out("portfolio", PR.report(a, perf, div, sections, risk), data_info=info, verbatim=full,
                trace=f"portfolio_analysis({len(holdings)} holdings, {'full report' if full else '+'.join(sections)}) "
                      f"→ score {a['diversification_score']} ({info['freshness']})")


def _saved_projection(state: FinanceState, g: dict) -> tuple[str, dict]:
    risk = g.get("risk_tolerance") or state.get("profile", {}).get("risk_tolerance", "moderate")
    return risk, project_goal(g["target_amount"], g["horizon_years"], g.get("current_savings", 0), g.get("monthly_contribution", 0),
                              get_config()["risk_profiles"][risk])


def saved_plan_figures(state: FinanceState) -> str:
    """The saved plan's figures as lines for the calculator's prompt, when the message is about the user's plan: they are the
    user's own numbers (so the calculator may use them as "user" inputs), and the projection is computed here in Python."""
    g = state.get("saved_goal")
    q = f"{state.get('original_question') or ''} {state['question']}"
    if not g or not g.get("target_amount") or not g.get("horizon_years") or not (
            R.refers_to_plan(q) or "goal" in (state.get("intent") or [])):
        return ""
    risk, r = _saved_projection(state, g)
    current, monthly, years = g.get("current_savings", 0) or 0, g.get("monthly_contribution", 0) or 0, g["horizon_years"]
    paid_in = current + monthly * 12 * years
    # plain numbers (no "$" or thousands commas): the calculator copies them into its formulas
    return (f"The user's saved {g['goal_type']} plan on the Goals tab (their own numbers, in dollars; already computed, "
            f"use them as inputs):\n"
            f"- target {r['target']:.0f} in {years} years\n"
            f"- already saved {current:.0f}; contributing {monthly:.0f} a month\n"
            f"- {risk} risk profile, assumed return {r['annual_return_assumption'] * 100:g}% a year, compounded monthly\n"
            f"- projected value after {years} years: {r['projected_value']:.2f}\n"
            f"- total paid in: {paid_in:.0f} ({current:.0f} + {monthly:.0f} x {12 * years} months)\n"
            f"- investment growth (projected value minus paid in): {r['projected_value'] - paid_in:.2f}\n"
            f"- not given: the account type (taxable, 401(k)/IRA or Roth are taxed differently) and any tax rate; a rate "
            f"is an assumption to state (a sample value), not something to calculate")


def _saved_goal_answer(state: FinanceState, g: dict) -> dict:
    risk, r = _saved_projection(state, g)
    lines = [f"Based on your {g['goal_type']} plan on the **Goals** tab (${r['target']:,.0f} in {g['horizon_years']} years, "
             f"${g.get('current_savings', 0):,.0f} saved so far, ${g.get('monthly_contribution', 0):,.0f} a month, {risk} profile, "
             f"assuming a steady {r['annual_return_assumption'] * 100:.0f}% yearly return):",
             f"- Projected value: about **${r['projected_value']:,.0f}**"
             + (" — on track." if r["on_track"] else f", ${r['shortfall']:,.0f} short of the target."),
             f"- Reaching the target would take about **${r['required_monthly']:,.0f} a month**.",
             "\n_This is a simple illustration. Real returns vary year to year and are never guaranteed._"]
    return _out("goal", "\n".join(lines), goal_type=g.get("goal_type"),
                trace=f"saved goal ({g['goal_type']}, ${r['target']:,.0f}, {g['horizon_years']}y) → ${r['required_monthly']:,.0f}/mo")


# Sample figures for "give me an example of a savings goal for a house": typical, round numbers, said to be samples
GOAL_EXAMPLES = {"house": {"home_price": 300_000, "down_payment_pct": 0.20, "years": 5},
                 "education": {"target": 100_000, "years": 15},
                 "retirement": {"target": 1_000_000, "years": 30},
                 "other": {"target": 15_000, "years": 3}}
GOAL_EXAMPLE_WHAT = {"education": "a child's college fund", "retirement": "retirement savings", "other": "a big purchase"}
SHORT_HORIZON_YEARS = 5          # money needed this soon usually sits in savings or conservative investments


def _goal_kind(state: FinanceState) -> str | None:
    """The goal type the message is about: the one it names, else the one of the worked example it follows on from."""
    kind = R.goal_kind(f"{state.get('original_question') or ''} {state['question']}")
    scen = CTX.current_scenario(state)
    return kind or (scen.get("goal_type") if scen.get("kind") == "savings_goal" else None)


def _goal_scenario(kind: str | None, target: float, years: int, monthly: float, annual_return: float, extra: dict | None = None,
                   text: str = "") -> dict:
    """The savings goal as the turn's worked example (context.scenario_line), for a follow-up such as "how is it taxed?"."""
    figures = {**(extra or {}), "target": target, "years": years, "monthly": round(monthly), "annual_return": annual_return}
    return {"kind": "savings_goal", "goal_type": kind or "other", "figures": figures,
            "text": text or f"saving ${target:,.0f} over {years} years (about ${monthly:,.0f} a month)"
                            + (f" for {GOAL_EXAMPLE_WHAT[kind]}" if kind in GOAL_EXAMPLE_WHAT else "")}


def _example_goal(state: FinanceState, kind: str) -> dict:
    """A worked example of a savings goal with sample figures, computed here (the writer once made one up)."""
    ex = GOAL_EXAMPLES[kind]
    years = ex["years"]
    risk = "conservative" if years <= SHORT_HORIZON_YEARS else state.get("profile", {}).get("risk_tolerance", "moderate")
    rate = get_config()["risk_profiles"][risk]
    if kind == "house":
        price, share = ex["home_price"], ex["down_payment_pct"]
        target = price * share
    else:
        target = ex["target"]
    r = project_goal(target, years, 0, 0, rate)
    monthly = r["required_monthly"]
    paid_in = monthly * 12 * years
    if kind == "house":
        head = [f"**Example: a savings goal for a house down payment** (sample figures)",
                f"- Home price: **${price:,.0f}**. A {share * 100:.0f}% down payment is **${target:,.0f}**: that is the goal's target.",
                f"- Time frame: **{years} years**, starting from $0."]
        scen = _goal_scenario("house", target, years, monthly, rate, {"home_price": price, "down_payment_pct": share},
                              f"saving ${target:,.0f} over {years} years (about ${monthly:,.0f} a month) for a "
                              f"{share * 100:.0f}% down payment on a ${price:,.0f} house")
    else:
        head = [f"**Example: a savings goal for {GOAL_EXAMPLE_WHAT[kind]}** (sample figures)",
                f"- Target: **${target:,.0f}** in **{years} years**, starting from $0."]
        scen = _goal_scenario(kind, target, years, monthly, rate)
    why = (f"Money needed within {SHORT_HORIZON_YEARS} years usually sits in savings or conservative investments, so this "
           f"assumes a steady {rate * 100:g}% yearly return." if years <= SHORT_HORIZON_YEARS
           else f"With a {risk} risk profile this assumes a steady {rate * 100:g}% yearly return.")
    lines = [*head, f"- {why}",
             f"- Saving about **${monthly:,.0f} a month** reaches it: ${paid_in:,.0f} paid in, about ${target - paid_in:,.0f} "
             f"from growth (with no growth at all it would take ${target / (12 * years):,.0f} a month).",
             "- To make it your own, put your figures on the **Goals** tab: it tracks the plan and shows the range of outcomes.",
             "\n_This is a simple illustration with sample numbers. Real returns vary and are never guaranteed._"]
    res = _out("goal", "\n".join(lines), verbatim=True, goal_type=kind,
               trace=f"goal: worked example ({kind}, ${target:,.0f}, {years}y, {rate * 100:g}%) → ${monthly:,.0f}/mo")
    res["turn_context"] = {"scenario": scen}
    return res


def _changed_goal(scen: dict) -> dict:
    """The house example with a loan: the down payment left to save (price − loan) and its monthly saving, against the
    example before the change, and the loan's monthly payment; computed here."""
    from src.core.income_tax import mortgage_first_year
    f, p = scen["figures"], scen.get("previous") or {}
    price, loan, rate, term, years = f["home_price"], f["loan_amount"], f["loan_rate"], f["loan_years"], f["years"]
    target, monthly = f["target"], f["monthly"]
    pay = mortgage_first_year(loan, rate, term)
    lines = [f"**Your house example with a ${loan:,.0f} loan at {rate * 100:g}%** (sample figures)",
             f"- The home still costs **${price:,.0f}**, so the loan leaves **${target:,.0f}** to pay up front "
             f"(${price:,.0f} − ${loan:,.0f})."]
    if p.get("target"):
        more = target - float(p["target"])
        lines.append(f"- That is **${abs(more):,.0f} {'more' if more > 0 else 'less'}** to save than the example's "
                     f"${float(p['target']):,.0f} down payment.")
    lines.append(f"- Saving it over **{years} years** at a steady {f.get('annual_return', 0.04) * 100:g}% takes about "
                 f"**${monthly:,.0f} a month**" + (f" (instead of ${float(p['monthly']):,.0f})." if p.get("monthly") else "."))
    lines.append(f"- The loan: ${loan:,.0f} at {rate * 100:g}% over {term} years is **${pay['payment']:,.0f} a month**, "
                 f"about ${pay['interest']:,.0f} of interest in the first year.")
    if p.get("loan_amount") and p.get("loan_rate"):
        old = mortgage_first_year(float(p["loan_amount"]), float(p["loan_rate"]), int(p.get("loan_years") or term))
        lines.append(f"- Before the change: a ${float(p['loan_amount']):,.0f} mortgage at {float(p['loan_rate']) * 100:g}% is "
                     f"${old['payment']:,.0f} a month, so the payment is **${abs(old['payment'] - pay['payment']):,.0f} a month "
                     f"{'lower' if pay['payment'] < old['payment'] else 'higher'}**.")
    for note in scen.get("assumed") or []:
        lines.append(f"- Assumed: {note}.")
    lines.append("\n_This is a simple illustration with sample numbers. Real returns and loan terms vary._")
    res = _out("goal", "\n".join(lines), verbatim=True, goal_type="house",
               trace=f"goal: changed example (loan ${loan:,.0f} at {rate * 100:g}%) → save ${target:,.0f}, ${monthly:,.0f}/mo; "
                     f"loan ${pay['payment']:,.0f}/mo")
    res["turn_context"] = {"scenario": scen}
    return res


@safe("goal")
def goal_node(state: FinanceState, config: RunnableConfig):
    e = state["entities"]
    saved = state.get("saved_goal")
    if state.get("scenario_now"):                                 # "what if I borrow $200,000 at 1.5%?" after the house example
        return _changed_goal(state["scenario_now"])
    kind = _goal_kind(state)
    if saved and kind and kind != saved.get("goal_type"):        # a house question isn't about the saved retirement plan
        saved = None
    if saved and not (e["target_amount"] or e["years"]):          # "am I on track?" -> use the plan saved on the Goals tab
        return _saved_goal_answer(state, saved)
    if not (e["target_amount"] and e["years"]):
        typed = f"{state.get('original_question') or ''} {state['question']}"
        if CP.wants_example(typed) and not (e["target_amount"] or e["years"]):
            return _example_goal(state, kind or "other")
        return _out("goal", GOAL_ASK, status="need_info", choices=GOAL_CHOICES, confidence="medium", trace="goal: missing target or years → ask")
    cfg = get_config()
    risk = state.get("profile", {}).get("risk_tolerance", "moderate")
    r = project_goal(e["target_amount"], e["years"], 0, e["monthly_amount"] or 0, cfg["risk_profiles"][risk])
    lines = [f"For a target of **${r['target']:,.0f}** in **{e['years']} years** ({risk} profile, assuming a steady "
             f"{r['annual_return_assumption'] * 100:.0f}% yearly return):"]
    if e["monthly_amount"]:
        lines.append(f"- Saving ${e['monthly_amount']:,.0f} a month would grow to about **${r['projected_value']:,.0f}**"
                     + (" — on track." if r["on_track"] else f", ${r['shortfall']:,.0f} short of the target."))
    lines.append(f"- Reaching the target would take about **${r['required_monthly']:,.0f} a month**.")
    lines.append("\n_This is a simple illustration. Real returns vary year to year and are never guaranteed._")
    res = _out("goal", "\n".join(lines), goal_type=kind,
               trace=f"project_goal(${e['target_amount']:,.0f}, {e['years']}y, {risk}) → ${r['required_monthly']:,.0f}/mo")
    res["turn_context"] = {"scenario": _goal_scenario(kind, float(e["target_amount"]), int(e["years"]),
                                                      r["required_monthly"], r["annual_return_assumption"])}
    return res


@safe("calc")
def calc_node(state: FinanceState, config: RunnableConfig):
    """The calculator's steps (calc_pipeline, mds/calc-pipeline-design.md): understand, define, find a sourced and
    cross-checked equation, fill its variables; Python validates, computes and shows the working with quotes. Questions
    no single equation answers go to the plan path. Without an LLM a keyword fallback runs a CATALOG calculator."""
    q = state["question"]
    if current_llm() is None:
        name, args = CALC.keyword_request(q)
        if name is None:
            return _out("calc", CALC.ASK, status="need_info", choices=CALC.CHOICES, confidence="medium",
                        trace="calc (keywords): no calculation recognised → ask")
        try:
            text = CALC.run(name, args)
        except (TypeError, ValueError) as e:
            return _out("calc", f"{CALC.ASK}\n\n_({e})_", status="need_info", choices=CALC.CHOICES, confidence="medium",
                        trace=f"calc (keywords): {name} rejected inputs ({e}) → ask")
        shown = ", ".join(f"{k}={v:g}" for k, v in args.items() if v not in (None, "", 0))
        return _out("calc", text, verbatim=True, trace=f"calc (keywords): {name}({shown})")
    # a new topic starts clean: an earlier question's figures would otherwise become extra targets or "user" numbers
    recent = H.transcript(state.get("history")) if state.get("follow_up") else ""
    known = CTX.describe(CTX.carried(state))
    plan = saved_plan_figures(state)            # "how much tax if the plan runs as planned?": the Goals tab's numbers are theirs
    prompt = (f"Recent conversation:\n{recent or '(none)'}\n\n"
              + (f"Figures from the previous answer:\n{known}\n\n" if known else "")
              + (f"{plan}\n\n" if plan else "") + f"Message: {q}")
    out = calculate(q, prompt, f"{q}\n{recent}\n{known}\n{plan}")
    steps = [f"calc step {line}" for line in out.trace]
    if out.kind == "needs":
        res = _out("calc", CALC.needs_input_text(out.needs.label, out.needs.inputs), status="need_info",
                   choices=CALC.CHOICES, confidence="medium",
                   trace=f"calc (LLM plan): no number is the user's → ask for {', '.join(out.needs.inputs)}")
    elif out.kind == "ask" and out.text:
        res = _out("calc", out.text, status="need_info", choices=CALC.CHOICES, confidence="medium",
                   trace=out.note or "calc (LLM steps): → ask")
    elif out.kind == "ask":                               # nothing worked: confirm what they meant, not a fixed request
        text, readings = CP.confirm(q, out.understood, out.errors)
        res = _out("calc", text, status="need_info", choices=readings or CALC.CHOICES, readings=bool(readings),
                   confidence="medium", trace=(out.note or "calc (LLM steps): → ask") + " → confirm with the user")
    else:
        sources = [{"id": f"calc:{s['url']}", "title": s["title"], "url": s["url"]}
                   for q_ in out.result.get("quotes", []) for s in q_["sources"] if s.get("url")]
        res = _out("calc", CALC.plan_text(out.result), verbatim=True, sources=sources,
                   trace=out.note or "calc (LLM steps): " + out.trace[-1])
    res["trace"] = steps + res["trace"]
    return res


def calculate(question: str, prompt: str, known_text: str) -> CP.Outcome:
    """The calculator's steps (calc_pipeline): a sourced equation when one fits, else the plan path."""
    def plan_path(example: bool, hint: str = "") -> CP.Outcome:
        result, errors, _ = plan_calculation(question, prompt + hint + (CP.EXAMPLE_NOTE if example else ""), known_text,
                                             example)
        if isinstance(result, PLAN.NeedsInput):
            return CP.Outcome("needs", needs=result, errors=errors)
        if result is None:
            return CP.Outcome("ask", errors=errors,
                              note="calc (LLM plan): rejected twice (" + " | ".join(errors) + ") → ask")
        values = "; ".join(f"{s['name']} = {result['values'][s['name']]:.6g}" if result["values"].get(s["name"]) is not None
                           else f"{s['name']} ({s['kind']})" for s in result["steps"])
        note = f"calc (LLM plan{', repaired after: ' + errors[0] if errors else ''}): {result['label']}: {values}"
        if result["checks"]:
            note += f"; {len(result['checks'])} check(s) passed"
        if result["set_aside"]:
            note += f"; {len(result['set_aside'])} check(s) set aside by the judge"
        return CP.Outcome("answer", result=result, errors=errors, note=note)
    return CP.calculate(question, prompt, known_text, plan_path)


JUDGE_CALLS = 2                                         # most judge calls per question


def plan_calculation(question: str, prompt: str, known_text: str,
                     example: bool = False) -> tuple[dict | PLAN.NeedsInput | None, list[str], list]:
    """Ask the LLM for a plan and run it. When only one of the plan's own checks disagrees, a judge call decides which is
    wrong: a wrong check is set aside (and shown in the answer), a wrong plan goes to the repair round with the judge's
    reason. Any other rejection goes back to the LLM once with the error. Returns (the executed plan, or NeedsInput when
    no number is the user's, or None when both plans were rejected; the rejection messages; the plans)."""
    plans, errors, judged = [_json(ask_llm(CALC.PLAN_SYSTEM, prompt))], [], 0
    for attempt in (1, 2):
        skip, set_aside = frozenset(), []
        while True:
            try:
                result = PLAN.run(plans[-1], question, known_text, skip, example=example)
                return {**result, "set_aside": set_aside}, errors, plans
            except PLAN.NeedsInput as e:
                return e, errors, plans
            except PLAN.CheckFailed as e:
                error = str(e)
                if judged < JUDGE_CALLS:
                    judged += 1
                    verdict = _json(ask_llm(CALC.JUDGE_SYSTEM, CALC.judge_prompt(question, plans[-1], e))) or {}
                    why = " ".join(str(verdict.get("reasoning") or "").split())
                    if len(why) > 600:                           # cut at a sentence, not mid-word
                        why = why[:600].rsplit(". ", 1)[0] + "."
                    if verdict.get("wrong") == "check":
                        skip |= {e.index}
                        c = e.check
                        set_aside.append({"when": ", ".join(f"`{k} = {v:g}`" for k, v in c["when"].items()),
                                          "expect": c["expect"], "why": why,
                                          "expected": "none" if e.expected is None else f"{e.expected:.6g}",
                                          "actual": "none" if e.actual is None else f"{e.actual:.6g}"})
                        continue
                    error += f" A reviewer judged {'the plan' if verdict.get('wrong') == 'plan' else 'it unclear'}: {why}"
            except PLAN.PlanError as e:
                error = str(e)
            break
        errors.append(error)
        if attempt == 1:
            plans.append(_json(ask_llm(CALC.PLAN_SYSTEM, CALC.repair_prompt(prompt, plans[-1], error))))
            if plans[-1] == plans[-2]:                           # the same plan again: say so, once
                plans.append(_json(ask_llm(CALC.PLAN_SYSTEM, CALC.repair_prompt(prompt, plans[-1], error, True))))
    return None, errors, plans


def clarify_node(state: FinanceState, config: RunnableConfig):
    return _out("clarify", CLARIFY_MESSAGE, status="need_info", choices=STARTER_CHOICES, confidence="low",
                trace="clarify: asked the user to rephrase")


READ_ONLY_FLAG = "⚠️ **Request flagged: Finnie is read-only.**"
READ_ONLY_MESSAGES = {
    "trade": ("I can't place trades, orders or transfers: I'm not connected to any brokerage or bank account, and every agent here "
              "can only read. I can explain how this kind of order works or look up the figures for you."),
    "data": ("I can't change your portfolio, goals, profile or chat history from the chat: every agent here can only read them. "
             "You can edit them yourself on the **Portfolio** and **Goals** tabs and in the profile sidebar."),
    "system": ("I can't change the system, its data, files or settings: every agent here has read-only access. "
               "I can answer questions using what's already there."),
}
READ_ONLY_CHOICES = ["Is my portfolio diversified?", "How does a limit order work?", "Am I on track for my goal?"]


def read_only_node(state: FinanceState, config: RunnableConfig):
    """The read-only guardrail (mds/read-only-guardrail.md): agents read the user's data and the market, they never change
    anything. A request to write (edit holdings/goals/profile, trade, move money, alter the system) is flagged, not attempted."""
    kind = state["entities"].get("write_request") or "data"
    return _out("read_only", f"{READ_ONLY_FLAG} {READ_ONLY_MESSAGES[kind]}", status="need_info", choices=READ_ONLY_CHOICES,
                confidence="high", verbatim=True, trace=f"read_only: flagged a request to change something ({kind}); nothing was changed")


OFF_TOPIC_FLAG = "🚫 **Off topic: Finnie only covers personal finance.**"
OFF_TOPIC_MESSAGE = ("I can help with money, saving, investing, markets, taxes, and your own portfolio and goals, but not with "
                     "other subjects. Ask me something about finance, or pick one of these.")


def off_topic_node(state: FinanceState, config: RunnableConfig):
    """The topic guardrail (mds/topic-guardrail.md): a message the LLM router finds is not about finance gets a fixed reply,
    and no agent, research or web search runs for it."""
    return _out("off_topic", f"{OFF_TOPIC_FLAG} {OFF_TOPIC_MESSAGE}", status="need_info", choices=STARTER_CHOICES,
                confidence="high", verbatim=True, trace="off_topic: not about finance; declined without looking it up")


# ---------------------------------------------------------------- verifier + research
_json = first_json


SUFFICIENCY_SYSTEM = (
    "You check whether retrieved SOURCES contain the information needed to answer a QUESTION from a personal-finance "
    "learner. Reply with ONLY JSON: {\"answers\": true} if the sources answer it fully or mostly, otherwise "
    "{\"answers\": false, \"missing\": \"<what the question asks for that the sources lack, under 15 words>\"}. When ANSWERED BY "
    "OTHER AGENTS is given and it already supplies everything the sources lack, reply {\"answers\": false, \"covered\": true}. "
    "When the note says a calculator works out the figure, a number computed from the user's own figures is not the "
    "sources' job: judge only whether they explain the rules or ideas the question needs (how the gains are taxed, say).")
CALC_NOTE = "\n\nNOTE: a calculator agent works out the figure the question asks for from the user's numbers."
CALC_QUESTION = ("{} (A calculator works out the figure itself. Judge only whether the sources explain the rules or ideas "
                 "behind it, such as how and when this is taxed.)")
OTHERS_CHARS = 1500                       # of each other agent's answer shown to the sufficiency check
CHOICES_SYSTEM = (
    "A personal-finance education assistant needs more details before it can help. Write 2 or 3 short messages the USER "
    "could send next, each covering a likely thing they mean (for example learning the concepts versus planning the "
    "numbers). Write them in the user's own voice (\"I\", \"my\"), never as questions to the user, never using \"you\" "
    "or \"your\". Each must work on its own, with example numbers where a plan needs them, under 15 words. "
    "Good: \"I want to save $20,000 for a house in 3 years\", \"What should I know before buying a house?\". "
    "Bad: \"What is your savings goal?\". Reply with ONLY JSON: {\"choices\": [\"...\", \"...\"]}.")
# "your", "you're"… or a bare "you", except "can/could/would you", which is the user addressing the assistant
_ADDRESSES_USER = re.compile(r"\byour(s)?\b|\byou('re|'ll|'ve)\b|(?<!can )(?<!could )(?<!would )\byou\b", re.I)
TOPICS_SYSTEM = (
    "Name up to 3 English Wikipedia articles about the general concepts behind a personal-finance question, most useful "
    "first. Use exact, existing encyclopedia titles for concepts, never companies or products (for example \"Mortgage\", "
    "\"Down payment\", \"Closing costs\"). Reply with ONLY JSON: {\"topics\": [\"...\"]}.")


def verifier_node(state: FinanceState, config: RunnableConfig):
    """Recheck every agent output before an answer is written. Runs again after research and after each replan, but checks
    each output only once (`verified`):
      - a knowledge-base answer whose sources don't answer the question becomes not_found (→ research);
      - a researched (Wikipedia) answer that doesn't answer it either becomes not_found and is kept as a `fallback`
        (→ web search, then replan looks for another agent; the fallback is used only if none answers);
      - a web answer that doesn't answer it becomes not_found too, but is never kept as the fallback;
      - any of those whose gap another agent's answer already fills (the market figures for "how is the tech sector doing?")
        is dropped as `covered`: no research, web search or replan for something already answered;
      - follow-up questions get choices the user can click."""
    llm_on = current_llm() is not None
    updates, trace = {}, []
    outputs = state.get("agent_outputs") or {}
    for agent, o in outputs.items():
        if o.get("verified"):
            continue
        status = o.get("status", "answered")
        if status == "answered" and (wanted := _off_target_goal(state, o)):
            # the saved retirement plan, replanned in for a question about the house example: about another goal, so unusable
            updates[agent] = {**o, "status": "not_found", "content": "", "sources": [], "fallback": None, "verified": True,
                              "researched": True, "web_searched": True, "handed_off": True,
                              "missing": f"an answer about the {wanted} goal"}
            trace.append(f"verifier: {agent} answers about the {o['goal_type']} goal, not the {wanted} one the question is about → dropped")
            continue
        if status == "answered" and o.get("origin") in ("kb", "wikipedia", "web") and llm_on:
            others = _answered_by_others(outputs, agent)
            shown = "".join(f"\n[{a}]\n{c[:OTHERS_CHARS]}\n" for a, c in others.items())
            calc_too = agent != "calc" and ("calc" in outputs or "calc" in (state.get("intent") or []))
            question = CALC_QUESTION.format(state["question"]) if calc_too else state["question"]
            verdict = _json(ask_llm(SUFFICIENCY_SYSTEM, f"QUESTION: {question}\n\nSOURCES:\n{o['content'][:6000]}"
                                                        + (f"\n\nANSWERED BY OTHER AGENTS:{shown}" if others else "")
                                                        + (CALC_NOTE if calc_too else "")))
            if verdict is not None and verdict.get("answers") is False and verdict.get("covered") is True and others:
                updates[agent] = {**o, "status": "not_found", "content": "", "sources": [], "fallback": None, "covered": True,
                                  "verified": True, "researched": True, "web_searched": True, "handed_off": True}
                trace.append(f"verifier: {agent} not needed, {', '.join(others)} already answer{'s' if len(others) == 1 else ''} the question")
                continue
            if verdict is not None and verdict.get("answers") is False:
                missing = str(verdict.get("missing") or "").strip()
                if o["origin"] == "kb":
                    updates[agent] = {**o, "status": "not_found", "content": "", "sources": [], "missing": missing}
                    trace.append(f"verifier: {agent} knowledge-base sources don't answer the question → research")
                else:                    # unchecked web pages never become the fallback; an earlier Wikipedia one is kept
                    fallback = o.get("fallback") if o["origin"] == "web" else {**o, "verified": True}
                    updates[agent] = {**o, "status": "not_found", "content": "", "sources": [], "missing": missing,
                                      "verified": True, "fallback": fallback}
                    trace.append(f"verifier: {agent} {'web' if o['origin'] == 'web' else 'researched'} sources don't answer the question either"
                                 + (f" (missing: {missing})" if missing else ""))
                continue
            kept = {k: v for k, v in o.items() if k != "fallback"}       # accepted: an earlier rejected answer can't be used now
            updates[agent] = {**kept, "verified": True}
            trace.append(f"verifier: {agent} sources answer the question" if verdict else f"verifier: {agent} check unavailable, kept")
        elif status == "need_info":
            choices = o.get("choices") or []
            if llm_on and agent not in ("clarify", "read_only", "off_topic") and not o.get("readings"):   # calc's readings already confirm its reading
                reply = _json(ask_llm(CHOICES_SYSTEM, f"User's message: {state['question']}\nWhat the assistant still needs: {o['content']}"))
                picked = [c.strip() for c in (reply or {}).get("choices", [])
                          if isinstance(c, str) and c.strip() and not _ADDRESSES_USER.search(c)][:3]   # must be the user's words
                choices = picked or choices
            updates[agent] = {**o, "choices": choices, "verified": True}
            trace.append(f"verifier: {agent} needs more details → asking with {len(choices)} choices")
        elif status == "not_found" and not o.get("researched"):
            trace.append(f"verifier: {agent} found nothing → research")
        elif status == "answered":
            updates[agent] = {**o, "verified": True}
    return {"agent_outputs": updates, "trace": trace or ["verifier: all agent outputs usable"]}


def _off_target_goal(state: FinanceState, o: AgentOutput) -> str | None:
    """The goal type the question is about, when the output is about another one (None when it fits or either is unknown)."""
    have = o.get("goal_type")
    wanted = _goal_kind(state) if have else None
    return wanted if wanted and wanted != have else None


def _answered_by_others(outputs: dict, agent: str) -> dict[str, str]:
    """{agent: content} of the other agents that answered from their own data (market figures, news, a calculation): not
    retrieved text, which is still being checked itself."""
    return {a: o["content"] for a, o in outputs.items() if a != agent and o.get("status", "answered") == "answered"
            and o.get("content") and o.get("origin") not in ("kb", "wikipedia", "web")}


def _unresolved(o: AgentOutput) -> bool:
    """Not found even after research, and replan hasn't yet looked for another agent to cover it."""
    return o.get("status") == "not_found" and bool(o.get("researched")) and not o.get("handed_off")


def route_after_verifier(state: FinanceState) -> str:
    outputs = (state.get("agent_outputs") or {}).values()
    if any(o.get("status") == "not_found" and not o.get("researched") for o in outputs):
        return "research"
    if web_search_enabled() and any(_needs_web(o) for o in outputs):              # Wikipedia had nothing: try the web
        return "research"
    if (any(_unresolved(o) for o in outputs) and current_llm() is not None       # replan needs the LLM to judge what's missing
            and (state.get("replans") or 0) < get_config()["workflow"].get("max_replans", 3)):
        return "replan"
    return "illustrate"


def _needs_web(o: AgentOutput) -> bool:
    """Not found even after the Wikipedia pass, and not searched on the web yet."""
    return o.get("status") == "not_found" and bool(o.get("researched")) and not o.get("web_searched")


WEB_RESULTS_USED = 3


def _web_research(state: FinanceState, o: AgentOutput, words: int) -> tuple[AgentOutput, str]:
    """Research's second pass: the question on Tavily. Page extracts become an answer the verifier checks like Wikipedia's."""
    o = {**o, "web_searched": True}
    try:
        results = web_search(state["question"])
    except WebSearchUnavailable as e:
        log.warning("web search failed: %s", e)
        return o, f"web_search → failed ({e})"
    dropped = len(results)
    results = [r for r in results if is_finance(r["title"], r["content"])]         # the web answers anything: keep to finance
    dropped -= len(results)
    if not results:
        return {**o, "content": NOT_FOUND_MESSAGE}, "web_search → no relevant results" + (f" ({dropped} not about finance)" if dropped else "")
    used = results[:WEB_RESULTS_USED]
    cut = lambda t: " ".join(t.split()[:words]) + ("…" if len(t.split()) > words else "")          # noqa: E731
    content = o.get("prefix", "") + "\n\n".join(f"**{r['title']}** ({r['domain']})\n\n{cut(r['content'])}" for r in used)
    return ({**o, "status": "answered", "origin": "web", "verified": False, "confidence": "medium", "content": content,
             "sources": [{"id": f"web:{r['url']}", "title": f"{r['title']} ({r['domain']})", "url": r["url"]} for r in used]},
            f"web_search → {len(results)} results, using {', '.join(r['domain'] for r in used)} (best {used[0]['score']:.2f})")


def research_node(state: FinanceState, config: RunnableConfig):
    """Look up not_found topics on Wikipedia. With an LLM the question is first turned into article titles, so a long or
    misspelled sentence still finds the right page; without one the router's keyword query is used. When that pass found
    nothing usable (or the verifier rejected it), a second pass searches the web (Tavily), if a key is set."""
    words, updates, trace, errors = _words(state), {}, [], []
    llm_topics: list[str] | None = None                         # asked once per pass: they depend only on the question
    for agent, o in (state.get("agent_outputs") or {}).items():
        if _needs_web(o) and web_search_enabled():
            updates[agent], note = _web_research(state, o, words)
            trace.append(note)
            continue
        if o.get("status") != "not_found" or o.get("researched"):
            continue
        o = {**o, "researched": True, "verified": False}            # the verifier checks what research finds
        if llm_topics is None:
            llm_topics = []
            if current_llm() is not None:
                reply = _json(ask_llm(TOPICS_SYSTEM, f"Question: {state['question']}"))
                llm_topics = [t.strip() for t in (reply or {}).get("topics", []) if isinstance(t, str) and t.strip()][:3]
                if llm_topics:
                    trace.append(f"research: topics {llm_topics}")
        topics = list(llm_topics)
        lookup = wiki_topic if topics else wiki_search      # LLM titles: exact page first; router keywords: search
        topics = topics or [o.get("query") or state["question"]]
        hits, unavailable = [], False
        try:
            for t in topics:
                if len(hits) == 2:
                    break
                try:
                    hit = lookup(t, words)
                except WikiUnavailable:
                    unavailable = True
                    trace.append(f"{lookup.__name__}('{t}') → unavailable")
                    continue
                trace.append(f"{lookup.__name__}('{t}') → {hit['title'] if hit else 'no relevant article'}")
                if hit and all(h["title"] != hit["title"] for h in hits):
                    hits.append(hit)
        except Exception as e:  # noqa: BLE001 — contain every failure, report it in state
            log.exception("research for %s failed", agent)
            updates[agent] = {**o, "content": "", "error": str(e)}
            errors.append(f"{agent}: {type(e).__name__}")
            continue
        prefix = o.get("prefix", "")
        if hits:
            updates[agent] = {**o, "status": "answered", "origin": "wikipedia", "confidence": hits[0]["confidence"],
                              "content": prefix + "\n\n".join(f"**{h['title']}**\n\n{h['extract']}" for h in hits),
                              "sources": [{"id": f"wikipedia:{h['title']}:{h['revision_id']}", "title": f"{h['title']} (Wikipedia)", "url": h["url"]} for h in hits]}
        elif unavailable:
            updates[agent] = {**o, "content": UNAVAILABLE_MESSAGE, "error": "wiki unavailable"}
            errors.append(f"{agent}: knowledge source unavailable")
        else:
            updates[agent] = {**o, "content": NOT_FOUND_MESSAGE}
    return {"agent_outputs": updates, "trace": trace, "errors": errors}


REPLAN_SYSTEM = """You coordinate the specialist agents of a personal-finance EDUCATION assistant. Some agents could not answer the user's question, even after looking it up on Wikipedia (and the web, when available). Decide which OTHER agents, if any, could supply what is still missing.

AGENTS
- qa: explains financial concepts from a finance knowledge base.
- market: live figures at every level: a company or fund (price, performance, valuation), a sector (return against the S&P 500 and its largest companies' moves), a region or country (its index), a sector's industries, the US market as a whole (indices, every sector ranked, the largest companies, today's most active stocks, market hours), asset classes (rates, commodities, currencies, crypto).
- news: recent headlines about a company, sector, region, topic or the whole market.
- portfolio: analyses the user's own holdings.
- goal: a savings plan to reach a target amount by a date.
- tax: tax rules and account types.
- calc: computes a specific figure (growth, loan payment, doubling time, present value, real return, APY, bond yield).

RULES
- Choose only from the agents listed as AVAILABLE. Never choose an agent that was already tried.
- goal, portfolio and tax only if the user explicitly asked for a savings plan, an analysis of their own holdings, or tax treatment; never because the question mentions retirement, saving or an amount.
- Choose an agent only if its job directly supplies what is missing. If none can, return an empty list: an honest "not found" is better than an unrelated answer.
- What the agents that already answered supplied (listed under ANSWERED) is not missing: never choose an agent to repeat it.
- Usually 0-2 agents.

Reply with ONLY JSON: {"intents": ["market"], "reason": "<one short sentence>"}."""


def replan_node(state: FinanceState, config: RunnableConfig):
    """An agent and the research step both came up empty: ask the LLM which agents not yet tried could supply what is
    missing, and send the question to them (they run in parallel, then back to the verifier). Runs at most
    workflow.max_replans times per question; with no candidate it moves on to the answer."""
    n = (state.get("replans") or 0) + 1
    limit = get_config()["workflow"].get("max_replans", 3)
    outputs = state.get("agent_outputs") or {}
    unresolved = {a: o for a, o in outputs.items() if _unresolved(o)}
    tried = list(state.get("tried_agents") or [])
    available = [i for i in R.INTENTS if i not in tried]
    intents, reason = [], ""
    if available:
        missing = "\n".join(f"- {a}: {o.get('missing') or 'found nothing relevant'}" for a, o in unresolved.items())
        done = {a: o["content"] for a, o in outputs.items() if o.get("status", "answered") == "answered" and o.get("content")}
        answered = "".join(f"\n[{a}]\n{c[:OTHERS_CHARS]}\n" for a, c in done.items()) or " (none)"
        recent = H.transcript(state.get("history"))
        reply = _json(ask_llm(REPLAN_SYSTEM, f"Recent conversation:\n{recent or '(none)'}\n\nQuestion: {state['question']}\n\n"
                                             f"Already tried: {', '.join(tried)}\nWhat is missing:\n{missing}\n\n"
                                             f"ANSWERED:{answered}\n\nAVAILABLE: {', '.join(available)}"))
        intents = list(dict.fromkeys(i for i in (reply or {}).get("intents", []) if i in available))
        reason = str((reply or {}).get("reason") or "").strip()
    res = {"replans": n, "replan_intents": intents, "tried_agents": tried + intents,
           "agent_outputs": {a: {**o, "handed_off": True} for a, o in unresolved.items()},
           "trace": [f"replan {n}/{limit}: " + (f"{', '.join(intents)}" + (f" ({reason})" if reason else "")
                                               if intents else "no other agent can supply what is missing")]}
    e = state.get("entities") or {}
    if {"market", "news"} & set(intents) and not (e.get("tickers") or e.get("indices") or e.get("companies") or e.get("markets")):
        subj = SYM.subjects(state["question"], history=state.get("history"))           # as the router does
        res["entities"] = {**e, "companies": subj["companies"], "markets": subj["markets"], "levels": subj["levels"],
                           "topic": subj["topic"], "excluded": sorted(subj["excluded"])}
        if subj["companies"]:
            res["trace"].append("resolved " + ", ".join(_resolved_label(c) for c in subj["companies"]))
        if subj["markets"]:
            res["trace"].append("markets: " + ", ".join(_market_label(m) for m in subj["markets"]))
    return res


def route_after_replan(state: FinanceState) -> list[str]:
    return sorted(f"{i}_agent" for i in state.get("replan_intents") or []) or ["illustrate"]


def illustrate_node(state: FinanceState, config: RunnableConfig):
    """Add a worked example to conceptual answers: when a Q&A or tax answer is about something numeric, the LLM writes the
    calculation that makes it concrete (with this turn's real figures where they fit, else sample numbers) and the
    calculator works it out like any other question: equation from the knowledge base or the web, computed in Python.
    Skipped for calculations, non-numeric topics and basic mode (no LLM). Follow-up suggestions then let the user vary the
    numbers."""
    outputs = state.get("agent_outputs") or {}
    concept = [o for k, o in outputs.items() if k in ("qa", "tax") and o.get("status", "answered") == "answered" and o.get("content")
               and o.get("origin") != "tax_tools" and not o.get("verbatim_tail")]    # the tax agent's own figures need no example
    if not concept or "calc" in outputs or current_llm() is None or "tax" in outputs:   # tax figures are the tax agent's
        return {"trace": []}
    figures = CTX.describe({"facts": {**(CTX.carried(state).get("facts") or {}), **_key_facts(state.get("market_data") or {})}})
    reply = _json(ask_llm(CALC.EXAMPLE_SYSTEM, f"Question: {state['question']}\n\nAnswer so far:\n{concept[0]['content'][:2500]}"
                          + (f"\n\nFigures:\n{figures}" if figures else "")))
    asked = (reply or {}).get("question")
    if not isinstance(asked, str) or not asked.strip():
        return {"trace": ["illustrate: no calculation fits this topic"]}
    asked = f"Show a worked example: {asked.strip()}"                   # the calculator's worked-example mode: samples allowed
    out = calculate(asked, (f"Figures from this answer:\n{figures}\n\n" if figures else "") + f"Message: {asked}", f"{asked}\n{figures}")
    steps = [f"illustrate: {asked}", *(f"illustrate calc step {line}" for line in out.trace)]
    if out.kind != "answer":
        return {"trace": [*steps, "illustrate: the calculator couldn't work it out → no example"]}
    sources = [{"id": f"calc:{s['url']}", "title": s["title"], "url": s["url"]}
               for q in out.result.get("quotes", []) for s in q["sources"] if s.get("url")]
    return {"agent_outputs": {"example": {"agent": "example", "content": CALC.plan_text({**out.result, "example": True}), "sources": sources,
                                          "data_info": None, "confidence": "high", "error": None, "status": "answered",
                                          "verbatim": True}},
            "trace": [*steps, out.note or "illustrate calc: " + out.trace[-1]]}


# ---------------------------------------------------------------- synthesizer + compliance
SYNTH_SYSTEM = (
    "You are Finnie, a friendly finance educator for beginners. Write the final answer using ONLY the context provided; "
    "do not add facts, numbers, tips or sources of your own, even well-known ones. If the context covers only part of the "
    "question, answer that part and say briefly what you couldn't cover. Match the user's knowledge level. Keep it concise "
    "and in plain language. Never say figures are unavailable when the context or data gives them, and never say a price "
    "moved because of the news, or that the news did or didn't affect it. When the context lists several headlines or "
    "items, cover each one in a bullet list (title, publisher and, only if the context gives the story's summary, that "
    "summary in 2-3 sentences, keeping its facts and figures; never guess what a story says from its title) instead of choosing one. Format with Markdown: "
    "**bold** for key figures, '- ' "
    "bullets for lists. Whenever the answer gives the same figures for two or more items or periods (companies, funds, "
    "indices, sectors, a company against the market), put them in a Markdown table, one row per item and one column per "
    "figure (| A | B | header row, then |---|---|), never as a bullet list per item, so the numbers line up. Never tell the user what to buy or sell and never promise returns. Do not include a disclaimer "
    "(it is added separately). Keep any figures exactly as given. When comparing, compare figures for the same period (today's "
    "change with today's change), never one item's day with another's month. The conversation only explains what the question refers to: "
    "answer the Question from the context, never by repeating an earlier answer or its subject. When the context gives "
    "\"Current <year> figures\", use those figures over any older amount in the other sources and say they are the "
    "<year> figures.")


READING_NOTE = "_I took this as {}. If you meant something else, pick an option below or name the company or topic._"
SCREEN_NOTE = ("_I took this as {}, since you switched from {}. If you meant what we discussed before, "
               "name it (for example “my portfolio” or the ticker)._")


LIST_ITEM_RE = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+")


def link_sources(text: str, sources: list[dict]) -> str:
    """Appends each source's link to the end of the bullet that names it (a headline the answer lists with its summary), so
    the link sits next to what it supports. Sources the answer doesn't name are left for the list under the answer."""
    lines = text.split("\n")
    for s in sources:
        if not s.get("url") or any(s["url"] in line for line in lines):
            continue
        names = {n.lower() for n in (s["title"], re.sub(r"\s*\([^()]*\)$", "", s["title"])) if len(n) >= 12}
        named = lambda line: any(n in line.lower() for n in names) or ((h := _headline(line)) is not None and h.lower() in s["title"].lower())  # noqa: E731
        start = next((i for i, line in enumerate(lines) if LIST_ITEM_RE.match(line) and named(line)), None)
        if start is None:
            continue
        end = start                                  # the item runs on over indented summary lines until a blank line or the next item
        while end + 1 < len(lines) and lines[end + 1].strip() and not LIST_ITEM_RE.match(lines[end + 1]):
            end += 1
        lines[end] = f"{lines[end].rstrip()} [Source]({s['url']})"
    return "\n".join(lines)


HEADLINE_ITEM_RE = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+\*\*([^*]+)\*\*\s*(?:\(|[-–—]\s)")   # "- **Title** (AFP, Oct 30…)", "- **Title** - AFP…"; a short bold label isn't one
HEADLINE_MIN_WORDS = 5


def _headline(line: str) -> str | None:
    """The story title a bullet starts with, or None when the bullet isn't a headline."""
    m = HEADLINE_ITEM_RE.match(line)
    return m.group(1).strip() if m and len(m.group(1).split()) >= HEADLINE_MIN_WORDS else None


def drop_unknown_headlines(reply: str, sources: list[dict]) -> str:
    """Removes headline bullets (with their summary lines) that aren't one of this answer's stories: the model copies earlier
    answers' headlines from the conversation however it's asked. A shortened title still counts as the story's."""
    titles = [x["title"].lower() for x in sources]
    lines, kept, i = reply.split("\n"), [], 0
    while i < len(lines):
        title = _headline(lines[i])
        if title is None or any(title.lower() in t for t in titles):
            kept.append(lines[i])
            i += 1
            continue
        i += 1
        while i < len(lines) and lines[i].strip() and lines[i][:1].isspace() and not LIST_ITEM_RE.match(lines[i]):
            i += 1                                   # its indented summary lines
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _sector_lines(state: FinanceState) -> str:
    """The sector's performance a news question didn't ask for by name (`_with_sector_figures`), to show word for word: the
    model leaves out figures the question doesn't need."""
    if not state["entities"].get("sector_figures"):
        return ""
    return "\n".join(MT.describe_lines({s: {"sector": d["sector"]} for s, d in (state.get("market_data") or {}).items() if "sector" in d}))


def synthesizer_node(state: FinanceState, config: RunnableConfig):
    """Writes the reply from `answered` outputs only. Follow-up questions and "couldn't find" messages are passed through
    word for word, never rewritten, so the model can't turn "I need more details" into an invented answer."""
    outputs = [state["agent_outputs"][k] for k in ORDER if k in state.get("agent_outputs", {})]
    answered = [o for o in outputs if o.get("status", "answered") == "answered" and o.get("content")]
    asks = [o for o in outputs if o.get("status") == "need_info" and o.get("content")]
    missing = [o for o in outputs if o.get("status") == "not_found" and o.get("content")]
    # nothing answered: write from the research the verifier found incomplete, also when another agent asks for details
    # (the tax rules, then the calculator's question about the missing rate)
    partial = [] if answered else [o["fallback"] for o in outputs if o.get("fallback")]
    answered = answered or partial                  # nothing better turned up: write from the research the verifier found incomplete
    choices = list(dict.fromkeys(c for o in [*asks, *(o for o in answered if o.get("asks_user"))]
                                 for c in o.get("choices") or []))[:3]          # the tax agent's one question, as buttons
    if answered:
        exact = [o for o in answered if o.get("verbatim")]          # calculator results: never reworded
        sector_lines = _sector_lines(state)
        prose = [o for o in answered if not o.get("verbatim") and not (sector_lines and o["agent"] == "market")]
        text, mode = "\n\n".join(o["content"] for o in prose), "extractive" if prose else "verbatim"
        if any(o.get("explains_itself") for o in exact):
            # the income-tax steps explain each rule as they apply it: a written intro only repeated their arithmetic
            # (and did it itself); the explaining agents' pages are linked for further reading instead
            links = list({x["url"]: x for o in [*prose, *exact] for x in o.get("sources", [])
                          if x.get("url") and x.get("id", "").startswith("kb:")}.values())[:4]
            text = ("**Read more:** " + " · ".join(f"[{re.sub(r' [(](Wikipedia|Finnie note, from the IRS)[)]$', '', x['title'])}]({x['url']})"
                                                  for x in links)
                    if links else "")
            prose, mode = [], "verbatim (steps explain themselves)"
        if prose and current_llm() is not None:
            history = H.transcript(state.get("history")) if state.get("follow_up") else ""     # a new question can only be misled by it
            context = "\n\n".join(f"[{o['agent']}]\n{o['content']}" for o in prose)
            level = state.get("profile", {}).get("knowledge_level", "beginner")
            shown_after = ("\n\nA worked calculation is shown separately right after your answer and gives the figure the "
                           "question asks for: don't do arithmetic, and never say that the figure, calculations, examples "
                           "or details are missing from the context. Explain the ideas behind it (for a tax figure: what "
                           "is taxed and when, and what changes the amount) and say the calculation below works it out."
                           if exact or any(o.get("verbatim_tail") for o in prose) else "")
            data = "" if sector_lines else MT.data_block(state.get("market_data") or {})        # exact figures the market tools fetched (volume, P/E...)
            figures = (f"\n\nData (exact figures from the market tools; use only those the question needs, and keep them "
                       f"exactly as given):\n{data}" if data else "")
            style = LENGTH_BY_LEVEL.get(level, LENGTH_BY_LEVEL["beginner"])
            earlier = state.get("topic_background") or ""             # earlier chats (topic memory): what was discussed, dated
            earlier = (f"\n\n{earlier}\nYou may mention that the user discussed this before, with its date. Take every current "
                       "figure from the Context or Data above; a figure in these notes may only be quoted with its date, as "
                       "what it was then." if earlier else "")
            # The question is repeated last: after a long context the model once answered the conversation's previous message
            # ("summary of my portfolio?") instead of the one asked ("how about nvda vs market trending today?").
            reply = ask_llm(SYNTH_SYSTEM, f"Knowledge level: {level} ({style})\nConversation so far (already answered):\n"
                                          f"{history or '(none)'}\n\nQuestion: {state['question']}\n\nContext:\n{context}{figures}"
                                          f"{shown_after}{earlier}\n\nAnswer this question, the user's latest message, and only "
                                          f"it: {state['question']}")
            if reply:
                text, mode = drop_unknown_headlines(reply, [x for o in prose for x in o.get("sources", [])]), "llm"
        text = link_sources(text, [s for o in prose for s in o.get("sources", [])])
        read_more = text if mode.startswith("verbatim (steps") else ""
        tails = [o["verbatim_tail"] for o in answered if o.get("verbatim_tail") and not read_more]   # figures after the words
        if tails:                       # the writer sometimes copies the figures it was given: they follow once, as worked out
            text = re.sub(r"\n{3,}", "\n\n", re.sub(r"\*\*In your estimate[^\n]*\*\*:?\n(?:\s*- [^\n]*(?:\n|$))+", "", text)).strip()
        text = "\n\n".join(t for t in [sector_lines, "" if read_more else text] + tails + [o["content"] for o in exact]
                           + [read_more] if t)
        readings = [o for o in answered if o.get("reading")]       # answered on a guess: say how it was read, never left to the LLM
        if readings:
            text += "\n\n" + "\n".join(READING_NOTE.format(o["reading"]) for o in readings)
            choices = choices or list(dict.fromkeys(c for o in readings for c in o.get("alternatives") or []))[:3]
        on_screen = state.get("screen") or {}
        if on_screen.get("switched"):                               # the tab, not the earlier answer, decided what "this" meant: say so
            text += "\n\n" + SCREEN_NOTE.format(on_screen["label"], on_screen["switched"])
        if asks:
            text += "\n\n" + "\n\n".join(o["content"] for o in asks)
    elif asks:
        text, mode = "\n\n".join(o["content"] for o in asks), "follow-up question"
    elif missing:
        text, mode = "\n\n".join(o["content"] for o in missing), "nothing found"
    else:
        text, mode = FALLBACK_MESSAGE, "fallback"
    shown = answered or asks or missing
    if state["entities"].get("advice_request") and answered:
        note = ("I can't tell you whether to buy or sell a specific investment; that depends on your whole situation. "
                "What I can do is show you the facts and explain the ideas behind the decision:")
        text = f"{note}\n\n{text}"
    if state.get("errors") and answered:
        text += "\n\n_(Some information wasn't available right now, so this answer may be incomplete.)_"
    seen, sources = set(), []
    for o in answered:
        for s in o.get("sources", []):
            if s["id"] not in seen:
                seen.add(s["id"])
                sources.append(s)
    data_info = next((o["data_info"] for o in answered if o.get("data_info")), None)
    return {"final_response": text, "choices": choices, "answered": any(not o.get("no_results") for o in answered),
            "agents": [R.AGENT_FOR_INTENT[o["agent"]] for o in shown] or ["Finnie"],
            "sources": sources, "data_info": data_info,
            "trace": [f"synthesizer: {mode} from {len(shown)} agent(s)" + (f", {len(choices)} choices offered" if choices else "")
                      + (" (partial: from research the verifier found incomplete)" if partial else "")]
                     + (["advice request detected: added a no-advice note"] if state["entities"].get("advice_request") and answered else [])}


FOLLOWUP_SYSTEM = (
    "You suggest what a personal-finance learner could ask next, after the assistant answered their question. Write up "
    "to three short QUESTIONS the user could send, in their own voice, each ending with a question mark, under 18 words:\n"
    "1. \"calculation\": a calculation question with concrete example numbers that illustrates the topic, e.g. "
    "\"How much would $5,000 grow to at 5% a year over 20 years?\". If they just did a calculation, vary one input. "
    "Use null if no calculation fits the topic.\n"
    "2. \"example\": a request for a real-life example, e.g. \"Can you give an example of compound interest in a savings "
    "account?\"\n"
    "3. \"related\": the natural next concept to learn, e.g. \"What is the difference between APR and APY?\"\n"
    "Never state facts or results, never address the user as \"you\", and don't repeat their question. "
    'Reply with ONLY JSON: {"calculation": "...", "example": "...", "related": "..."}.')


def followups_node(state: FinanceState, config: RunnableConfig):
    """After a real answer, offer up to three next steps as clickable choices: a worked calculation, an example and a
    related question. Skipped when the reply already asks the user something, found nothing, or there's no LLM."""
    if not state.get("answered") or state.get("choices") or current_llm() is None:
        return {"trace": []}
    reply = _json(ask_llm(FOLLOWUP_SYSTEM, f"User's question: {state['question']}\n\nAssistant's answer:\n{state['final_response'][:2500]}"))
    picked = []
    for key in ("calculation", "example", "related"):
        c = (reply or {}).get(key)
        if (isinstance(c, str) and c.strip().endswith("?") and not _ADDRESSES_USER.search(c)    # a question, in the user's words
                and c.strip().lower() != state["question"].strip().lower()):
            picked.append(c.strip())
    return {"choices": picked[:3], "trace": [f"follow-ups: {len(picked)} suggested" if picked else "follow-ups: none usable"]}


SCENARIO_SYSTEM = (
    "You read an answer from a personal-finance education assistant and note the worked example it goes through, if it "
    "has one (sample or the user's figures). Reply with ONLY JSON: {\"text\": \"<the example in one line, with its "
    "amounts, e.g. saving $60,000 over 5 years for a 20% down payment on a $300,000 house>\", \"goal_type\": "
    "\"house|education|retirement|other|null\", \"figures\": {\"target\": 60000, \"years\": 5, \"monthly\": 1000, "
    "\"home_price\": 300000, \"down_payment_pct\": 0.2}}. goal_type and target/years only for an amount saved up over "
    "years; leave out any figure the answer doesn't state, and use other short snake_case names for other amounts. "
    "Reply {} when the answer works through no example.")
_EXAMPLE_IN_ANSWER = re.compile(r"(for example|for instance|example|let'?s say|say you|suppose|imagine)", re.I)


def _answer_scenario(state: FinanceState, text: str) -> dict | None:
    """The worked example a written answer went through ("for example, a $300,000 house with 20% down..."), when no agent
    reported one: noted for the next turn ("how would the tax change in this case?"). Every figure must be in the answer."""
    if (state.get("turn_context") or {}).get("scenario") or current_llm() is None or not state.get("answered"):
        return None
    if not (CP.wants_example(state.get("question") or "") or _EXAMPLE_IN_ANSWER.search(text)) or len(re.findall(r"\$\s?\d", text)) < 2:
        return None
    data = _json(ask_llm(SCENARIO_SYSTEM, f"Question: {state.get('question') or ''}\n\nANSWER:\n{text[:3000]}")) or {}
    said = {round(float(n.replace(",", "")), 2) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
    figures = {}
    for k, v in (data.get("figures") or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and re.fullmatch(r"[a-z_]{1,30}", str(k)):
            shown = {round(float(v), 2), round(float(v) * 100, 2)} if (k.endswith("_pct") or k in ("annual_return", "rate")) else {round(float(v), 2)}
            if shown & said:                              # a figure the answer states, never one the model worked out
                figures[k] = v
    line = " ".join(str(data.get("text") or "").split())[:240]
    if not line or not figures:
        return None
    goal = data.get("goal_type") if data.get("goal_type") in ("house", "education", "retirement", "other") else None
    kind = "savings_goal" if goal and figures.get("target") and figures.get("years") else "example"
    return {"kind": kind, "goal_type": goal, "text": line, "figures": figures, "from": "answer"}


def compliance_node(state: FinanceState, config: RunnableConfig):
    text, removed = finalize(state["final_response"])
    scenario = _answer_scenario(state, text)
    return {"final_response": text, "context": CTX.build({**state, "answer_scenario": scenario}),   # saved for the next turn
            "trace": [f"compliance: {'removed %d advice-like sentence(s)' % removed if removed else 'no advice patterns found'}; disclaimer added"]
                     + ([f"context: noted the answer's worked example ({scenario['text']})"] if scenario else [])}
