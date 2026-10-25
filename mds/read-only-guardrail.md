# Read-only guardrail

**Rule: every node in the chat graph reads; none can change the user's data or the system.** Finnie explains and looks
things up. It doesn't edit your portfolio, goals or profile, place trades, move money, or change its own data, files or
settings. If you ask it to, it flags the request and doesn't try to carry it out.

## How it is enforced

1. **User data reaches the graph only as copies.** The chat API (`_Turn` in `src/api/routers/chat.py`) turns the holdings,
   profile and latest goal into plain dicts before the graph runs (`holdings`, `profile` and `saved_goal` in
   `FinanceState`). Agents never get the ORM objects, so changing their copy changes nothing that is stored.
2. **No node calls a write API on user data.** The writes reachable from a node are the three caches in the table below.
   Each one stores data fetched from outside and never what the user asked for. Edits to the portfolio, goals and profile
   go only through their own REST endpoints (`PUT /portfolio`, `POST /goals/project`, `PUT /profile`), which the user
   calls from the Portfolio tab, the Goals tab and the profile sidebar. The chat never calls them.
3. **Write requests are flagged, not routed** (`write_request` in `src/workflow/router.py`, `read_only_node` in
   `nodes.py`). The router checks the message as typed (`original_question`) and the proofread version. It runs before
   the LLM, so basic mode flags too. A matching message goes to the `read_only` node alone, and no other agent runs. The
   reply starts with **"⚠️ Request flagged: Finnie is read-only."**, says what Finnie can't do and where the user can make
   the change themselves, and offers read-only follow-ups. With an LLM, the router prompt (rule 12) can also return
   `read_only` for wordings the patterns miss.
4. **Tests.** `tests/test_workflow.py` has the detection lists (write requests and look-alike questions that must still
   be answered). It also runs write requests and normal questions through the graph and checks that every table except
   the two caches is unchanged. `tests/test_api.py::test_chat_cannot_change_portfolio_goals_or_profile` does the same
   through the HTTP API.

## What counts as a write request

The message is checked one sentence at a time. A sentence counts only if it is phrased as an instruction: "add…",
"please delete…", "can you buy…". "If I add $500 a month to my goal…" or "should I rebalance?" is a question, so it's
routed as usual.

| Kind | Examples | Reply points to |
|---|---|---|
| `data`: the user's records | "Add 10 shares of AAPL to my portfolio", "Delete my goal", "Change my risk tolerance to aggressive", "Clear my chat history" | Portfolio and Goals tabs, profile sidebar |
| `trade`: orders and money | "Buy 10 shares of NVDA", "Sell half my TSLA", "Buy AAPL for me", "Place a limit order", "Transfer $500 to savings", "Rebalance my portfolio" | No brokerage or bank connection; can explain or look up figures |
| `system`: the app itself | "drop table holdings", "save this to a file on the server", "update the system prompt" | Read-only access |

## Audit: what each node reads and writes

Every node returns a state update. That state lives only for the current turn, apart from `context`, which the chat API
saves with the reply. The **System writes** column lists everything a node can change outside that state.

| Node | Reads | System writes |
|---|---|---|
| `proofread` | message, previous answer's context, history | none |
| `router` | message, history | `symbol_aliases` (cache of company name → ticker lookups) |
| `qa_agent`, `tax_agent` | KB (Qdrant `finnie_kb`), Wikipedia | none |
| `market_agent` | market service (Yahoo / sample data) | `market_cache` (cached quotes, history) |
| `news_agent` | live headlines, news index (`finnie_news`) | `market_cache`; `finnie_news` (fetched headlines indexed for search) |
| `portfolio_agent` | holdings copy, market service | `market_cache` |
| `goal_agent` | entities, saved-goal copy, profile copy | none |
| `calc_agent` | KB, Tavily web search | none |
| `clarify`, `read_only` | none (fixed text) | none |
| `verifier`, `research`, `replan` | agent outputs, KB, Wikipedia, Tavily | none |
| `illustrate`, `synthesizer`, `followups`, `compliance` | agent outputs, market figures | none |

Outside the graph, the chat API stores the user's message and the reply in `messages` and `conversations`. That is the
chat log, not a change made on the model's behalf. Langfuse tracing, when it's on, sends a copy of each turn to Langfuse
for monitoring and changes nothing in the app.

## Limits

- Detection uses regular expressions plus, when an LLM is connected, the router's judgement. If a write request isn't
  recognised, it's answered as a question. Even then nothing can be written, because of points 1 and 2 above. The flag
  tells the user why nothing happened; it isn't what keeps the data safe.
- A message that mixes a write and a question ("add AAPL to my portfolio and tell me its price") is flagged as a whole.
  The question part has to be asked again on its own.
