# Design notes

Decision records and the measurements behind them.

| Document | What it covers |
|---|---|
| [rag-data-design.md](rag-data-design.md) | Knowledge-base storage (collection → category → document → section → chunk), why Qdrant, chunking method and chunk sizes |
| [kb-token-stats-basics.md](kb-token-stats-basics.md) | `basics` category: token counts per document, section and paragraph; chunk-size simulation; retrieval and answer-quality tests, max 512 vs max 250 |
| [kb-token-stats-bonds.md](kb-token-stats-bonds.md) | `bonds` category: the same measurements and both tests |
| [kb-token-stats-stocks.md](kb-token-stats-stocks.md) | `stocks` category (150 pages): the same measurements and both tests |
| [kb-token-stats-etfs-and-mutual-funds.md](kb-token-stats-etfs-and-mutual-funds.md) | `etfs-and-mutual-funds` category (50 pages): the same measurements and both tests |
| [kb-token-stats-goal-planning.md](kb-token-stats-goal-planning.md) | `goal-planning` category (150 pages): the same measurements and both tests; not indexed yet |
| [kb-eval-summary.md](kb-eval-summary.md) | Both tests for every category side by side, and combined |
| [yfinance-capabilities.md](yfinance-capabilities.md) | What the yfinance library (1.7.0) can fetch, checked live: per-ticker data, funds and ETFs, sectors, calendars, screeners; what the app uses and what it could add |
| [agent-code-map.md](agent-code-map.md) | Where each agent and workflow step lives in the code (functions, files, how to add a node) |
| [agent-tools.md](agent-tools.md) | Graph of which tools each agent and pipeline step calls, and the data source behind each tool |
| [agent-portfolio-agent.md](agent-portfolio-agent.md) | Portfolio agent: its responsibility and the data it needs (user portfolio data, live market data, knowledge base); the Portfolio tab report it shares, how each metric is computed and its limits |
| [data/](data/) | CSVs behind the stats (`python -m scripts.kb_token_stats`), the retrieval test (`python -m scripts.eval_retrieval`) and the answer-quality test (`python -m scripts.eval_generation`, needs `OPENAI_API_KEY`) |

One `kb-token-stats-<category>.md` per category as more categories are measured. `python -m scripts.kb_report --category <name>`
writes a category doc from the CSVs (keeping its hand-written notes and findings) and `--summary` rewrites the summary.
