export type Knowledge = "beginner" | "intermediate" | "advanced";
export type Risk = "conservative" | "moderate" | "aggressive";
export type Freshness = "live" | "cached" | "stale" | "sample";

export interface Profile { knowledge_level: Knowledge; risk_tolerance: Risk; horizon_years: number; goals: string[] }
export interface Source { id: string; title: string; url?: string | null }
export interface DataInfo { provider: string; fetched_at: string; freshness: Freshness }
export interface Message {
  id: number; role: "user" | "assistant"; content: string;
  agents: string[]; sources: Source[]; data_info: DataInfo | null; trace: string[]; choices?: string[]; created_at: string;
}
export interface ChatStatus { llm: { enabled: boolean; provider: string | null; model: string | null; last_error?: string | null }; tools: string[] }
export interface Holding { ticker: string; shares: number; cost_basis: number | null; purchase_date?: string | null }
/** default_purchase_date (YYYY-MM-DD): performance counts a holding from here when it has no purchase date. */
export interface Portfolio { holdings: Holding[]; default_purchase_date: string }
export interface Slice { name: string; weight: number }
export interface Analysis {
  empty: boolean; total_value: number; total_gain_loss?: number | null; annual_fee?: number;
  weighted_expense_ratio?: number; diversification_score?: number; effective_holdings?: number;
  risk_level?: number; risk_label?: string; warnings: string[]; skipped: string[];
  allocation?: Slice[]; sectors?: Slice[]; geography?: Slice[];
  total_return_pct?: number | null; day_change?: number | null; day_change_pct?: number | null;
  movers?: { basis: "total" | "day"; winners: Mover[]; losers: Mover[] };
  performance?: Performance; dividends?: Dividends; data_info?: DataInfo;
  holdings: {
    ticker: string; name: string; shares: number; price: number; value: number; weight: number; asset_class: string;
    gain_loss: number | null; gain_loss_pct: number | null; day_change: number | null; day_change_pct: number | null;
  }[];
}
export interface Mover { ticker: string; name: string; change_pct: number; change: number }
/** Since each holding's purchase date (default_start where it has none); time-weighted. Annualized figures are null under ~30 days. */
export interface Performance {
  days: number; start: string | null; end: string | null; risk_free_rate: number; default_start: string | null;
  excluded: string[]; pending: string[]; clamped: string[]; clamped_from: Record<string, string>; assumed: string[];
  points: { date: string; value: number; benchmark: number | null }[];
  period_return: number | null; annualized_return: number | null; volatility: number | null; max_drawdown: number | null;
  sharpe: number | null; sortino: number | null; benchmark_return: number | null; excess_return: number | null;
  benchmark: { symbol: string; name: string };
}
export interface Dividends {
  total: number; yield: number; by_month: { month: string; amount: number }[];
  by_holding: { ticker: string; name: string; amount: number; yield: number }[];
}
export interface Envelope<T> { data: T; provider: string; fetched_at: string; freshness: Freshness }
export interface Quote {
  symbol: string; name: string; price: number; change: number; change_pct: number; volume: number;
  prev_close?: number; day_high?: number; day_low?: number;
}
export interface NewsItem { id: string; title: string; summary: string; publisher: string; url: string; published: string | null; thumbnail: string | null }
export interface HistoryPoint { date: string; close: number; ma50: number | null; ma200: number | null; volume?: number }
export interface IntradayData { symbol: string; prev_close: number; points: IntradayPoint[]; tz?: string }
export interface IntradayPoint { t: string; close: number; volume: number }
export interface LiveQuote extends Envelope<Quote> { spark: number[] }
export interface SymbolInfo { symbol: string; name: string }
export interface GoalInput {
  goal_type: "retirement" | "house" | "education" | "other"; target_amount: number; horizon_years: number;
  current_savings: number; monthly_contribution: number; risk_tolerance: Risk;
}
export interface GoalResult {
  projected_value: number; target: number; on_track: boolean; shortfall: number; required_monthly: number;
  annual_return_assumption: number; suggested_allocation: Record<string, number>;
  series: { year: number; projected: number; contributed: number; target: number }[];
}

