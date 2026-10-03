# Portfolio agent: data needs

Analyzes what the user currently holds, values it with market data, and explains the result in beginner-friendly terms.

## 1. User portfolio data (user session and inputs)

To analyze what the user currently holds.

| Data | Detail |
|---|---|
| Assets and tickers | Stock, ETF or asset symbols (e.g. AAPL, VTI, VXUS, BND) |
| Position details | Number of shares/units held per asset |
| Cost basis | Average purchase price per share, to determine total profit/loss |
| Purchase date | Optional date per holding; performance is measured from it (`portfolio.default_purchase_date` in `config.yaml`, 2026-01-01, when not set) |
| Cash holdings | Cash balance or money market funds |
| User profile and risk appetite | User goals, target age, investment horizon and risk preference, retrieved via the system's state management / conversation history, to evaluate whether the current portfolio matches the user's risk profile |

## 2. Live market data (external APIs)

To value the portfolio accurately in real time. Fetched via the yFinance API or the Alpha Vantage API.

| Data | Detail |
|---|---|
| Real-time / delayed quotes | Current stock and ETF prices, to compute current portfolio value |
| Asset metadata | Sector, industry, exchange and asset class classifications (e.g. US equities, international, bonds, cash) |
| Historical price data | Benchmark returns (e.g. S&P 500 performance), to compare individual stock or overall portfolio performance |

## 3. Financial knowledge base (vector database / RAG)

To provide beginner-friendly, educational explanations alongside the raw numbers. A vector database (FAISS, Chroma DB or
Pinecone) containing 50–100 curated financial articles.

| Data | Detail |
|---|---|
| Investment concepts | Guidelines on asset allocation, diversification rules of thumb and risk balance |
| Jargon explanations | Educational definitions explaining terms like concentration risk, volatility and rebalancing in plain language |
| Citations and attribution data | Source metadata to ground recommendations and include proper educational disclaimers |

## Portfolio report (what is built)

The Portfolio tab's dashboard is one API call, `GET /api/sessions/{id}/portfolio/analysis`, with all maths in Python and no
LLM. The Portfolio agent answers chat questions from the same functions, so the tab and the chat give the same numbers.

| Step | Code |
|---|---|
| Price and classify each holding | `portfolio_instruments` in [src/core/portfolio_data.py](../src/core/portfolio_data.py) |
| Allocation, sectors, geography, risk, fees, gain/loss, today's change, winners and losers | `analyze_portfolio` in [src/core/calculators.py](../src/core/calculators.py) |
| Return, volatility, drawdown, Sharpe, Sortino, comparison with the S&P 500 | `portfolio_history` → `portfolio_performance` |
| Dividend income (Portfolio tab only) | `portfolio_dividends` |

Settings are under `portfolio:` in `config.yaml` (benchmark index, risk-free rate, trading days per year, default purchase date).

### How each metric is computed, and its limits

The app stores current shares, an average cost basis and an optional purchase date per holding. There is no transaction
history, so each holding is treated as bought in full on its purchase date.

| Metric | How it is computed | Limit |
|---|---|---|
| Total return | Current value against cost basis | Only holdings with a cost basis |
| Daily P&L | Shares × today's change from the quote | none |
| Value over time | Each holding's shares × daily close, counted from its purchase date | A purchase shows as a step up in value. Price history reaches back 10 years at most; a holding bought before its own first price (an older purchase, or a recent listing) counts from that first price, without holding the others back |
| Period and annualized return (CAGR), volatility, max drawdown, Sharpe, Sortino | Time-weighted: each day's return is taken over the holdings already owned the day before, so a purchase is not counted as a gain | Under 30 trading days only the period return and drawdown are shown. Differs from total return on cost basis, which uses the price the user paid |
| Comparison with the S&P 500 | The index's return over the same period; the chart line puts the same money into the index on the same dates | Yahoo's fund prices are adjusted for dividends and the index is not, which favours the portfolio slightly |
| Dividend income | Last 12 months of payments per share × current shares, by month | Trailing income, not a forecast calendar |
| Sector exposure | Fund sector weights (look-through) and each stock's sector | Bundled funds use coarser sector names than Yahoo, so a mixed portfolio can show both "Other" and specific sectors |
| Geographic exposure | US stocks / International stocks / Bonds / Cash, from the asset type | Funds report no country split; a single stock counts as US |
| Cash | Ticker `CASH` (or a money-market fund such as `SPAXX`) at $1 a share | No separate cash balance field |

Asset type for a ticker outside the bundled instruments comes from its Yahoo fund profile: mostly bonds → bond fund, mostly
cash → cash, a "real estate" category → real estate, a foreign/emerging/world category → international, one sector above
50% → thematic, otherwise a broad stock fund. A ticker with no fund profile is an individual stock.

### Not built yet

- Knowledge-base explanations with citations in the agent's answer (section 3 above): the agent still uses one fixed
  sentence on concentration risk.
- Investment horizon, goals and target age in the fit check: only risk tolerance is used.
- Transaction history (several purchases or sales of one holding): each holding has one purchase date for all its shares.
