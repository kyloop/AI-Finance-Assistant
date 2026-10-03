# Agent code map

Where each agent and workflow step lives in the code. For what the steps do, see the
[README: Chatbot orchestrator](../README.md#chatbot-orchestrator-langgraph); for the tools each one calls and the data behind
them, see [Agent tools](agent-tools.md).

There is no separate file per agent. Every agent and step is a function in
[src/workflow/nodes.py](../src/workflow/nodes.py), and [src/workflow/graph.py](../src/workflow/graph.py) wires them into
the LangGraph graph.

## Agents and steps

All in [src/workflow/nodes.py](../src/workflow/nodes.py). Agents are wrapped in `@safe("<name>")`, which records a failure
in state instead of crashing the graph, so the other agents still answer.

| Graph node | Function | Notes |
|---|---|---|
| `proofread` | `proofread_node` | LLM rewrite of the message with spelling, grammar and abbreviations fixed, and a follow-up completed from the previous answer's context (`PROOFREAD_SYSTEM`, `CTX.describe`); sets `follow_up`. `_proofread_ok` rejects a rewrite that drops a number or ticker, or adds one that isn't in the message or context. Replaces `question`; `original_question` keeps what was typed. Without an LLM, `follow_up` comes from `context.looks_like_follow_up`. |
| `router` | `router_node` | LLM intent classifier, keyword fallback (`classify` in `router.py`). Company names for market/news questions are resolved here (`_routed`). `route_after_router` decides which agents run. |
| `qa_agent` | `qa_node` | Knowledge-base answer via `_kb_answer` (shared with Tax) |
| `tax_agent` | `tax_node` | `_kb_answer` with a tax-focused query and caveat |
| `market_agent` | `market_node` | Tool-calling agent over `market_tools.py`: `_llm_fetch` lets the model pick tools (`MARKET_TOOL_SYSTEM`, `MT.TOOL_SPECS`), `_fill_in` guarantees a quote per company and the asked/carried period's performance (`_period_for`), `MT.describe_lines` writes the text. Symbols: tickers, indices, carried companies, the UI's watchlist or selected stock (`_view_symbols`). Writes `market_data` and `turn_context` |
| `news_agent` | `news_node` | Live headlines, the news index, industry peers (`_sector_news`, `_live_news`, `_relevant_news`) |
| `portfolio_agent` | `portfolio_node` | `portfolio_instruments` / `portfolio_history` in `src/core/portfolio_data.py` fetch the data; `analyze_portfolio` / `portfolio_performance` in `src/core/calculators.py` do the maths. No LLM: the node fills a fixed text template with the figures. Performance counts each holding from its purchase date (`portfolio.default_purchase_date` in `config.yaml` when it has none) |
| `goal_agent` | `goal_node` | `project_goal` in `src/core/calculators.py`; the Goals tab's saved plan via `_saved_goal_answer` |
| `calc_agent` | `calc_node` | Picks a calculation from `CATALOG` in `calc.py` (LLM or `keyword_request`), runs it with `calc.run` |
| `clarify` | `clarify_node` | Fixed "please rephrase" message with starter choices |
| `verifier` | `verifier_node` | Checks each new output once (`verified`): knowledge-base and researched answers (LLM sufficiency check, `SUFFICIENCY_SYSTEM`), choices for `need_info`. `route_after_verifier` sends unresearched `not_found` to research, still-unanswered ones to replan, the rest to illustrate |
| `research` | `research_node` | Wikipedia lookup (`wiki_topic` / `wiki_search`) for `not_found` outputs not yet researched; always goes back to the verifier |
| `replan` | `replan_node` | Picks agents not yet tried for outputs still `not_found` after research (`REPLAN_SYSTEM`, `_unresolved`); `route_after_replan` runs them or moves on to illustrate. Capped by `workflow.max_replans` |
| `illustrate` | `illustrate_node` | Worked example with sample numbers, computed by `calc.run` |
| `synthesizer` | `synthesizer_node` | Writes the reply from `answered` outputs only |
| `followups` | `followups_node` | Suggested next questions |
| `compliance` | `compliance_node` | `finalize` in `safety.py`: strips advice, adds the disclaimer |

Shared helpers in `nodes.py`: `_out` builds an `AgentOutput`, `_not_found` marks a lookup for research, and `_db` gets the
database session from the graph config.

## Supporting files

| File | What it holds |
|---|---|
| [src/workflow/graph.py](../src/workflow/graph.py) | `get_graph` (nodes and edges, including the research → verifier and replan → agents loops), `AGENT_NODES`, `FLOW_NODES` (the UI's agent-flow layout, kept in step with the graph by `tests/test_flow.py`), `RUN_CONFIG` (LangGraph recursion limit) and the entry points `run_chat` / `stream_chat` called by the API |
| [src/workflow/state.py](../src/workflow/state.py) | `FinanceState` (the state passed between nodes, including the loop's `tried_agents`, `replans`, `replan_intents`) and `AgentOutput` (each agent's result: content, sources, status, choices, and the loop flags `verified`, `researched`, `missing`, `handed_off`, `fallback`) |
| [src/workflow/tools.py](../src/workflow/tools.py) | Tools the nodes call: `kb_search`, `wiki_search`, `wiki_topic`, `market_quotes`, `news_latest`, `news_search`, `news_index_now` (and `resolve_symbol`, `industry_peers` re-exported from the market service), plus the `set_*` hooks tests use to swap in fakes |
| [src/workflow/market_tools.py](../src/workflow/market_tools.py) | The market agent's tools (`get_quote`, `get_performance`, `get_company_profile`, `get_fund_profile`; `TOOL_SPECS`, `run_tool`), period parsing (`asked_period`, `parse_period`), `period_stats`, `merge_market` (reducer for `market_data`), `describe_lines` / `data_block` (text and prompt formatting) |
| [src/workflow/context.py](../src/workflow/context.py) | Conversation context saved with each answer (`messages.context`): `build` (in `compliance_node`), `carried` (the previous context for a follow-up), `describe` (for prompts), `merge_turn` (reducer for `turn_context`, which the market agent fills) |
| [src/workflow/router.py](../src/workflow/router.py) | Keyword intent patterns (`INTENT_PATTERNS`, `classify`), entity extraction (`extract_entities`), LLM reply parsing (`parse_llm_intents`) |
| [src/workflow/symbols.py](../src/workflow/symbols.py) | Company mentions to tickers (`resolve`), using the LLM and `resolve_symbol` |
| [src/workflow/calc.py](../src/workflow/calc.py) | Calculator catalog, prompts and result formatting; the maths is in `src/core/calculators.py` |
| [src/workflow/news.py](../src/workflow/news.py) | News agent helpers: time window, tickers, topic words, story formatting |
| [src/workflow/safety.py](../src/workflow/safety.py) | Advice filter and disclaimer (`filter_advice`, `finalize`) |

Outside `src/workflow/`:

| File | What it holds |
|---|---|
| [src/core/llm.py](../src/core/llm.py) | Provider selection and `ask_llm`, the single LLM call every node uses |
| [src/core/market_service.py](../src/core/market_service.py) | Cached market data (`get_market_data`: quote, history, intraday, news, fund, stock), `resolve_symbol`, `industry_peers` |
| [src/core/calculators.py](../src/core/calculators.py) | Portfolio analysis and performance (`analyze_portfolio`, `portfolio_performance`: time-weighted return and risk, each holding counted from its purchase date or its own first close when that is later), goal projection and the finance formulas |
| [src/core/portfolio_data.py](../src/core/portfolio_data.py) | Market data for the portfolio report, shared by the Portfolio tab and the Portfolio agent: priced instruments (`portfolio_instruments`), price history against the benchmark since the earliest purchase, 10 years at most (`portfolio_history`), dividends (`portfolio_dividends`, Portfolio tab only). The benchmark, risk-free rate and default purchase date come from `portfolio` in `config.yaml` |
| [src/api/routers/portfolio.py](../src/api/routers/portfolio.py) | The Portfolio tab's endpoints: `GET`/`PUT /portfolio` (holdings, plus `default_purchase_date` for the empty purchase-date field) and `GET /portfolio/analysis` (the report) |
| [src/rag/](../src/rag/) | Knowledge-base and news vector search (Qdrant) behind `kb_search` / `news_search` |
| [src/api/routers/chat.py](../src/api/routers/chat.py) | The `/chat` and `/chat/stream` endpoints that call `run_chat` / `stream_chat` |

## Adding or changing a node

1. Write the function in `nodes.py` (wrap an agent in `@safe`).
2. Register it in `get_graph` in `graph.py` (agents go in `AGENT_NODES`; a new agent also needs an intent in
   `R.INTENTS`, a line in `ROUTER_SYSTEM` and in `REPLAN_SYSTEM`, so the router and replan can pick it).
3. Add it to `FLOW_NODES` so the agent-flow panel draws it; `tests/test_flow.py` fails until you do.
4. If it reads or writes new state, add the field to `FinanceState` in `state.py`.

## Market data access today

Three agents use market data, all through `get_market_data` in `market_service.py`:

- Market: `market_quotes` (quotes only).
- News: `news_latest` and `industry_peers`.
- Portfolio: the quote for each holding's price; its asset type, sectors and fees from the bundled record
  (`INSTRUMENTS`) when there is one, otherwise the fund or stock endpoint; and the price-history endpoint for the holdings
  and the benchmark. Without a database it falls back to the bundled sample prices.

Q&A, Tax, Goal and the Calculator have no market data. A shared market-data step for all agents has been proposed but
not built.
