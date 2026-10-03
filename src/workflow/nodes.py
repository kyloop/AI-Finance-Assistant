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

from src.core.calculators import analyze_portfolio, project_goal
from src.core.config import get_config
from src.core.llm import ask_llm, current_llm
from src.core.market_service import SymbolNotFound
from src.core.portfolio_data import portfolio_history, portfolio_instruments
from src.kb.wiki import WikiUnavailable

from . import calc as CALC
from . import context as CTX
from . import history as H
from . import market_tools as MT
from . import news as NEWS
from . import router as R
from . import symbols as SYM
from .safety import finalize
from .state import AgentOutput, FinanceState
from .tools import industry_peers, kb_search, news_index_now, news_latest, news_search, wiki_search, wiki_topic

log = logging.getLogger(__name__)

WORDS_BY_LEVEL = {"beginner": 0.6, "intermediate": 1.0, "advanced": 1.5}
SYMBOL_OK = re.compile(r"^[A-Z0-9.\-=^]{1,15}$")
ORDER = ["portfolio", "market", "news", "calc", "goal", "tax", "qa", "example", "clarify"]
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
    "the message, add facts or drop a request. If a word may be a ticker or name you don't know, leave it unchanged.\n"
    "You may be given the CONTEXT of the conversation so far (the previous question, its companies, period and figures). If the "
    "message continues it (it points back with \"it\", \"them\", \"which\", \"compare to\", \"what about X\", or leaves out a "
    "company or period it relies on), rewrite it as a complete question that names them, using ticker symbols from the CONTEXT: "
    "\"compare to starbucks\" after TSLA over the last month -> \"Compare TSLA and Starbucks over the last month.\"; "
    "\"which did better?\" -> \"Which did better over the last month, TSLA or SBUX?\". Set follow_up to true then. If the message "
    "starts a new topic, only correct it and set follow_up to false. Take companies, periods and numbers only from the message "
    "or the CONTEXT.\n"
    'Reply with ONLY JSON: {"question": "<the corrected message>", "follow_up": true}')
_TICKER_TOKEN = re.compile(r"\b[A-Z]{2,5}\b")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
PROOFREAD_MAX_CHARS = 500                  # longer messages go to the router as typed
FOLLOW_UP_EXTRA_CHARS = 200                # room a completed follow-up may add (company names, the period)


def _proofread_ok(original: str, fixed: str, ctx: dict | None = None) -> bool:
    """A correction, not a different message: no number or capitalised ticker lost, not much longer, and similar text; or,
    for a follow-up completed from the context, anything added (tickers, numbers) comes from that context."""
    if not fixed:
        return False
    if any(n not in fixed for n in _NUMBER.findall(original)):
        return False
    if any(t not in fixed for t in _TICKER_TOKEN.findall(original) if not original.isupper()):
        return False
    if ctx is not None:
        known = f"{original.upper()} {CTX.describe(ctx).upper()}"
        return (len(fixed) <= len(original) + FOLLOW_UP_EXTRA_CHARS
                and all(t in known for t in _TICKER_TOKEN.findall(fixed))
                and all(n in known for n in _NUMBER.findall(fixed)))
    if len(fixed) > 2 * len(original) + 40:
        return False
    return difflib.SequenceMatcher(None, original.lower(), fixed.lower()).ratio() >= 0.5


def _proofread_reply(q: str, ctx: dict | None) -> tuple[str, bool] | None:
    """(corrected question, follow-up?) from the LLM; None if it gave nothing usable. A plain-text reply counts as a correction."""
    prompt = (f"CONTEXT:\n{CTX.describe(ctx)}\n\n" if ctx else "") + f"Message: {q}"
    reply = ask_llm(PROOFREAD_SYSTEM, prompt)
    if not reply:
        return None
    data = _json(reply)
    if data is None:
        fixed = reply.strip().strip('"“”').strip()
        return (fixed, False) if fixed else None
    fixed = str(data.get("question") or "").strip()
    return (fixed, bool(data.get("follow_up")) and bool(ctx)) if fixed else None


def proofread_node(state: FinanceState, config: RunnableConfig):
    """Fix spelling, grammar and abbreviations before routing ("tsla last 10 yrs" -> "TSLA over the last 10 years"), and turn
    a follow-up into a complete question from the previous answer's context ("compare to starbucks" -> "Compare TSLA and
    Starbucks over the last month"). The rewrite replaces `question` for every later node; `original_question` keeps what
    the user typed. `follow_up` tells the router and agents to carry the context's companies, period and figures over.
    Without an LLM the message is kept and a follow-up is recognised by its wording (context.looks_like_follow_up)."""
    q, ctx = state["question"], state.get("context_in") or None
    base = {"original_question": q, "follow_up": bool(ctx) and CTX.looks_like_follow_up(q)}
    note = " (follow-up: carrying the earlier context)" if base["follow_up"] else ""
    if not get_config()["workflow"].get("proofread", True) or current_llm() is None:
        return {**base, "trace": [("proofread: skipped (no LLM)" if current_llm() is None else "proofread: off") + note]}
    if R.is_gibberish(q) or len(q) > PROOFREAD_MAX_CHARS:
        return {**base, "trace": ["proofread: left as typed" + note]}
    got = _proofread_reply(q, ctx)
    if got is None:
        return {**base, "trace": ["proofread: no reply, left as typed" + note]}
    fixed, follow_up = got
    if not _proofread_ok(q, fixed, ctx if follow_up else None):
        log.info("proofread rewrite rejected: %r -> %r", q, fixed)
        return {**base, "trace": ["proofread: rewrite rejected, left as typed" + note]}
    tag = " (follow-up of the previous question)" if follow_up else ""
    if fixed == q:
        return {**base, "follow_up": follow_up, "trace": [f"proofread: no changes{tag}"]}
    return {"question": fixed, "original_question": q, "follow_up": follow_up, "trace": [f"proofread: “{q}” → “{fixed}”{tag}"]}


