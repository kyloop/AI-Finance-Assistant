# News index and News agent

Token statistics, the retrieval test (hit@1, hit@5, hint@5, MRR) and the answer-quality test (relevance, faithfulness, correctness, completeness) are in [news-eval.md](news-eval.md).

Why: the chat needs cross-ticker, topic questions ("what's been said about chip export restrictions this week?") and history
longer than Yahoo's ~30 stories. Pasting full stories into the prompt costs too many tokens; retrieval sends the top few.

## Index (`src/rag/news.py`)
- Own Qdrant collection `finnie_news` (not `finnie_kb`), same embedding model, same client (local Qdrant allows one client per process).
- One point per story: text = title + summary. Payload: `title, summary, publisher, url, published, published_ts, ingested_at, tickers`.
  Point id = hash of the Yahoo story id, so a story fetched again (or for another ticker) is never duplicated; it only gains the ticker.
- Ingest: every fresh Yahoo news fetch (`market_service.news_listeners`, background thread) plus a poll every `news_index.poll_seconds`.
- Poll covers: the market feed, portfolio holdings, and any ticker whose quote or news was fetched in the last `recent_view_days`
  (the Live-tab watchlist and Market-tab searches both go through those fetches), capped at `max_tracked_symbols`.
- Stories older than `retention_days` are skipped on ingest and deleted after each poll.

## Agent (`news_node`, `src/workflow/news.py`)
- No topic words left after removing generic phrasing, tickers and dates ("latest on AAPL", "market news") → live 5-minute cached feed.
- Otherwise vector search with ticker and date filters ("this week" → 7 days, default `default_days`). Hits must score at least
  `min_score` and within `score_margin` of the best.
- **Finds the company or ticker with tools.** A name the router doesn't know ("Palantir") is resolved on Yahoo's symbol search
  (`market_service.resolve_symbol`; a hit must be a stock, ETF or index whose name contains the word the user wrote; falls back to the bundled
  instruments offline). With an LLM the names are extracted by the model, without one by phrasing cues ("news on X", "X stock"). The Market
  agent uses the same lookup for "price of Palantir".
- **Two live news sources.** Yahoo's ticker news feed can return nothing for a ticker (seen on 2026-10-01 for PLTR and MSFT while quotes
  worked), so `_yf_news` falls back to Yahoo's search endpoint, which returns headlines with publisher and time but **no summary**. Those
  stories are indexed by title alone, which retrieves less well (see the title-only rows in [news-eval.md](news-eval.md)). Resolved company
  names are saved in the `symbol_aliases` table so a restart or a Yahoo outage doesn't lose them.
- **A topic question about a ticker that isn't indexed yet** fetches its headlines live, indexes them on the spot, and searches again. If the
  feed has stories but none on the topic, it shows the latest headlines labelled as such.
- Only after those steps does it say nothing was found, and the message lists what was tried. It never falls through to the Wikipedia research
  step. Stories are returned as sources.

## Limits
Yahoo news is a title and short summary, so answers are headline-level. Only tickers we ingest are searchable. Yahoo's feed isn't a
real-time wire. `min_score` was calibrated on hand-written headlines (the sandbox couldn't reach Yahoo); recheck it on real stories.

## Findings
- **Score calibration** (bge-small, 7 hand-written headlines, not real Yahoo stories): on-topic matches scored 0.62-0.80 (e.g. "chip export
  restrictions" vs an export-rules headline 0.77; "NVDA export rules" 0.62). Off-topic stories scored up to 0.61 (an oil story for a chip
  question 0.57; a Nvidia story for an interest-rate question 0.61); unrelated queries scored 0.39-0.49. The first guess of 0.55 let the
  off-topic ones through, so the floor is 0.60 plus `score_margin` 0.08 below the best hit. Recheck on real stories once indexed.
- **Parallel agents must not share a DB session.** "Latest on NVDA" runs `market_agent` and `news_agent` in parallel threads; sharing the
  request's SQLAlchemy session between them failed intermittently in tests ("transaction is closed"). `news_node` opens its own session on
  the same engine. `market_agent` still uses the shared one.
- **Stale cache is not indexed.** Stories enter the index only on a live fetch, so if Yahoo is unreachable the index stops growing; the
  chat can still show the stale cached headlines.

## Measured on real stories (finnie.db news cache, 2026-10-01)
190 unique stories from 210 fetched (MARKET, AAPL, NVDA, AM, AMD, SPY, SPCX); 18 appear in more than one feed; no duplicate titles.
- **Size:** title + summary is 20-167 tokens (median 64, p95 123) against the embedder's 512 limit, so one chunk per story never truncates.
  Summaries are 76-599 characters (median 205), none empty, 20 under 100 characters.
- **Age:** median 26 hours, but 29 of 190 (15%) are older than 14 days (the oldest is about 178 days), so the retention filter does drop stories.
- **Scores on real stories** (5 feeds, 132 stories in the window): on-topic queries top out at 0.64-0.78 ("Nvidia AI data center demand" 0.78,
  "Federal Reserve interest rates" 0.68, "Apple iPhone" 0.67). Unrelated queries top out at 0.46-0.54. The weakness is a topic that is
  near but not covered: "chip export restrictions" has no matching story in the cache, yet the top four chip stories score 0.62-0.64 and pass
  `min_score` 0.60. A dense embedding can't tell "chips" from "chip export rules", so such answers show related stories, not a "nothing found".
- **Ticker tags are the feed, not the subject:** a story fetched through NVDA's feed is tagged NVDA even if it is mostly about AMD or software
  stocks ("In AI Race, Software Is Now Winning Alongside Chips"). A ticker filter returns what Yahoo lists for that ticker.
