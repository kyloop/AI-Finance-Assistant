# Topic guardrail

**Rule: Finnie answers questions about personal finance, investing, markets, the economy and money. It declines
anything else** (sport, recipes, travel, health, celebrities, coding, homework, trivia, jokes, poems).

## How it is enforced

1. **The router declines it (LLM mode).** Rule 13 of `ROUTER_SYSTEM` in `src/workflow/nodes.py` lets the router return
   `["off_topic"]`. `_route` then sends the message to `off_topic_node` alone. No agent, Wikipedia lookup or web search
   runs, and the reply is fixed: **"🚫 Off topic: Finnie only covers personal finance."**, followed by what Finnie can
   help with and starter questions to click. If the router returns `off_topic` together with a finance intent ("who won
   the World Cup, and what is an ETF?"), `off_topic` is dropped and the finance part is answered. Follow-ups in a finance
   conversation and money questions about any subject ("how much should I save for a wedding?") are not off-topic.
2. **Sources must be about finance (every mode).** Without an LLM there is no reliable way to tell a finance question
   from another from keywords alone ("What is an ETF?" contains no finance word), so basic mode doesn't decline up front.
   Instead every outside source has to pass `is_finance` (`src/workflow/tools.py`: at least two finance words in the title
   and the start of the text):
   - Wikipedia pages (`wiki_search`, `wiki_topic`), as before;
   - Tavily web results in Research (`_web_research`); the trace records how many were dropped as "not about finance".

   The knowledge base only holds finance articles, so an off-topic question that gets past the router finds nothing
   usable and ends in the "I'd rather not guess" reply instead of an answer.
3. **Tests.** `tests/test_workflow.py` checks that the LLM router's `off_topic` route runs no agent, research or
   synthesis, and that a finance part next to an off-topic one is still answered. `tests/test_tavily.py` checks that web
   results that aren't about finance are dropped, and `test_off_topic_wikipedia_hits_are_rejected` does the same for
   Wikipedia.

## Limits

- The up-front decline needs an LLM; in basic mode an off-topic question gets "I'd rather not guess" rather than the
  off-topic message.
- The router is an LLM judgment: an unusual wording can be routed either way. A false "off-topic" is visible (the
  fixed message) and the user can rephrase; a missed one is caught by the source filter in step 2.
- The News agent's web news search is not filtered: it only runs for companies, markets or topics the router already
  found in a finance question.