# ---------------------------------------------------------------- router
ROUTER_SYSTEM = """You are the router for a personal-finance EDUCATION assistant. Decide which specialist agents must work on the user's message. Choose ALL agents whose job is needed to fully answer it.

AGENTS AND THEIR RESPONSIBILITIES
- qa: Explains financial concepts, definitions, how things work, WHY something happens, drivers/risks/pros-cons, and "what should I consider" questions. Knowledge-base driven. No live data, no user holdings.
- portfolio: Analyzes the USER'S OWN holdings (allocation, diversification, concentration, risk, performance of what they own). Only when the message refers to "my portfolio / my stocks / my holdings" or supplied holdings.
- market: Live and recent market DATA and trends: prices, quotes, indices, valuation metrics for a named security (P/E, dividend yield, market cap), sector or asset-class performance, "how is X doing / performing", comparisons between tickers, rates, housing, commodities, crypto. Anything about the current STATE or PERFORMANCE of a market, sector, asset class or security.
- news: Recent headlines and developments ("latest", "recent", "what happened", "what's being reported", "any news") about a company, industry, sector, topic or the whole market. Summarizes and gives context.
- goal: Builds a savings plan: monthly amount needed to reach a target amount by a date (risk appetite may apply). Only when they want a plan or "how much should I save".
- tax: Tax rules and account types (401k, IRA, Roth, HSA, 529), contribution limits, capital gains, deductions, tax treatment of investments.
- calc: Computes a specific number: future value, loan/mortgage payment, doubling time, present value, real return, APY, bond yield. Use when the user wants a figure calculated, not explained.

ROUTING RULES
1. A message can need several agents. Return every intent whose responsibility is required; usually 1-3, never more than 4.
2. Performance or condition of a market, sector or asset class ("how is the housing market performing", "how are tech stocks doing", "state of the bond market") -> market + qa. market supplies the data; qa supplies the explanation of what drives it and what it means for a learner. Add news if they ask about recent events/causes or use "lately/this week/why now".
3. "Why did X move / why is X up/down" -> market + news (+ qa if they also ask what the concept means).
4. Split compound messages. If a message has several parts (joined by "and", "also", a comma, or a second question), classify EACH part separately and return the union of intents. A definition plus a live figure for a named company or index ("What is a P/E ratio and what is TSLA's?") -> qa + market. Never let one part hide the other. But "and" alone does not mean two agents: add an agent only if the second part needs a different agent's job.
5. A pure price/quote request ("price of NVDA") -> market only. A pure definition ("what is an ETF") -> qa only. Only use a single intent when the WHOLE message is that one thing. Do not add agents that contribute nothing.
6. "Should I buy/invest in X" or "is X a good investment" -> qa + market (+ portfolio if they mention their holdings). Education only, never personal advice.
7. Questions about what to consider or how something works (buying a house, mortgages, retirement accounts) -> qa. Add goal only if they ask for a savings plan, calc only if they ask for a number, tax only if tax treatment is asked.
8. "How much will I have / what is my payment" -> calc. "How much must I save each month to reach $X by <date>" -> goal. If both a number and an explanation are requested, calc + qa.
9. Tax-related investing questions ("how are dividends taxed", "Roth vs traditional") -> tax (+ qa if broad concept explanation is also requested).
10. Follow-ups: pronouns or references to the earlier subject ("them", "it", "the same sector", "grab the recent news") inherit the intents the conversation is about. A short "what about X?" repeats ALL intents of the previous question for the new subject (price and news for NVDA, then "what about NU?" -> market + news).
11. Anything unclear or very general about money/investing -> qa, with lower confidence.

EXAMPLES
"What is the performance of the housing market?" -> ["market","qa"]
"How is the housing market doing and what's in the news?" -> ["market","qa","news"]
"Why are tech stocks down this week?" -> ["market","news"]
"What is a P/E ratio?" -> ["qa"]
"What is a P/E ratio? And what is TSLA's P/E ratio?" -> ["qa","market"]
"Explain dividend yield and show me KO's" -> ["qa","market"]
"What's a Roth IRA and what's the contribution limit this year?" -> ["tax"]
"Price of AAPL?" -> ["market"]
"Is my portfolio too concentrated in tech?" -> ["portfolio","qa"]
"What's the monthly payment on a $400k mortgage at 6.5% for 30 years?" -> ["calc"]
"I want $50k for a down payment in 4 years, how much per month?" -> ["goal"]
"Roth IRA or 401k, and how are the gains taxed?" -> ["tax","qa"]
"Should I invest in real estate right now?" -> ["qa","market"]

Reply with ONLY JSON: {"intents": ["qa"], "confidence": 0.0-1.0}. Intents must come from: qa, portfolio, market, news, goal, tax, calc. Confidence reflects how sure you are that the intent SET is complete and correct."""


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
    if "market" in intents or not SYM.ticker_mentions(text):
        return intents
    if set(intents) <= {"qa", "news"} and len(text.split()) <= SHORT_QUESTION_WORDS:
        return [*(i for i in intents if i != "qa"), "market"]
    return [*intents, "market"]


SHORT_QUESTION_WORDS = 12


def _routed(res: dict, state: FinanceState) -> dict:
    """Add the companies a market or news question is about. Resolved once here, with the conversation, so "nvdia" is corrected to
    NVIDIA and "them" means the company discussed earlier; the market and news agents both read `entities["companies"]`."""
    e = res["entities"]
    if {"market", "news"} & set(res["intent"]) and not (e["tickers"] or e["indices"]):
        e["companies"] = SYM.resolve(state["question"], history=state.get("history"))
        if e["companies"]:
            res["trace"] = [*res["trace"], "resolved " + ", ".join(_resolved_label(c) for c in e["companies"])]
    return _with_carried_companies(res, state)