export interface Conversation { id: number; title: string; created_at: string; updated_at: string; message_count: number }

/** What the user is looking at, sent with each chat message so "this stock" / "my watchlist" can be resolved. */
export interface ChatView { tab: string; selected: string | null; watchlist: string[] }

/** One node of the LangGraph workflow, as laid out by GET /chat/flow (stage = left-to-right column). */
export interface FlowNode { id: string; label: string; stage: number; kind: "agent" | "step"; description: string }
/** A graph edge; `conditional` ones are picked at run time (router -> agents, verifier -> research | illustrate). */
export interface FlowEdge { from: string; to: string; conditional: boolean }
export type FlowStatus = "ok" | "answered" | "not_found" | "need_info" | "error";
/** Streamed by POST /sessions/{sid}/chat/stream while the graph runs (t = seconds since the turn began). */
export type FlowEvent =
  | { type: "node_start"; node: string; t: number }
  | { type: "node_end"; node: string; t: number; ms: number; status: FlowStatus; detail: string; picked?: string[] };

/** ETF / mutual fund profile (GET /market/fund/{symbol}, yfinance `funds_data`). Fractions are 0–1; null = Yahoo didn't report it. */
export interface Weight { name: string; weight: number }
export interface FundProfile {
  symbol: string; name: string; quote_type: "ETF" | "MUTUALFUND" | string; description: string;
  category: string | null; family: string | null; legal_type: string | null;
  total_assets: number | null; yield: number | null;     // total assets cover every share class of the fund
  operations: { expense_ratio: number | null; category_expense_ratio: number | null; turnover: number | null; category_turnover: number | null };
  asset_classes: Weight[]; sector_weights: Weight[];
  top_holdings: { symbol: string; name: string; weight: number | null }[];
  equity: { pe?: number | null; pb?: number | null; ps?: number | null; pcf?: number | null; category_pe?: number | null; category_pb?: number | null;
            median_market_cap?: number | null; earnings_growth_3y?: number | null };
  bond: { duration?: number | null; maturity?: number | null; credit_quality?: number | null; category_duration?: number | null; category_maturity?: number | null };
  bond_ratings: Weight[]; government_share: number | null;
}

/** Company research (GET /market/stock/{symbol}): corporate actions, key statement lines and earnings data. Fractions are 0–1. */
export interface Statement { periods: string[]; rows: { name: string; values: (number | null)[] }[] }
export interface EstimateRow { period: string; [k: string]: number | string | null }
export interface StockProfile {
  symbol: string; name: string; quote_type: "EQUITY" | "ETF" | "MUTUALFUND" | string;
  sector: string | null; industry: string | null; currency: string | null;
  actions: {
    dividends: { date: string; amount: number | null }[]; dividends_by_year: { year: number; amount: number }[];
    splits: { date: string; ratio: number | null }[]; capital_gains: { date: string; amount: number | null }[];
    shares: { date: string; shares: number }[];
  };
  statements: Record<"income" | "balance" | "cash_flow", Record<"annual" | "quarterly" | "ttm", Statement>>;
  earnings: {
    next: { date?: string | null; eps_low?: number | null; eps_avg?: number | null; eps_high?: number | null;
            revenue_low?: number | null; revenue_avg?: number | null; revenue_high?: number | null;
            ex_dividend_date?: string | null; dividend_date?: string | null };
    dates: { date: string; eps_estimate: number | null; eps_reported: number | null; surprise: number | null }[];
    history: { quarter: string; eps_estimate: number | null; eps_actual: number | null; surprise: number | null }[];
    eps_estimate: EstimateRow[]; revenue_estimate: EstimateRow[]; eps_trend: EstimateRow[]; eps_revisions: EstimateRow[]; growth: EstimateRow[];
  };
}
