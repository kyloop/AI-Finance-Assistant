# Market symbols: currencies, crypto, commodities, rates, indices and sectors

Why: the ticker directory ([ticker-index.md](ticker-index.md)) only knows listed companies and ETFs. A market question either found
nothing or a look-alike: "any news about forex?" resolved "forex" to SHILY (closest match) and "Any" to ANY.BD, and "news of the day"
resolved "day" to DHSB (Day Hagan Smart Buffer ETF). The model that extracts companies had answered "none" correctly; the phrasing-cue
fallback then overruled it.

Code: `src/data/markets.yaml` (the list), `src/rag/markets.py` (lookup, story tags), `scripts/market_symbols.py` (dry run, write,
verify), `src/workflow/symbols.py` (`subjects`: companies, markets, topic, excluded in one model call). Tests: `tests/test_markets.py`.

## Checks against Yahoo (2026-10-26/27, yfinance 1.7.0)

Candidate symbols came from Yahoo's own market pages (finance.yahoo.com/markets/currencies, /commodities, /world-indices, /bonds) and the
saved screener `all_cryptocurrencies_us`, plus the 11 SPDR sector ETFs and ETFs that track each market. 148 symbols checked.

**`Ticker.get_news()` returned no stories for any symbol, even AAPL and ^GSPC.** The app had been answering news only through its
fallback, `yf.Search(symbol).news`. `_yf_news` now asks the search endpoint first and the ticker feed second. Search stories have
no summary, only headline, publisher and time.

Prices: every symbol returned 5-day history except `MOEX.ME` and `^MERV` (dropped).

News through the search endpoint (20 stories asked for per term):

| Group | Works by symbol | Nothing or stale by symbol | Fix |
|---|---|---|---|
| US indices | ^GSPC, ^DJI, ^IXIC (20 stories, all < 24 h), ^RUT, ^VIX | ^NYA, ^XAX, index futures (ES=F …) | quotes only |
| Sectors | all 11 SPDR ETFs (most < 24 h) | | |
| Commodities | GC=F, SI=F, PL=F, PA=F, CL=F, BZ=F, ZC=F, ZS=F, KC=F, SB=F, CT=F, LE=F, HE=F, ZR=F | MGC=F, SIL=F, GF=F, OJ=F; HG=F, NG=F off-topic | copper and gas by name ("copper prices", "natural gas prices"), wheat by name |
| Forex | JPY=X, EURUSD=X, GBPUSD=X, CNY=X, CAD=X, INR=X, IDR=X, SGD=X, CHF=X | crosses (EURGBP=X, EURCHF=X …), ZAR=X, **DX-Y.NYB** | dollar index by name "DXY"; crosses quotes only |
| Rates | ^TNX, ^TYX | ^IRX, ^FVX, Treasury futures | group by name "Treasury yields" |
| World indices | ^FTSE, ^GDAXI, ^FCHI, ^STOXX50E, ^HSI, ^AXJO, ^GSPTSE, ^KS11, ^BVSP, ^BSESN, ^JKSE | 000001.SS, ^MXX, ^NZ50, ^KLSE, ^TWII | Nikkei by name; Shanghai via FXI |
| Crypto | BTC-USD only (12 stories, 4 days old) | ETH-USD, SOL-USD … (0) | **by name**: "Ethereum", "Solana", "XRP" … (20 stories, many < 24 h) |
| ETF backups | GLD, USO, IBIT, CPER current | UUP, FXE, FXY thin and weeks old | kept as `etf` only where the market's own term is weak |

Free text is unreliable: "oil prices", "crypto", "Treasury yields" return good stories, but "forex" returns a CFD-broker press release and
an eye-drug story. Short symbols match words: SHY → "just shy of a record", ^STI → an FDA story about an STI drug. So each symbol has its
own checked `news` term (`null` = quotes only), and every group lists its own.

`python -m scripts.market_symbols --check-news` repeats the news check for every term in the list; 84 of 85 returned stories
("Shanghai Composite" did not, now `null` with FXI as backup).

## The list (`src/data/markets.yaml`)

96 symbols in 7 groups: forex 25, crypto 12, commodities 20, rates 4, US indices 9, world indices 15, sectors 11. Per symbol: Yahoo
`symbol`, display `name`, `aliases` (what users write; embedded), `codes` (joined forms such as "eurusd", exact match only, they embed
badly), `news` term, backup `etf`. Hand-written and reviewed in git; no refresh job (these symbols rarely change).