def _with_carried_companies(res: dict, state: FinanceState) -> dict:
    """A follow-up uses the companies the previous answer was about: all of them when it names none ("which did better?"),
    and alongside the new one when it compares or adds ("compare to Starbucks", "news on MSFT too?")."""
    prev, e = CTX.carried(state), res["entities"]
    if not prev.get("companies") or not {"market", "news"} & set(res["intent"]):
        return res
    new = e.get("companies") or []
    have = {*e["tickers"], *e["indices"], *(c["symbol"] for c in new)}
    if have and not CTX.ADDS_TO.search(state["question"]):
        return res
    add = [{**c, "mention": "(earlier)"} for c in prev["companies"] if c["symbol"] not in have]
    add = add[:max(0, CTX.MAX_COMPANIES - len(have))]
    if add:
        e["companies"] = [*add, *new]
        res["trace"] = [*res["trace"], "from the previous answer: " + ", ".join(c["symbol"] for c in add)]
    return res


def router_node(state: FinanceState, config: RunnableConfig):
    res = _route(state)
    res["tried_agents"] = [n.removesuffix("_agent") for n in route_after_router(res)]       # replan never re-runs these
    return res


def _route(state: FinanceState) -> dict:
    text = state["question"]
    entities = R.extract_entities(text, state.get("history"))
    if R.is_gibberish(text):
        return {"intent": ["clarify"], "entities": entities, "router_mode": "keywords", "trace": ["router: no words found → clarify"]}
    if current_llm() is not None:
        recent = H.transcript(state.get("history"))
        reply = ask_llm(ROUTER_SYSTEM, f"Recent conversation:\n{recent or '(none)'}\n\nMessage: {text}")
        parsed = R.parse_llm_intents(reply) if reply else None
        if parsed:
            intents, confidence = parsed
            if confidence < 0.3:
                return {"intent": ["clarify"], "entities": entities, "router_mode": "llm", "trace": [f"router (LLM): low confidence {confidence:.1f} → clarify"]}
            intents = _with_listed_tickers(intents, text)
            return _routed({"intent": intents, "entities": entities, "router_mode": "llm", "trace": [f"router (LLM): {', '.join(intents)}"]}, state)
        log.warning("router LLM reply unusable; falling back to keywords")
    intents = _with_listed_tickers(R.classify(text), text)
    if intents == ["qa"] and CTX.carried(state).get("companies"):                 # "which did better?" after a market answer
        intents = ["market"]
    return _routed({"intent": intents, "entities": entities, "router_mode": "keywords", "trace": [f"router (keywords): {', '.join(intents)}"]}, state)


def route_after_router(state: FinanceState) -> list[str]:
    intents = state.get("intent") or ["qa"]
    if intents == ["clarify"]:
        return ["clarify"]
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


def _kb_answer(agent: str, state: FinanceState, query: str, prefix: str = "") -> dict:
    """Answer from the knowledge base (Qdrant). not_found (→ research on Wikipedia) when the index is missing or failing,
    or the best match is below rag.min_score (the topic probably isn't indexed yet)."""
    cfg = get_config()["rag"]
    try:
        hits = kb_search(state["question"])
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
        sources.append({"id": f"kb:{h['doc_id']}#{h['section']}", "title": f"{label} (Wikipedia)", "url": h["source_url"] + anchor})
    return _out(agent, prefix + body, sources=sources, query=query, prefix=prefix, origin="kb",
                confidence="high" if top["score"] >= cfg["min_score"] + 0.08 else "medium",
                trace=f"kb_search → {len(hits)} chunks, best {top['doc_title']} › {top['section']} ({top['score']:.2f})")


@safe("qa")
def qa_node(state: FinanceState, config: RunnableConfig):
    return _kb_answer("qa", state, state["entities"]["wiki_query"])


@safe("tax")
def tax_node(state: FinanceState, config: RunnableConfig):
    q = state["entities"]["wiki_query"]
    q = q if "tax" in q.lower() or "ira" in q.lower() or "401" in q else f"{q} tax"
    return _kb_answer("tax", state, q, TAX_PREFIX)


_PRICE_ASK = re.compile(r"\b(price|quote|trading at|share price|worth today|how much is)\b", re.I)
MARKET_ASK = ("I couldn't tell which company or ticker you mean. Tell me the company name or its ticker symbol "
              "(for example “NVIDIA” or “NVDA”) and I'll look up its price.")


def _view_symbols(state: FinanceState) -> list[str]:
    """Symbols the user means without naming them: "my watchlist", or "this stock" while one is selected on the Live tab."""
    view, q = state.get("view") or {}, state["question"]
    valid = lambda syms: [s for s in dict.fromkeys(str(x).strip().upper() for x in syms if x) if SYMBOL_OK.match(s)]  # noqa: E731
    if re.search(r"\b(watchlist|watching|tracking|following)\b", q, re.I):
        return valid(view.get("watchlist") or [])
    if view.get("selected") and re.search(r"\b(this|it|that|selected|current)\b", q, re.I):
        return valid([view["selected"]])
    return []


_PERFORMANCE = re.compile(r"\b(perform\w*|better|worse|best|worst|compare\w*|versus|vs|returns?|gain\w*|grow\w*|done|doing|did)\b", re.I)


def _period_for(state: FinanceState) -> tuple[date, str] | None:
    """The period this question asks about; for a follow-up ("which did better?", "what about AAPL?"), the one the previous
    answer used (its saved context). A plain price question gets none. Conversations saved before contexts existed fall
    back to looking for a period in the recent messages."""
    q = state["question"]
    if p := MT.asked_period(q):
        return p
    if _PRICE_ASK.search(q):
        return None
    if state.get("context_in") is not None:
        return CTX.period_of(CTX.carried(state))
    if not _PERFORMANCE.search(q):
        return None
    return next((p for m in reversed(H.recent(state.get("history"))) if (p := MT.asked_period(m["content"]))), None)


