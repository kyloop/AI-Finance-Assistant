# Ticker directory

Why: the chat resolves what the user typed ("NU", "NUU", "nvdia", "Palantir", "s&p 500 etf") to a Yahoo symbol. That used to cost a Yahoo
search per new name and failed offline for anything outside the 15 bundled instruments. Now every US-listed stock and ETF is on disk. Prices
are not stored; they stay live from the market service.

Code: `src/rag/tickers.py` (lookup, index), `src/rag/build_tickers.py` (download + build), hooked into `market_service.resolve_symbol`.
Config: `symbols_index` in `config.yaml`. Tests: `tests/test_tickers.py`.

## Data
- Sources: Nasdaq Trader `nasdaqlisted.txt` + `otherlisted.txt` (all US exchanges) and SEC `company_tickers.json`. All free.
  The SEC file is ordered by market cap, so its position is the `rank` used to break ties ("NUU" -> NU before NUV; "applle" -> Apple Inc.
  before Apple Hospitality). SEC requests need a contact in the user agent: set `SEC_USER_AGENT="Your Name you@example.com"` in `.env`.
- Saved to `src/data/raw/tickers.csv` (symbol, name, exchange, asset_type, rank; ~15k rows, ~9.4k stocks and ~5.7k ETFs). Committed, so
  lookups work offline. Test issues, warrants, rights, units, preferreds and notes are dropped; names lose "- Class A Common Stock" and similar.
- Refresh: `python -m src.rag.build_tickers` (download, then rebuild the index). `--offline` rebuilds from the CSV; `--csv-only` skips the index.
  The local Qdrant store allows one process, so stop the API first. If the collection is missing, the API builds it from the CSV in the
  background at startup (~40 s).

## Lookup order (`resolve_symbol`)
| # | Step | Example | How |
|---|---|---|---|
| 1 | saved names | anything resolved by Yahoo before | `symbol_aliases` table |
| 2 | exact ticker | `nu`, `brk.b` -> BRK-B | dictionary |
| 3 | name starts with the query | `Palantir`, `apple` | dictionary, best-ranked first |
| 4 | Yahoo symbol search | `Rivian` if not listed locally | network |
| 5 | close ticker | `NUU` -> NU (also NUE, NUV) | one edit away, 3-4 letter inputs only |
| 6 | misspelt name | `nvdia`, `netflx`, `disnee` | character similarity (difflib) |
| 7 | same meaning | `s&p 500 etf` -> VOO, `nu bank` -> NU | Qdrant vector search, `min_score` 0.80 |
| 8 | bundled sample instruments | offline | last resort |

Steps 5-7 are guesses. The hit has `match: "fuzzy"` and up to three `alternatives`, the chat trace shows "(closest match; also NUE, NUV)", and
guesses are never saved as aliases.

## Findings
- **Embeddings are the wrong tool for typos.** bge-small on the 15k names: "netflx" -> InflaRx 0.81, "amazn" -> Amaze 0.73, "tesle" ->
  Tema Memory ETF 0.67, "foobarbaz" -> 0.64, while the right answer for "nvdia" scored 0.72. No `min_score` separates them. Character
  similarity gets all of these right in about 10 ms with no index, so it runs first.
- **Embeddings are right for meaning.** "s&p 500 etf" -> VOO 0.96, "bitcoin etf" -> BITB 0.91, "taiwan semiconductor" -> TSM 0.93, "nu bank" ->
  NU 0.81, "jp morgan chase" -> JPM 0.92. Wrong guesses scored 0.82 or lower only for names the dictionary already catches, so 0.80 is the floor.
  The vector is the company name alone; the symbol is not embedded (a 2-4 letter code embeds as noise).
- **Spelling thresholds:** 0.85 similarity for any listing, 0.80 only for companies the SEC ranks (so "tesle" finds Tesla but obscure
  micro-caps need a near-perfect match). Matches within 0.03 of the best are tied, and the better-ranked company wins.
- **Short inputs:** 1-2 letter inputs never get ticker-typo correction (one edit from half the market); 3-4 letters do.
- **Known misses:** "goggle" and "google" (Alphabet's name has no Google in it). A generic word that is spelt like a company ("chips" ->
  Chipmos) can match; `workflow/symbols.py` filters such words (`_NOT_COMPANIES`) before they reach the lookup.