Nine aliases are also listed tickers; the market wins, and `$BTC` / "BTC stock" still reach the ticker:
btc (Grayscale Bitcoin Mini Trust), eth (Grayscale Ethereum Mini), XRP (Bitwise XRP ETF), Tron and trx (Tron Inc., TRX Gold), gold
(Gold.com), wti (W&T Offshore), corn (Teucrium Corn Fund), djia (Global X Dow 30 Covered Call ETF).

## In Qdrant (`finnie_symbols`, Qdrant Cloud)

Same collection as the companies, written by upsert (never by rebuilding it, so the 15,137 company points and the running app are
untouched):

- one `asset_type: market` point per distinct name/alias (233), vector = that text, payload `{group, symbol, name, alias, news, etf}`;
- one `asset_type: market_group` point per group (7), vector = label + aliases, so "forex" itself matches;
- ids `uuid5("market:<symbol>:<normalised text>")`, never a company id (XLK is both a sector and an ETF);
- payload indexes on `asset_type`, `symbol`, `group`. `search_names` (company lookup) now filters to stocks and ETFs.

`--write` read every point back: 240 points, 0 differences. Live searches:

| Query | Result | Score |
|---|---|---|
| USD---JPY | JPY=X | 0.974 |
| Europe vs USD | EURUSD=X | 0.922 |
| japanese yen | JPY=X | 1.000 |
| etherium | ETH-USD | 0.801 (also caught earlier by spelling) |
| forex | the forex group | 0.836 |
| gold price, crude oil, bitcoin, tech sector | GC=F, CL=F, BTC-USD, XLK | 1.000 |
| 10 year treasury | ^TNX | 0.926 |
| Palantir, NVIDIA (companies unaffected) | PLTR, NVDA | 0.882, 0.897 |

## How a question finds its subject

`symbols.subjects` makes one model call returning `{companies, markets, topic, excluded}`. **An empty answer is final**: the
phrasing cues only run when there is no model or its reply is unusable. A market name the model lists as a company ("gold") is moved
to markets. Markets resolve through `markets.lookup`: exact (case and punctuation ignored, "USD---JPY" = "usdjpy"), then spelling
(5+ letters), then the Qdrant market points (`min_score` 0.80, and every hit within `score_margin` of the best must be the same market,
or no guess). Without a model, `markets.in_text` scans for names and aliases (longest first) and capitalised codes; everyday words
("sugar", "Stellar") count only when capitalised mid-sentence, and a short question about a market's state ("how is the yen doing
today?") goes to the market agent instead of Q&A.

- **Router** puts them in `entities["markets"]`, `["topic"]`, `["excluded"]`; a follow-up carries the previous answer's markets.
- **Market agent** quotes a market's symbol, or a group's first four; prices print in their unit (EUR/USD 1.1218, a yield as %,
  an index in points). `_yf_quote` keeps 4 decimals below 10.
- **News agent** fetches companies by ticker and markets by their `news` terms (up to 4 feeds). The model's topic decides live feed
  (`""`) or search, and is the search text. Stored stories are tagged with their fetch term and `market:<group>`, so a market search
  filters on the tag. When the index and Yahoo give fewer than `news_index.web_min_stories` (3) relevant stories, Tavily's news search
  (`topic: news`, `days`) adds recent articles with their excerpts, and they are indexed for the next question.
- **Background poll** fetches a recently asked market by its news term (DXY for DX-Y.NYB; none for quote-only symbols), and skips
  ^GSPC/^IXIC/^DJI (already in the market feed).
- **Proofreader** turns "not X, just Y" into the question for Y. The rewrite may drop only what the user ruled out, and may not
  bring it back or name anything new.

## Live end-to-end checks (2026-10-27, real LLM, Yahoo, Qdrant Cloud, Tavily)

| Question | Path | Answer |
|---|---|---|
| any news about forex? | markets: currencies → 4 forex feeds | "Asian currencies mixed as dollar holds firm…", "China's yuan climbs to fresh 4-year high…" |
| I am not looking for DHSB news. I just want earler news of today | proofread → "What were the market headlines earlier today?" → market feed | today's US market headlines, no DHSB |
| how is gold doing today? | markets: Gold (GC=F) → get_quote, get_performance | $4,017.60, −0.31% |
| What is Europe vs USD today? | markets: EUR/USD → get_quote | 1.1171 |
| crypto news on ETF flows | markets: crypto, topic "ETF flows" → 56 Yahoo stories (45 new) → < 3 relevant → Tavily +5 | Bitcoin ETF flows research, ETF flow trackers |

## Known limits

- Without a model, "what's been said about gold…" is not routed to news (the keyword router expects "what has been said").
- The live feed ignores "today" / "earlier" (it shows the newest stories); time windows apply to the stored-news search only.
- Yahoo search stories have no summary; Tavily stories do.