MARKET_TOOL_SYSTEM = (
    "You fetch market data for a personal-finance EDUCATION assistant. Call the tools that supply the figures the question "
    "needs, for the companies or funds it is about (use ticker symbols). Request everything in this one reply; you may call "
    "several tools at once. get_quote gives today's price, change, volume and day range; get_performance a period's return, "
    "high/low and average volume; get_company_profile a company's sector, valuation (P/E, market cap, beta), earnings and "
    "dividends; get_fund_profile an ETF's or mutual fund's expense ratio, yield and holdings. Don't answer the question yourself.")


def _llm_fetch(llm, state: FinanceState, db, symbols: list[str], period: tuple[date, str] | None) -> tuple[dict, list[str]]:
    """Let the model choose tools and arguments (LangChain tool calling); Python runs them through market_tools, which read the
    cache. At most `workflow.market_tool_calls` calls in `workflow.market_tool_rounds` replies, so one question can't fan out."""
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    cfg = get_config()["workflow"]
    max_calls, rounds = int(cfg.get("market_tool_calls", 4)), int(cfg.get("market_tool_rounds", 1))
    names = {c["symbol"]: c.get("name") for c in state["entities"].get("companies") or []}
    about = [f"Companies: {', '.join(f'{names[s]} ({s})' if names.get(s) else s for s in symbols)}"]
    if period:
        about.append(f"Period the conversation is about: {period[1]}")
    if known := CTX.describe(state.get("context_in")):
        about.append(f"Earlier in the conversation:\n{known}")
    messages = [SystemMessage(MARKET_TOOL_SYSTEM), HumanMessage("\n".join(about) + f"\n\nQuestion: {state['question']}")]
    bound, data, notes, calls = llm.bind_tools(MT.TOOL_SPECS), {}, [], 0
    for _ in range(rounds):
        reply = bound.invoke(messages)
        tool_calls = getattr(reply, "tool_calls", None) or []
        if not tool_calls:
            break
        messages.append(reply)
        for call in tool_calls:
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


def _fill_in(db, data: dict, symbols: list[str], period: tuple[date, str] | None) -> tuple[dict, list[str]]:
    """What every answer has, whatever the model chose (and all of it without an LLM): a quote for each company, and the
    asked or carried period's performance."""
    notes = []
    need = [s for s in symbols if "quote" not in data.get(s, {})]      # cached, so cheap even when the model chose other tools
    if need:
        got = MT.get_quote(db, need)
        notes.append(f"get_quote({', '.join(need)}) → {_freshness(got)}")
        data = MT.merge_market(data, got)
    if period:
        need = [s for s in symbols if "quote" in data.get(s, {}) and "period" not in data[s]]
        if need:
            got = MT.performance(db, need, *period)
            notes.append(f"get_performance({', '.join(need)}, {period[1]}) → {_freshness(got)}")
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
            f.update({k: pr[k] for k in ("trailing_pe", "market_cap", "dividend_yield") if pr.get(k) is not None})
        if fd := d.get("fund"):
            f.update({k: fd[k] for k in ("expense_ratio", "yield") if fd.get(k) is not None})
        if f:
            facts[sym] = {k: v for k, v in f.items() if v is not None}
    return facts


@safe("market")
def market_node(state: FinanceState, config: RunnableConfig):
    """Market data through tools (market_tools.py). With an LLM the model picks the tools and arguments for the question
    (quote, performance over a period, company or fund profile); then, and without an LLM, every company gets a quote and the
    asked or carried period its performance. All figures go to `market_data` for the synthesizer and the saved context."""
    e = state["entities"]
    symbols = e["tickers"] + e["indices"]
    view_syms = _view_symbols(state) if not symbols else []
    symbols = symbols or view_syms
    named = e.get("companies") or []        # "price of Palantir": looked up on Yahoo by the router; or carried from the previous answer
    symbols = list(dict.fromkeys([*symbols, *(r["symbol"] for r in named)]))
    if not symbols and _PRICE_ASK.search(state["question"]):                      # a quote for something we can't identify: ask, don't research
        return _out("market", MARKET_ASK, status="need_info", confidence="low", trace="market: price asked for, but no company or ticker recognised → ask")
    if not symbols:                        # a market concept rather than a quote: look it up
        return _not_found("market", e["wiki_query"], "market: no ticker or index → concept lookup")
    db = _db(config)
    if db is None:
        raise RuntimeError("no database session for market lookup")
    period = _period_for(state)
    data, notes, how = {}, [], "keywords"
    llm = current_llm()
    if llm is not None and hasattr(llm, "bind_tools"):
        try:
            data, notes = _llm_fetch(llm, state, db, symbols, period)
            how = "LLM tools"
        except Exception as ex:  # noqa: BLE001 — a model that can't call tools still gets the standard figures
            log.warning("market tool calling failed: %s", ex)
            notes.append(f"tool calling failed ({type(ex).__name__})")
    data, more = _fill_in(db, data, symbols, period)
    notes += more
    lines = MT.describe_lines(data)
    quotes = [d["quote"] for d in data.values() if "quote" in d]
    if quotes:
        lines.append("\n_“% vs previous close” compares today's price with yesterday's closing price. A single day's move says little about the long term._")
    info = {"provider": quotes[0]["source"], "fetched_at": quotes[0]["as_of"], "freshness": quotes[0]["freshness"]} if quotes else None
    res = _out("market", "\n".join(lines), data_info=info, confidence="high" if quotes else "low",
               trace=f"market ({how}): " + "; ".join(notes))
    res["market_data"] = data
    used = next((d["period"] for d in data.values() if "period" in d), None)
    res["turn_context"] = {"companies": [{"symbol": s, "name": MT._name(d, s)} for s, d in data.items() if "error" not in d or len(d) > 1][:CTX.MAX_COMPANIES],
                           "facts": _key_facts(data),
                           **({"period": {"start": used["start"], "label": used["label"]}} if used else
                              {"period": {"start": period[0].isoformat(), "label": period[1]}} if period else {})}
    return res


NEWS_LIVE_MAX = 6


