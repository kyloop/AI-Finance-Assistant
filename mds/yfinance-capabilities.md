# yfinance library reference

What the `yfinance` library (the app's Yahoo Finance data source) can fetch, **checked against the installed version (1.7.0) on 2026-10-02**: the member lists
below come from inspecting the library, and every row marked ✅ was called live against Yahoo and returned data that day.
Rows without a mark exist in the library but were not called.

yfinance is an unofficial, keyless scraper of Yahoo Finance endpoints. Fields change without notice, requests are
rate-limited, and calls sometimes return empty DataFrames or `None`. Cache results and handle empties.

## Currently used in this repo

| What | Where |
|---|---|
| `yf.Ticker(symbol)`: `fast_info` (quote), `history` (daily and intraday bars), `info` (name, industry key) | `src/core/market_service.py` (`_yf_quote`, `_yf_history`, `_yf_intraday`, `_yf_name`, `_yf_peers`) |
| `Ticker.get_news`, `yf.Search(...).news` | `market_service.py` (`_yf_news`, `_search_news`): the News agent and the news index |
| `yf.Search(...).quotes` | `market_service.py` (`_yf_resolve`): company name → ticker |
| `yf.Industry(key).top_companies` | `market_service.py` (`_yf_peers`): industry peers for "news from the same sector" |
| `yf.AsyncWebSocket` | `src/core/live_stream.py`: live prices on the Live tab |
| `Ticker.funds_data` (all fields) + `info` (`totalAssets`, `yield`) | `market_service.py` (`_yf_fund`, `_fund_payload`): the Research tab's fund profiles |
| `dividends`, `splits`, `capital_gains`, `get_shares_full`; `income_stmt` / `balance_sheet` / `cash_flow` (annual, quarterly, TTM); `calendar`, `get_earnings_dates`, `earnings_history`, `earnings_estimate`, `revenue_estimate`, `eps_trend`, `eps_revisions`, `growth_estimates` | `market_service.py` (`_yf_stock`, `_stock_payload`): the Research tab's Stock research |

Everything below is available but not yet wired in.

## Top-level API (1.7.0)

`download`, `Ticker`, `Tickers`, `Search`, `Lookup`, `Market`, `MarketRegion`, `Sector`, `Industry`, `Calendars`,
`screen`, `EquityQuery`, `ETFQuery`, `FundQuery`, `PREDEFINED_SCREENER_QUERIES`, `WebSocket`, `AsyncWebSocket`, `Auth`,
`config`, `set_config`, `set_tz_cache_location`, `enable_debug_mode`.

## Per-ticker: `yf.Ticker(symbol)`

98 public members; each property also has a `get_…()` method.

| Group | Members | Live check |
|---|---|---|
| Prices | `history(period, interval, start, end)`, `fast_info`, `info` (~150 fields: sector, P/E, beta, dividend yield, margins…), `history_metadata`, `live()` (streaming) | ✅ `history(1y)` 252 daily bars; ✅ `info` (trailing P/E, dividend yield, market cap, sector, beta) |
| Valuation | `valuation`: market cap, enterprise value, trailing and forward P/E… by quarter | ✅ AAPL, 9 measures × 6 dates |
| Corporate actions (in use: Stock research) | `actions`, `dividends`, `splits`, `capital_gains` (funds) | ✅ `dividends`, `splits`, `capital_gains` (empty for VOO and VFIAX: index funds rarely distribute) |
| Financial statements (in use: Stock research) | `income_stmt`, `balance_sheet`, `cash_flow` (annual), `quarterly_…`, `ttm_…` (income and cash flow only); `shares`, `get_shares_full()` | ✅ all three, annual (4 years), quarterly (5–6) and TTM; ✅ `get_shares_full`; ❌ **`shares` raises `YFNotImplementedError` in 1.7.0** |
| Earnings and estimates (in use: Stock research) | `earnings_dates`, `calendar`, `earnings_estimate`, `revenue_estimate`, `earnings_history`, `eps_trend`, `eps_revisions`, `growth_estimates` | ✅ all eight (AAPL, MSFT, KO) |
| Analysts | `recommendations`, `recommendations_summary`, `upgrades_downgrades`, `analyst_price_targets` | ✅ price targets (low/mean/median/high), ✅ buy/hold/sell counts |
| Ownership | `major_holders`, `institutional_holders`, `mutualfund_holders`, `insider_transactions`, `insider_purchases`, `insider_roster_holders` | |
| **Funds and ETFs** (in use: Research tab) | `funds_data`: `top_holdings`, `sector_weightings`, `asset_classes`, `equity_holdings`, `bond_holdings`, `bond_ratings`, `fund_overview`, `fund_operations`, `description` | ✅ VOO top 10 holdings with weights, ✅ sector weights, ✅ category and family, ✅ expense ratio, turnover and net assets vs category average |
| Options | `options` (expiry dates), `option_chain(date)` | |
| Other | `news`, `sec_filings`, `sustainability` (ESG), `isin` | ✅ `news` (in use) |

Options limits (from the library's behaviour, not re-checked): snapshot only, quotes typically ~15 min delayed, one
expiry per call, no Greeks (compute from `impliedVolatility`, which is unreliable for illiquid strikes), `openInterest`
updates daily, no historical chains, and the WebSocket doesn't carry option contracts.

## Multi-ticker and lookup

| Function | Purpose | Live check |
|---|---|---|
| `yf.download(tickers, period, interval)` | Batch history in one call; much faster than looping `Ticker` | ✅ VOO + QQQ, 1 month |
| `yf.Tickers("VOO QQQ")` | Batch wrapper | |
| `yf.Search(query)` | `.quotes`, `.news`, `.lists`, `.research`, `.nav` | ✅ (in use) |
| `yf.Lookup(query)` | Tickers by type: `.stock`, `.etf`, `.mutualfund`, `.index`, `.future`, `.currency`, `.cryptocurrency` | ✅ `Lookup("vanguard").etf`: VOO, VGT, VTI, VXUS… |

## Market, sectors and calendars

| Function | Returns | Live check |
|---|---|---|
| `yf.Market("US")` | `.status` (open/closed, hours), `.summary` (S&P 500, Dow, Nasdaq, Russell, VIX, gold…) | ✅ both |
| `yf.Sector(key)` | `.overview`, `.industries`, `.top_companies`, **`.top_etfs`**, **`.top_mutual_funds`**, `.research_reports` | ✅ technology: top ETFs QQQ, VGT, XLK, QQQM, SMH…; 50 top companies; 12 industries |
| `yf.Industry(key)` | `.overview`, `.top_companies`, `.top_growth_companies`, `.top_performing_companies` (YTD return, price, target), `.research_reports` | ✅ semiconductors top performers |
| `yf.Calendars()` | `.earnings_calendar`, `.economic_events_calendar` (CPI, retail sales… actual vs expected), `.ipo_info_calendar`, `.splits_calendar` | ✅ earnings, ✅ economic events |

## Screener: `yf.screen(query, sortField, sortAsc, size)`

A filtered, sorted query over Yahoo's whole universe (not a UI screen). Each result carries the quote plus, for funds,
`netAssets`, `netExpenseRatio`, `ytdReturn`, `fiftyTwoWeekChangePercent` (price change only, no dividends) and
`annualReturnNavY3` / `annualReturnNavY5`; for stocks, `marketCap`, P/E and the like.

**Predefined** (`PREDEFINED_SCREENER_QUERIES`):
- Stocks: `day_gainers`, `day_losers`, `most_actives`, `most_shorted_stocks`, `aggressive_small_caps`, `small_cap_gainers`,
  `growth_technology_stocks`, `undervalued_growth_stocks`, `undervalued_large_caps`
- ETFs: `top_etfs_us` (4–5 star Morningstar rating, sorted by today's % change, so it skews to whatever is moving),
  `top_performing_etfs` (same rating filter, sorted by **lowest expense ratio**), `technology_etfs`, `bond_etfs`
- Mutual funds: `top_mutual_funds`, `solid_large_growth_funds`, `solid_midcap_growth_funds`, `conservative_foreign_funds`,
  `high_yield_bond`, `portfolio_anchors`

✅ `top_etfs_us`, ✅ `top_performing_etfs`.

**Custom** queries:
- `ETFQuery`: filter on `exchange`, `categoryname` (Morningstar category: Large Blend, Large Growth, Mid-Cap Value,
  Foreign Large Blend…), `fundfamilyname`; sort or filter on fund net assets, fees, trailing and historical performance,
  Morningstar rating. ✅ US ETFs sorted by `fundnetassets`: VTI, VOO, IVV, SPY, VXUS, QQQ, BND, VUG.
- `EquityQuery`: filter on `region`, `exchange`, `sector`, `industry`, `peer_group`, plus ~90 numeric fields (price,
  valuation, profitability, leverage, statements, short interest, ESG). ✅ US stocks by `intradaymarketcap` bands
  (large > $10B, mid $2–10B). The raw result includes over-the-counter foreign listings, so filter by exchange.
- `FundQuery`: mutual funds (filter on `exchange` only).

### Quirks in `funds_data` (seen 2026-10-02, handled in `_fund_payload`)
- `equity_holdings` valuation ratios are **inverted**: VOO's "Price/Earnings" is 0.04033 (1/0.04033 = 24.8, the S&P 500's
  P/E); P/B 0.189 → 5.3, P/S 0.273 → 3.7, P/CF 0.053 → 19. Bond funds report 0 for all four.
- `fund_operations` "Total Net Assets" is unreliable: VOO's equals its median market cap (514,320.12), BND's is 0, and the
  "Category Average" column repeats the fund's own value. `info["totalAssets"]` is consistent (BND $399B, QQQ $489B) but
  covers every share class (VOO and VFIAX both report $1.76T).
- `bond_ratings["us_government"]` is the share in government bonds, not a rating bucket (BND: AA 72.5% and government 51.8%).
- `fund_operations` turnover of exactly 0 (QQQ) means not reported.
- `Median Market Cap` is in $ millions and `3 Year Earnings Growth` in percent.
- `top_holdings` can raise inside yfinance for mutual funds; `sector_weightings` and `top_holdings` are empty for bond funds.
- A stock has no fund data (`YFDataException: No Fund data found`); `info["quoteType"]` tells a stock from a missing fund.
- `info` also has `fundInceptionDate` (wrong: VOO and BND show the same 2016 date) and returns in mixed units (`ytdReturn`
  in percent, `threeYearAverageReturn` as a fraction), so neither is used yet.

### Quirks in the stock data (seen 2026-10-02, handled in `_stock_payload`)
- `get_earnings_dates(limit=12)` ignores `limit` (25 rows for AAPL); the first row is the upcoming report, with no reported EPS.
- The earnings surprise is in **percent** in `earnings_dates` (`Surprise(%)` 6.74) but a **fraction** in
  `earnings_history` (`surprisePercent` 0.0674).
- `eps_revisions` mixes capitalisation: `upLast7days`, `upLast30days`, `downLast30days`, but `downLast7Days`.
- `calendar` returns `datetime.date` objects and a list for "Earnings Date".
- `get_shares_full` returns several reports per day; keep the last per quarter.
- Statements, `calendar` and the estimates are empty or 404 for funds (`No fundamentals data found for symbol: VOO`).
- About 15 requests per stock: ~12 s sequentially for AAPL on a first load, 4–9 s in parallel. Cache it.

## Streaming

`yf.WebSocket` / `yf.AsyncWebSocket` (and `Ticker.live()`): push prices for equities, ETFs, crypto and FX. No option
contracts.

## Candidate additions for this app

| Data | Would serve |
|---|---|
| ETF/fund screens (largest by assets, by Morningstar category, presets) | "top / popular / large-cap / mid-cap ETFs" in chat; a Research tab |
| Stock screens by market-cap band, sector | "large-cap / mid-cap stocks" |
| `funds_data` (holdings, sector weights, expense ratio vs category) | **done for the Research tab**; still to do: the chat's agents, and Portfolio look-through with live data instead of the sample `sector_breakdown` |
| `history` / `download` returns over 1M / 1Y / 5Y | "how has X performed"; Goal planning grounded in real index returns |
| `Sector.top_etfs` / `top_companies` / `Industry.top_performing_companies` | "best tech ETFs", sector questions |
| `Market.summary` / `.status` | "how is the market today", market open/closed |
| `info` / `valuation` / `calendar` / `earnings_dates` | P/E, dividend yield, next earnings for a named stock |
| `analyst_price_targets` / `recommendations_summary` | context only; framed carefully, since this is an education app and must not read as advice |
| `Calendars().economic_events_calendar` | "when is the next CPI report" |

New data types plug in through `PROVIDERS` and `get_market_data` in `src/core/market_service.py` (cached in the
`market_cache` table).

## Alternatives for what yfinance lacks

Not re-checked on 2026-10-02.

| Need | Option |
|---|---|
| Real-time options, Greeks, option streaming | `schwabdev` (Schwab API): needs a brokerage account, OAuth with ~7-day refresh token expiry, ~120 req/min |
| Historical options | Massive (formerly Polygon.io): paid tiers. The free tier is limited to ~5 req/min and mostly end-of-day data; confirm what it covers before relying on it |
| Historical chains on a free setup | Snapshot yfinance chains on a schedule into your own database |

Neither Schwab nor yfinance provides historical option data.
