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
| Dividend income | `portfolio_dividends` |
| The agent's answer: sections and explanations | `focus` / `report` in [src/workflow/portfolio_report.py](../src/workflow/portfolio_report.py) |

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
| Contribution to return | Each day's return split into the holdings' moves (a holding's change / the previous day's portfolio value), scaled by the growth so far, so the contributions add up exactly to the period return | Same purchase-date assumption as the return |
| Dividend income | Last 12 months of payments per share × current shares, by month | Trailing income, not a forecast calendar |
| Sector exposure | Fund sector weights (look-through) and each stock's sector | Bundled funds use coarser sector names than Yahoo, so a mixed portfolio can show both "Other" and specific sectors |
| Geographic exposure | US stocks / International stocks / Bonds / Cash, from the asset type | Funds report no country split; a single stock counts as US |
| Cash | Ticker `CASH` (or a money-market fund such as `SPAXX`) at $1 a share | No separate cash balance field |

Asset type for a ticker outside the bundled instruments comes from its Yahoo fund profile: mostly bonds → bond fund, mostly
cash → cash, a "real estate" category → real estate, a foreign/emerging/world category → international, one sector above
50% → thematic, otherwise a broad stock fund. A ticker with no fund profile is an individual stock.

### The agent's answer

`portfolio_report.focus` reads the question and picks sections: diversification ("diversified", "tech-heavy", "sector",
"allocation"), performance ("doing", "return", "beat", "winners"), risk ("risky", "volatile", "drawdown", "Sharpe"), fees
and dividend income. A question that matches none of them, or asks for an analysis, review, summary or breakdown, gets all
five plus a holdings table (value, weight, gain/loss on cost, contribution to return). The full report is marked
`verbatim` so the synthesizer passes it through unshortened; a focused answer goes through the synthesizer, which answers
the question from it. Every answer ends with the warnings and, when a holding or sector is concentrated, the concentration note.

Each figure comes with a fixed-rule explanation, so the answer is the same without an LLM:

| Section | What it explains |
|---|---|
| Diversification | The score's three parts (holdings 40, asset classes 30, largest sector 30), which asset classes are missing, the breakdowns by asset class, sector and region, and which part holds the score back most |
| Performance | Return and annualized return, points ahead of or behind the S&P 500, which holdings drove it (and whether one produced most of it), best and worst holdings |
| Risk | Risk level against the tolerance limit and how it is built, bonds and cash as a cushion, volatility and largest fall against the S&P 500, that fall in dollars from today's value, Sharpe ratio in words |
| Fees | Weighted expense ratio banded low/typical/high, the cost per $10,000, the holdings with the largest fees |
| Dividend income | Trailing 12-month income and yield, the largest payers, that it is not a forecast |

### Not built yet

- Knowledge-base explanations with citations in the agent's answer (section 3 above): the explanations are fixed rules,
  and concentration risk still has one fixed sentence.
- Investment horizon, goals and target age in the fit check: only risk tolerance is used.
- Transaction history (several purchases or sales of one holding): each holding has one purchase date for all its shares.
