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
| `topic` | `topic_node` | Topic memory: which topic the message belongs to (`topics.choose`, mds/topic-memory.md); reopens an older topic's context, links earlier chats and passes their notes to the synthesizer. A no-op when the run has no topics. |
| `qa_agent` | `qa_node` | Knowledge-base answer via `_kb_answer` (shared with Tax) |
| `tax_agent` | `tax_node` | The tax expert ([agent-tax-agent.md](agent-tax-agent.md)): tools in `tax_tools.py`. Amounts + "how much tax" → `estimate_income_tax` (`tax_calc.answer` → `income_tax.estimate`), verbatim steps + read-more `_tax_pages`; saved plan → `_kb_answer` with `PLAN_TAX_SEARCHES` and `_plan_tax_facts` + `tax_on_plan` as `verbatim_tail`; else `_kb_answer` on the tax and retirement categories with the caveat |
| `market_agent` | `market_node` | Tool-calling agent over `market_tools.py`: `_llm_fetch` lets the model pick tools (`MARKET_TOOL_SYSTEM`, `MT.TOOL_SPECS`), `_fill_in` guarantees a quote per company and the asked/carried period's performance (`_period_for`), `_levels_asked` / `_fill_levels` add sector and market-overview figures by level (`entities["levels"]`), `_fill_wide` / `_market_wide` the market-wide figures (most active, largest companies, market hours) a question asks for without naming a subject, `MT.describe_lines` writes the text (`_market_result`). Symbols: tickers, indices, carried companies, the UI's watchlist or selected stock (`_view_symbols`). Writes `market_data` and `turn_context` |
| `news_agent` | `news_node` | Live headlines, the news index, industry peers (`_sector_news`, `_live_news`, `_relevant_news`) |
| `portfolio_agent` | `portfolio_node` | `portfolio_instruments` / `portfolio_history` in `src/core/portfolio_data.py` fetch the data; `analyze_portfolio` / `portfolio_performance` in `src/core/calculators.py` do the maths. `src/workflow/portfolio_report.py` writes the answer: `focus` picks the sections the question asks for (diversification, performance, risk, fees, dividend income; all of them for a general or "analyse my portfolio" question, which is shown verbatim), and each section gives the figures with a rule-based explanation. No LLM in the node. Performance counts each holding from its purchase date (`portfolio.default_purchase_date` in `config.yaml` when it has none) |
| `goal_agent` | `goal_node` | `project_goal` in `src/core/calculators.py`; the Goals tab's saved plan via `_saved_goal_answer` |
| `calc_agent` | `calc_node` | `calculate` → `calc_pipeline.calculate`: `UNDERSTAND_SYSTEM`, `DEFINE_SYSTEM` (`_targets`), per formula target `find_equation` (`_kb` + `_web` in parallel, `extract` with `EXTRACT_SYSTEM` and quote checks, then `translate` (`plain`, else `TRANSLATE_SYSTEM`), `_match` with `MATCH_SYSTEM`, `REFINE_SYSTEM`), `name_equations`, `VARIABLES_SYSTEM`, `build_plan`, then `calc_plan.run(require_checks=False)` and `calc.plan_text` (quotes). Fallback `plan_calculation`: `calc.PLAN_SYSTEM`, `calc_plan.run`, judge `calc.JUDGE_SYSTEM` on `CheckFailed`, `calc.repair_prompt` (given the sourced equations when step 4 failed). Nothing computes: `calc_pipeline.confirm` with `CONFIRM_SYSTEM`. Without an LLM: `calc.keyword_request` + `calc.run` |
| `clarify` | `clarify_node` | Fixed "please rephrase" message with starter choices |
| `read_only` | `read_only_node` | The read-only guardrail: `R.write_request` (or the LLM router's `read_only` intent) flags a request to change data, trade or alter the system; fixed "⚠️ Request flagged" message by kind (`READ_ONLY_MESSAGES`), nothing is changed (mds/read-only-guardrail.md) |
| `off_topic` | `off_topic_node` | The topic guardrail: the LLM router's `off_topic` intent (rule 13 in `ROUTER_SYSTEM`) declines a non-finance message with a fixed "🚫 Off topic" reply (`OFF_TOPIC_MESSAGE`); nothing is looked up (mds/topic-guardrail.md) |
| `verifier` | `verifier_node` | Checks each new output once (`verified`): knowledge-base and researched answers (LLM sufficiency check, `SUFFICIENCY_SYSTEM`; one whose gap another agent's answer already fills is dropped as `covered`, with no research or replan), choices for `need_info`. `route_after_verifier` sends unresearched `not_found` to research, still-unanswered ones to replan, the rest to illustrate |
| `research` | `research_node` | Wikipedia lookup (`wiki_topic` / `wiki_search`) for `not_found` outputs not yet researched; a second pass (`_web_research`, when `_needs_web` and a Tavily key is set) searches the web. Always goes back to the verifier |
| `replan` | `replan_node` | Picks agents not yet tried for outputs still `not_found` after research (`REPLAN_SYSTEM`, `_unresolved`); `route_after_replan` runs them or moves on to illustrate. Capped by `workflow.max_replans` |
| `illustrate` | `illustrate_node` | Worked example: `EXAMPLE_SYSTEM` writes the calculation (this turn's figures, else sample numbers), `calculate` works it out in worked-example mode |
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
| [src/workflow/market_tools.py](../src/workflow/market_tools.py) | The market agent's tools (`get_quote`, `get_performance`, `get_company_profile`, `get_fund_profile`, `get_sector_performance`, `get_market_overview`; `TOOL_SPECS`, `run_tool`), period parsing (`asked_period`, `parse_period`), `period_stats`, `merge_market` (reducer for `market_data`), `describe_lines` / `data_block` (text and prompt formatting) |
| [src/workflow/context.py](../src/workflow/context.py) | Conversation context saved with each answer (`messages.context`): `build` (in `compliance_node`), `carried` (the previous context for a follow-up), `describe` (for prompts), `merge_turn` (reducer for `turn_context`, which the market agent fills) |
| [src/workflow/topics.py](../src/workflow/topics.py) | Topic memory (mds/topic-memory.md): `choose` (the `topic` node's decision: continue, reopen, link or new), `candidates` (topics loaded for a turn), `record_turn` (after each reply, from `chat.py`: the turn's topic, summary, entities and embedding), `apply_turn` (folds a turn into a topic), `rebuild_topic` (recreates a topic from its messages) |
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
| [src/core/calculators.py](../src/core/calculators.py) | Portfolio analysis and performance (`analyze_portfolio`, `portfolio_performance`: time-weighted return and risk, each holding's contribution to it, the benchmark's volatility and drawdown, each holding counted from its purchase date or its own first close when that is later), goal projection and the finance formulas |
| [src/core/portfolio_data.py](../src/core/portfolio_data.py) | Market data for the portfolio report, shared by the Portfolio tab and the Portfolio agent: priced instruments (`portfolio_instruments`), price history against the benchmark since the earliest purchase, 10 years at most (`portfolio_history`), dividends (`portfolio_dividends`, the Portfolio tab and the agent's income section). The benchmark, risk-free rate and default purchase date come from `portfolio` in `config.yaml` |
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