def _news_none(days: int, tried: list[str], trace: str, *, unavailable: bool = False) -> dict:
    """Nothing usable after the tools ran: say what was tried (never fall through to Wikipedia, which has no news) and don't offer follow-ups."""
    if unavailable:
        msg = "I can't search my news index right now, so I can't check recent stories. Please try again shortly."
    else:
        did = "; ".join(tried)
        msg = (f"I looked, and found no news matching that from the last {days} days ({did}). "
               "If you name a company or ticker, for example “news on NVDA”, I can pull its latest headlines.")
    return _out("news", msg, confidence="low", verbatim=True, no_results=True, trace=trace)


def _live_envs(db, tickers: list[str]) -> list[tuple[str | None, dict]]:
    """Live (5-minute cached) headline feeds for the named tickers, or the market feed when there are none."""
    envs = []
    for sym in tickers[:3] or [None]:
        try:
            envs.append((sym, news_latest(db, sym)))
        except SymbolNotFound:
            continue
    return envs


def _fetched_note(envs: list[tuple[str | None, dict]], label: str) -> str:
    n = sum(len(env["data"]["items"]) for _, env in envs)
    return f"fetched {n} {label} headlines from Yahoo" if n else f"Yahoo returned no headlines for {label}"


def _live_news(envs: list[tuple[str | None, dict]], label: str, intro: str = "") -> dict | None:
    """The newest stories across the feeds, as an agent output; None if the feeds are empty."""
    per = NEWS_LIVE_MAX if len(envs) <= 1 else max(2, NEWS_LIVE_MAX // len(envs))
    items = {i["id"]: i for _, env in envs for i in env["data"]["items"][:per]}
    if not items:
        return None
    stories = sorted(items.values(), key=lambda i: i.get("published") or "", reverse=True)[:NEWS_LIVE_MAX]
    info = {k: envs[0][1][k] for k in ("provider", "fetched_at", "freshness")}
    body = f"{intro}Latest headlines for {label} (Yahoo Finance, {info['freshness']}):\n" + "\n".join(NEWS.format_story(s) for s in stories)
    return _out("news", body, sources=[NEWS.story_source(s) for s in stories], data_info=info,
                trace=f"news_latest({label}) → {len(stories)} stories ({info['freshness']})")


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
    text, tried = state["question"], []                      # the proofread question: corrected, and completed for a follow-up
    tickers = [t for t in NEWS.tickers_in(text, state["entities"]) if SYMBOL_OK.match(t)]
    resolved = state["entities"].get("companies") or []      # looked up by the router, or carried from the previous answer
    if resolved:
        tickers = list(dict.fromkeys([*tickers, *(r["symbol"] for r in resolved)]))
        tried.append("matched " + ", ".join(f"{r['name']} ({r['symbol']})" for r in resolved))
    tickers = tickers or _view_symbols(state)
    res = _news_answer(state, config, text, tickers, resolved, tried)
    if tickers:                                               # so "what about their earnings?" knows who "their" is
        names = {r["symbol"]: r.get("name") or r["symbol"] for r in resolved}
        res["turn_context"] = {"companies": [{"symbol": t, "name": names.get(t, t)} for t in tickers[:CTX.MAX_COMPANIES]]}
    return res


def _news_answer(state: FinanceState, config: RunnableConfig, text: str, tickers: list[str], resolved: list[dict], tried: list[str]) -> dict:
    cfg, steps = get_config()["news_index"], []
    label = ", ".join(tickers[:3]) if tickers else "the market"
    if tickers and NEWS.asks_about_sector(text):
        return _sector_news(tickers[0], config, steps)
    topic = NEWS.topic_words(text, tickers, [x for r in resolved for x in (r["mention"], r["name"])])
    days = NEWS.time_window(text, cfg["retention_days"]) or cfg["default_days"]
    db = _db(config)
    if db is None:
        raise RuntimeError("no database session for news lookup")
    envs = None
    if not topic:
        with DBSession(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as own:     # agents run in parallel threads; a Session isn't shareable
            envs = _live_envs(own, tickers)
        live = _live_news(envs, label)
        if live:
            live["trace"] = steps + live["trace"]
            return live
        tried.append(_fetched_note(envs, label))
    try:
        hits = _relevant_news(text, tickers, days)
        tried.append("searched the indexed stories" + (f" for {label}" if tickers else ""))
        if not hits and tickers:                                  # not indexed yet: fetch the headlines now, index them, search again
            if envs is None:
                with DBSession(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as own:
                    envs = _live_envs(own, tickers)
                tried.append(_fetched_note(envs, label))
            added = sum(news_index_now(sym, env["data"]["items"]) for sym, env in envs if sym and env["data"]["items"])
            steps.append(f"news_latest({label}) → {sum(len(e['data']['items']) for _, e in envs)} stories, {added} newly indexed")
            hits = _relevant_news(text, tickers, days)
    except Exception as e:  # noqa: BLE001 — a broken index must not break chat
        log.warning("news search failed: %s", e)
        return _news_none(days, tried, f"news_search → failed ({type(e).__name__})", unavailable=True)
    if not hits:
        fallback = _live_news(envs, label, f"I found no stories about that specifically in the last {days} days. ") if envs and tickers else None
        if fallback:                                              # the feed has stories, just none on this topic: show them, labelled
            fallback["confidence"] = "medium"
            fallback["trace"] = steps + [f"news_search({days}d, {label}) → no relevant stories; showing the latest headlines"]
            return fallback
        return _news_none(days, tried, "; ".join(steps + [f"news_search({days}d, {label}) → no relevant stories"]))
    fetched = datetime.fromtimestamp(max(h.get("ingested_at") or 0 for h in hits), timezone.utc).isoformat()
    body = f"Stories from the last {days} days that match the question (Yahoo Finance headlines and short summaries):\n" + "\n".join(NEWS.format_story(h) for h in hits)
    return _out("news", body, sources=[NEWS.story_source(h) for h in hits],
                data_info={"provider": "yfinance", "fetched_at": fetched, "freshness": "cached"},
                confidence="high" if hits[0]["score"] >= cfg["min_score"] + 0.1 else "medium",
                trace="; ".join(steps + [f"news_search({days}d, {label}) → {len(hits)} stories, best {hits[0]['score']:.2f}"]))


def _signed_usd(n: float) -> str:
    return f"{'+' if n >= 0 else '-'}${abs(n):,.0f}"


@safe("portfolio")
def portfolio_node(state: FinanceState, config: RunnableConfig):
    holdings = state.get("holdings") or []
    if not holdings:
        return _out("portfolio", "I don't see a portfolio yet. Add your holdings (or load a sample) on the **Portfolio** tab and ask me again.",
                    confidence="medium", trace="portfolio: no holdings")
    risk = state.get("profile", {}).get("risk_tolerance", "moderate")
    db = _db(config)                 # shared with the market agent's thread: every use goes through the market service, which serialises them
    instruments, info = portfolio_instruments(db, [h["ticker"] for h in holdings])
    a = analyze_portfolio(holdings, instruments, risk)
    perf = portfolio_history(db, a["holdings"]) if db is not None and not a["empty"] else None
    if a["empty"]:
        return _out("portfolio", "None of your holdings could be priced, so I can't analyse them yet.", confidence="low", trace="portfolio: nothing priced")
    lines = [f"Your portfolio is worth about **${a['total_value']:,.0f}** across {len(a['holdings'])} holdings."]
    if a["total_gain_loss"] is not None:
        lines.append(f"- Gain/loss against what you paid: **{_signed_usd(a['total_gain_loss'])}** ({a['total_return_pct']:+.1%}), for the holdings with a cost basis")
    if a["day_change"] is not None:
        lines.append(f"- Today: {_signed_usd(a['day_change'])} ({a['day_change_pct']:+.2%})")
    lines += [f"- Diversification score: **{a['diversification_score']}/100** (about {a['effective_holdings']} effective holdings)",
              f"- Risk level: **{a['risk_level']}/5** ({a['risk_label']}) against your stated {risk} tolerance",
              f"- Fees: about ${a['annual_fee']:,.2f} a year ({a['weighted_expense_ratio'] * 100:.2f}% weighted)"]
    if perf and perf["period_return"] is not None:
        versus = f", against {perf['benchmark_return']:+.1%} for the {perf['benchmark']['name']}" if perf["benchmark_return"] is not None else ""
        lines += [f"\nSince {perf['start']}, counting each holding from its purchase date:",
                  f"- Return: **{perf['period_return']:+.1%}**{versus}",
                  f"- Volatility: {perf['volatility']:.1%} a year; largest fall from a peak: {perf['max_drawdown']:.1%}",
                  "_These figures assume each holding was bought in full on its purchase date"
                  + (f" ({perf['default_start']} where none is set)._" if perf["assumed"] else "._")]
    if a["warnings"]:
        lines.append("\nThings worth a closer look:")
        lines += [f"- {w}" for w in a["warnings"][:4]]
        if any("of your portfolio" in w for w in a["warnings"]):
            lines.append("\n_Concentration risk means a large share of your money depends on one holding or sector, so a bad stretch there "
                         "hurts more. Diversifying spreads that risk._")
    return _out("portfolio", "\n".join(lines), data_info=info,
                trace=f"portfolio_analysis({len(holdings)} holdings) → score {a['diversification_score']} ({info['freshness']})")


def _saved_goal_answer(state: FinanceState, g: dict) -> dict:
    risk = g.get("risk_tolerance") or state.get("profile", {}).get("risk_tolerance", "moderate")
    r = project_goal(g["target_amount"], g["horizon_years"], g.get("current_savings", 0), g.get("monthly_contribution", 0),
                     get_config()["risk_profiles"][risk])
    lines = [f"Based on your {g['goal_type']} plan on the **Goals** tab (${r['target']:,.0f} in {g['horizon_years']} years, "
             f"${g.get('current_savings', 0):,.0f} saved so far, ${g.get('monthly_contribution', 0):,.0f} a month, {risk} profile, "
             f"assuming a steady {r['annual_return_assumption'] * 100:.0f}% yearly return):",
             f"- Projected value: about **${r['projected_value']:,.0f}**"
             + (" — on track." if r["on_track"] else f", ${r['shortfall']:,.0f} short of the target."),
             f"- Reaching the target would take about **${r['required_monthly']:,.0f} a month**.",
             "\n_This is a simple illustration. Real returns vary year to year and are never guaranteed._"]
    return _out("goal", "\n".join(lines), trace=f"saved goal ({g['goal_type']}, ${r['target']:,.0f}, {g['horizon_years']}y) → ${r['required_monthly']:,.0f}/mo")


@safe("goal")
def goal_node(state: FinanceState, config: RunnableConfig):
    e = state["entities"]
    saved = state.get("saved_goal")
    if saved and not (e["target_amount"] or e["years"]):          # "am I on track?" -> use the plan saved on the Goals tab
        return _saved_goal_answer(state, saved)
    if not (e["target_amount"] and e["years"]):
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
    return _out("goal", "\n".join(lines), trace=f"project_goal(${e['target_amount']:,.0f}, {e['years']}y, {risk}) → ${r['required_monthly']:,.0f}/mo")


@safe("calc")
def calc_node(state: FinanceState, config: RunnableConfig):
    """Pick a calculation and its inputs (LLM, or a keyword fallback), compute it in Python, show the working."""
    name, args, how = None, {}, "keywords"
    if current_llm() is not None:
        recent = H.transcript(state.get("history"))
        known = CTX.describe(state.get("context_in"))          # the previous answer's figures, e.g. "SBUX: price $94.71"
        reply = _json(ask_llm(CALC.CALC_SYSTEM, f"Recent conversation:\n{recent or '(none)'}\n\n"
                                                + (f"Figures from the previous answer:\n{known}\n\n" if known else "")
                                                + f"Message: {state['question']}"))
        if reply is not None:
            name, args, how = reply.get("function"), reply.get("args") or {}, "LLM"
    if name is None and how == "keywords":
        name, args = CALC.keyword_request(state["question"])
    if name not in CALC.CATALOG:
        return _out("calc", CALC.ASK, status="need_info", choices=CALC.CHOICES, confidence="medium",
                    trace=f"calc ({how}): numbers missing → ask")
    try:
        text = CALC.run(name, args)
    except (TypeError, ValueError) as e:
        return _out("calc", f"{CALC.ASK}\n\n_({e})_", status="need_info", choices=CALC.CHOICES, confidence="medium",
                    trace=f"calc ({how}): {name} rejected inputs ({e}) → ask")
    shown = ", ".join(f"{k}={v:g}" if isinstance(v, (int, float)) else f"{k}={v}" for k, v in args.items() if v not in (None, "", 0))
    return _out("calc", text, verbatim=True, trace=f"calc ({how}): {name}({shown})")


def clarify_node(state: FinanceState, config: RunnableConfig):
    return _out("clarify", CLARIFY_MESSAGE, status="need_info", choices=STARTER_CHOICES, confidence="low",
                trace="clarify: asked the user to rephrase")


# ---------------------------------------------------------------- verifier + research
def _json(reply: str | None) -> dict | None:
    """The first complete JSON object in an LLM reply, or None. Text around it, including stray extra braces (seen in
    gpt-4o-mini replies), is ignored."""
    text = reply or ""
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, start)
            return obj if isinstance(obj, dict) else None
        except ValueError:
            start = text.find("{", start + 1)
    return None


SUFFICIENCY_SYSTEM = (
    "You check whether retrieved SOURCES contain the information needed to answer a QUESTION from a personal-finance "
    "learner. Reply with ONLY JSON: {\"answers\": true} if the sources answer it fully or mostly, otherwise "
    "{\"answers\": false, \"missing\": \"<what the question asks for that the sources lack, under 15 words>\"}.")
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
        (→ replan looks for another agent; the fallback is used only if none answers);
      - follow-up questions get choices the user can click."""
    llm_on = current_llm() is not None
    updates, trace = {}, []
    for agent, o in (state.get("agent_outputs") or {}).items():
        if o.get("verified"):
            continue
        status = o.get("status", "answered")
        if status == "answered" and o.get("origin") in ("kb", "wikipedia") and llm_on:
            verdict = _json(ask_llm(SUFFICIENCY_SYSTEM, f"QUESTION: {state['question']}\n\nSOURCES:\n{o['content'][:6000]}"))
            if verdict is not None and verdict.get("answers") is False:
                missing = str(verdict.get("missing") or "").strip()
                if o["origin"] == "kb":
                    updates[agent] = {**o, "status": "not_found", "content": "", "sources": [], "missing": missing}
                    trace.append(f"verifier: {agent} knowledge-base sources don't answer the question → research")
                else:
                    updates[agent] = {**o, "status": "not_found", "content": "", "sources": [], "missing": missing,
                                      "verified": True, "fallback": {**o, "verified": True}}
                    trace.append(f"verifier: {agent} researched sources don't answer the question either"
                                 + (f" (missing: {missing})" if missing else ""))
                continue
            updates[agent] = {**o, "verified": True}
            trace.append(f"verifier: {agent} sources answer the question" if verdict else f"verifier: {agent} check unavailable, kept")
        elif status == "need_info":
            choices = o.get("choices") or []
            if llm_on and agent != "clarify":
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


def _unresolved(o: AgentOutput) -> bool:
    """Not found even after research, and replan hasn't yet looked for another agent to cover it."""
    return o.get("status") == "not_found" and bool(o.get("researched")) and not o.get("handed_off")


def route_after_verifier(state: FinanceState) -> str:
    outputs = (state.get("agent_outputs") or {}).values()
    if any(o.get("status") == "not_found" and not o.get("researched") for o in outputs):
        return "research"
    if (any(_unresolved(o) for o in outputs) and current_llm() is not None       # replan needs the LLM to judge what's missing
            and (state.get("replans") or 0) < get_config()["workflow"].get("max_replans", 3)):
        return "replan"
    return "illustrate"


def research_node(state: FinanceState, config: RunnableConfig):
    """Look up not_found topics on Wikipedia. With an LLM the question is first turned into article titles, so a long or
    misspelled sentence still finds the right page; without one the router's keyword query is used."""
    words, updates, trace, errors = _words(state), {}, [], []
    llm_topics: list[str] | None = None                         # asked once per pass: they depend only on the question
    for agent, o in (state.get("agent_outputs") or {}).items():
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


REPLAN_SYSTEM = """You coordinate the specialist agents of a personal-finance EDUCATION assistant. Some agents could not answer the user's question, even after a Wikipedia lookup. Decide which OTHER agents, if any, could supply what is still missing.

AGENTS
- qa: explains financial concepts from a finance knowledge base.
- market: live prices, quotes and performance of named stocks, ETFs and indices; market, sector and asset-class trends.
- news: recent headlines about a company, industry, sector, topic or the whole market.
- portfolio: analyses the user's own holdings.
- goal: a savings plan to reach a target amount by a date.
- tax: tax rules and account types.
- calc: computes a specific figure (growth, loan payment, doubling time, present value, real return, APY, bond yield).

RULES
- Choose only from the agents listed as AVAILABLE. Never choose an agent that was already tried.
- Choose an agent only if its job directly supplies what is missing. If none can, return an empty list: an honest "not found" is better than an unrelated answer.
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
        recent = H.transcript(state.get("history"))
        reply = _json(ask_llm(REPLAN_SYSTEM, f"Recent conversation:\n{recent or '(none)'}\n\nQuestion: {state['question']}\n\n"
                                             f"Already tried: {', '.join(tried)}\nWhat is missing:\n{missing}\n\n"
                                             f"AVAILABLE: {', '.join(available)}"))
        intents = list(dict.fromkeys(i for i in (reply or {}).get("intents", []) if i in available))
        reason = str((reply or {}).get("reason") or "").strip()
    res = {"replans": n, "replan_intents": intents, "tried_agents": tried + intents,
           "agent_outputs": {a: {**o, "handed_off": True} for a, o in unresolved.items()},
           "trace": [f"replan {n}/{limit}: " + (f"{', '.join(intents)}" + (f" ({reason})" if reason else "")
                                               if intents else "no other agent can supply what is missing")]}
    e = state.get("entities") or {}
    if {"market", "news"} & set(intents) and not (e.get("tickers") or e.get("indices") or e.get("companies")):
        res["entities"] = {**e, "companies": SYM.resolve(state["question"], history=state.get("history"))}   # as the router does
        if res["entities"]["companies"]:
            res["trace"].append("resolved " + ", ".join(_resolved_label(c) for c in res["entities"]["companies"]))
    return res


def route_after_replan(state: FinanceState) -> list[str]:
    return sorted(f"{i}_agent" for i in state.get("replan_intents") or []) or ["illustrate"]


def illustrate_node(state: FinanceState, config: RunnableConfig):
    """Add a worked example to conceptual answers: when a Q&A or tax answer is about something numeric, the LLM picks a
    calculation with sample numbers and Python computes it exactly. Skipped for calculations, non-numeric topics and
    basic mode (no LLM). Follow-up suggestions then let the user vary the numbers."""
    outputs = state.get("agent_outputs") or {}
    concept = [o for k, o in outputs.items() if k in ("qa", "tax") and o.get("status", "answered") == "answered" and o.get("content")]
    if not concept or "calc" in outputs or current_llm() is None:
        return {"trace": []}
    reply = _json(ask_llm(CALC.EXAMPLE_SYSTEM, f"Question: {state['question']}\n\nAnswer so far:\n{concept[0]['content'][:2500]}"))
    name, args = (reply or {}).get("function"), (reply or {}).get("args") or {}
    if name not in CALC.CATALOG:
        return {"trace": ["illustrate: no calculation fits this topic"]}
    try:
        text = CALC.run(name, args)
    except (TypeError, ValueError) as e:
        return {"trace": [f"illustrate: {name} rejected sample inputs ({e})"]}
    shown = ", ".join(f"{k}={v:g}" for k, v in args.items() if isinstance(v, (int, float)) and v)
    return {"agent_outputs": {"example": {"agent": "example", "content": f"{CALC.EXAMPLE_HEADING}\n\n{text}", "sources": [],
                                          "data_info": None, "confidence": "high", "error": None, "status": "answered",
                                          "verbatim": True}},
            "trace": [f"illustrate: {name}({shown})"]}


# ---------------------------------------------------------------- synthesizer + compliance
SYNTH_SYSTEM = (
    "You are Finnie, a friendly finance educator for beginners. Write the final answer using ONLY the context provided; "
    "do not add facts, numbers, tips or sources of your own, even well-known ones. If the context covers only part of the "
    "question, answer that part and say briefly what you couldn't cover. Match the user's knowledge level. Keep it concise "
    "and in plain language. When the context lists several headlines or items, cover each one in a short bullet list (title, "
    "publisher and a few words on what it says) instead of choosing one. Format with Markdown: **bold** for key figures, '- ' "
    "bullets for lists, and when the context gives the same figures for several items or periods, a Markdown table "
    "(| A | B | header row, then |---|---|) so the numbers line up. Never tell the user what to buy or sell and never promise returns. Do not include a disclaimer "
    "(it is added separately). Keep any figures exactly as given.")


def synthesizer_node(state: FinanceState, config: RunnableConfig):
    """Writes the reply from `answered` outputs only. Follow-up questions and "couldn't find" messages are passed through
    word for word, never rewritten, so the model can't turn "I need more details" into an invented answer."""
    outputs = [state["agent_outputs"][k] for k in ORDER if k in state.get("agent_outputs", {})]
    answered = [o for o in outputs if o.get("status", "answered") == "answered" and o.get("content")]
    asks = [o for o in outputs if o.get("status") == "need_info" and o.get("content")]
    missing = [o for o in outputs if o.get("status") == "not_found" and o.get("content")]
    partial = [] if answered or asks else [o["fallback"] for o in outputs if o.get("fallback")]
    answered = answered or partial                  # nothing better turned up: write from the research the verifier found incomplete
    choices = list(dict.fromkeys(c for o in asks for c in o.get("choices") or []))[:3]
    if answered:
        exact = [o for o in answered if o.get("verbatim")]          # calculator results: never reworded
        prose = [o for o in answered if not o.get("verbatim")]
        text, mode = "\n\n".join(o["content"] for o in prose), "extractive" if prose else "verbatim"
        if prose and current_llm() is not None:
            history = H.transcript(state.get("history"))
            context = "\n\n".join(f"[{o['agent']}]\n{o['content']}" for o in prose)
            level = state.get("profile", {}).get("knowledge_level", "beginner")
            shown_after = ("\n\nA worked calculation is shown separately right after your answer; don't do arithmetic and "
                           "don't say that calculations or examples are missing." if exact else "")
            data = MT.data_block(state.get("market_data") or {})        # exact figures the market tools fetched (volume, P/E...)
            figures = (f"\n\nData (exact figures from the market tools; use only those the question needs, and keep them "
                       f"exactly as given):\n{data}" if data else "")
            reply = ask_llm(SYNTH_SYSTEM, f"Knowledge level: {level}\nConversation so far:\n{history or '(none)'}\n\n"
                                          f"Question: {state['question']}\n\nContext:\n{context}{figures}{shown_after}")
            if reply:
                text, mode = reply, "llm"
        text = "\n\n".join(t for t in [text] + [o["content"] for o in exact] if t)
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


def compliance_node(state: FinanceState, config: RunnableConfig):
    text, removed = finalize(state["final_response"])
    return {"final_response": text, "context": CTX.build(state),            # saved with the answer for the next turn
            "trace": [f"compliance: {'removed %d advice-like sentence(s)' % removed if removed else 'no advice patterns found'}; disclaimer added"]}
