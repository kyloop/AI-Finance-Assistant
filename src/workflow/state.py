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
    origin: str                  # kb | wikipedia, for answered knowledge lookups
    query: str                   # not_found: what research should look up
    prefix: str                  # text kept in front of a researched answer (e.g. the tax caveat)
    choices: list[str]           # need_info: follow-up questions the user can pick
    no_results: bool             # answered "nothing found" (news): shown, but not a real answer to follow up on
    verbatim: bool               # shown word for word, never rewritten by the LLM (calculator results)
    verified: bool               # the verifier has checked this output; later passes skip it
    researched: bool             # the research node has already looked this up
    missing: str                 # not_found: what the verifier says the sources lack (for replan)
    handed_off: bool             # replan has already looked for other agents to cover this output
    fallback: dict               # a researched answer the verifier rejected; used only if nothing better turns up


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
    saved_goal: dict | None                                # the user's latest plan from the Goals tab
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
    context: dict                                          # saved with the answer; the next turn's context_in
    final_response: str
    choices: list[str]                                     # clickable follow-ups; a pick is sent back through the router
    answered: bool                                         # the reply answers the question (so follow-ups can be offered)
    agents: list[str]
    sources: list[dict]
    data_info: dict | None
    extras: dict[str, Any]
