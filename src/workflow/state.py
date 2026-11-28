import operator
from typing import Annotated, Any, TypedDict

from .context import merge_turn
from .market_tools import merge_market


def merge_dicts(a: dict, b: dict) -> dict:
    return {**(a or {}), **(b or {})}


class AgentOutput(TypedDict, total=False):
    agent: str
    content: str
    sources: list[dict]          # {id, title, url}
    data_info: dict | None       # {provider, fetched_at, freshness}
    confidence: str              # high | medium | low
    error: str | None
    status: str                  # answered | not_found | need_info (verifier routes on this)
    origin: str                  # kb | wikipedia | web, for answered knowledge lookups
    query: str                   # not_found: what research should look up
    prefix: str                  # text kept in front of a researched answer (e.g. the tax caveat)
    choices: list[str]           # need_info: follow-up questions the user can pick
    readings: bool               # need_info: the choices are the calculator's readings of the question, kept as is
    no_results: bool             # answered "nothing found" (news): shown, but not a real answer to follow up on
    reading: str                 # answered on a guess: how the question was read, shown to the user ("the latest market-wide headlines")
    alternatives: list[str]      # ...and other readings they can pick instead (clickable choices)
    verbatim: bool               # shown word for word, never rewritten by the LLM (calculator results)
    verified: bool               # the verifier has checked this output; later passes skip it
    researched: bool             # the research node has already looked this up
    web_searched: bool           # research's second pass has already searched the web for it
    missing: str                 # not_found: what the verifier says the sources lack (for replan)
    handed_off: bool             # replan has already looked for other agents to cover this output
    fallback: dict               # a researched answer the verifier rejected; used only if nothing better turns up


class TurnContext(TypedDict, total=False):
    """What one answer saves in `messages.context` (context.build) and the next turn reads as `context_in`.
    Rows written before topic memory lack the last three fields; read them with .get()."""
    question: str                 # the corrected question
    intents: list[str]
    companies: list[dict]         # [{symbol, name}], at most 3
    markets: list[dict]           # [{key, name}], at most 3
    levels: list[str]             # company | sector | region | market | asset class
    tab: str | None
    symbol: str | None
    period: dict | None           # {label, start}
    facts: dict[str, dict]        # per symbol: price, return, start_price, end_price, as_of, period
    tax: dict | None              # the tax agent's last estimate (tax_calc)
    scenario: dict | None         # the worked example the answer gave: {kind, goal_type, text, figures} (context.scenario_line)
    topic_id: str | None          # "t1": carried from the previous turn, else assigned after the turn (topics.record_turn)
    summary: str                  # one sentence on what was discussed, no figures; written after the reply
    source_ids: list[str]         # kb:… | wikipedia:… | web:… | news:… (mds/topic-memory.md)
    related: list[str]            # topics.uid of earlier chats' topics this turn was linked to (topic node)
    linked: list[dict]            # the same, for the UI: [{uid, date, label}]


class FinanceState(TypedDict, total=False):
    # inputs
    question: str                                          # after the proofread node: the corrected message
    original_question: str                                 # what the user typed
    context_in: dict | None                                # the previous answer's saved context (see context.py)
    follow_up: bool                                        # proofread: this message continues from context_in
    history: list[dict]                                    # [{role, content}] oldest first
    profile: dict
    holdings: list[dict]
    view: dict | None                                      # {tab, selected, watchlist} from the UI
    screen: dict | None                                    # proofread: the message is about the tab on screen (context.screen)
    scenario_now: dict | None                              # proofread: the previous answer's example as the message changes it
                                                           # (context.scenario_change: the house example with a loan)
    saved_goal: dict | None                                # the user's latest plan from the Goals tab
    topics_in: dict | None                                 # {"current": [...], "earlier": [...]}: topics the message may belong to
                                                           # (topics.candidates); None (run_chat without it) = no topic memory
    # topic node output (mds/topic-memory.md)
    topic: dict                                            # {action, topic_id, related, linked, note}
    topic_background: str                                  # earlier chats' dated summaries for the synthesizer
    # router output
    intent: list[str]
    entities: dict
    router_mode: str                                       # llm | keywords
    tried_agents: list[str]                                # intents of every agent run so far (router + replans)
    # replan loop: when an agent and research both fail, replan picks other agents (at most workflow.max_replans times)
    replans: int
    replan_intents: list[str]
    # parallel agent writes are merged by reducers
    agent_outputs: Annotated[dict[str, AgentOutput], merge_dicts]
    errors: Annotated[list[str], operator.add]
    trace: Annotated[list[str], operator.add]
    turn_context: Annotated[dict, merge_turn]              # companies, period and figures the agents used this turn
    market_data: Annotated[dict, merge_market]             # {"TSLA": {"quote": {...}, "period": {...}, "profile": {...}}}: every figure
                                                           # the market tools fetched this turn, for the synthesizer
    # final
    context: TurnContext                                   # saved with the answer; the next turn's context_in
    final_response: str
    choices: list[str]                                     # clickable follow-ups; a pick is sent back through the router
    answered: bool                                         # the reply answers the question (so follow-ups can be offered)
    agents: list[str]
    sources: list[dict]
    data_info: dict | None
    extras: dict[str, Any]
