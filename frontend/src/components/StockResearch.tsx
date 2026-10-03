import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { Envelope, EstimateRow, Statement, StockProfile } from "../types";
import { COLORS, ErrorBanner, FreshnessBadge } from "./common";

const EXAMPLES = ["AAPL", "MSFT", "NVDA", "KO", "JNJ"];
const SECTIONS = ["Earnings & estimates", "Financial statements", "Dividends & splits"] as const;
type Section = (typeof SECTIONS)[number];
const STATEMENTS = { income: "Income statement", balance: "Balance sheet", cash_flow: "Cash flow" } as const;
type Kind = keyof typeof STATEMENTS;
type Period = "annual" | "quarterly" | "ttm";
const PERIODS: Record<Period, string> = { annual: "Annual", quarterly: "Quarterly", ttm: "Trailing 12 months" };
const CHART_ROWS: Record<Kind, [string, string]> = {
  income: ["Total Revenue", "Net Income"], balance: ["Total Assets", "Total Liabilities Net Minority Interest"], cash_flow: ["Operating Cash Flow", "Free Cash Flow"],
};
/** One-line meaning of each statement line, shown as a tooltip and under the table. */
const LINE_HELP: Record<string, string> = {
  "Total Revenue": "All the money taken in from selling products and services.",
  "Cost Of Revenue": "What it cost to make what was sold.",
  "Gross Profit": "Revenue minus the cost of making it.",
  "Operating Expense": "Running costs: research, marketing, salaries, offices.",
  "Operating Income": "Profit from the core business, before interest and tax.",
  "Pretax Income": "Profit before income tax.",
  "Tax Provision": "Income tax for the period.",
  "Net Income": "The bottom line: profit after every cost and tax.",
  "EBITDA": "Earnings before interest, tax, depreciation and amortisation: a rough measure of cash profit.",
  "Diluted EPS": "Net income per share, counting shares that options could still create.",
  "Diluted Average Shares": "Average number of shares, including those options could create.",
  "Total Assets": "Everything the company owns.",
  "Current Assets": "Assets that turn into cash within a year (cash, receivables, inventory).",
  "Cash And Cash Equivalents": "Cash and very short-term investments.",
  "Total Liabilities Net Minority Interest": "Everything the company owes.",
  "Current Liabilities": "What it must pay within a year.",
  "Total Debt": "Borrowed money (loans and bonds).",
  "Net Debt": "Debt minus cash; negative means more cash than debt.",
  "Stockholders Equity": "Assets minus liabilities: what belongs to shareholders.",
  "Retained Earnings": "Profits kept in the business over the years instead of paid out.",
  "Working Capital": "Current assets minus current liabilities: short-term breathing room.",
  "Ordinary Shares Number": "Shares outstanding at the date of the balance sheet.",
  "Operating Cash Flow": "Cash the business itself generated.",
  "Capital Expenditure": "Cash spent on buildings, equipment and other long-term assets.",
  "Free Cash Flow": "Operating cash flow minus capital expenditure: cash left over for dividends, buybacks or debt.",
  "Investing Cash Flow": "Cash spent on or received from investments and acquisitions.",
  "Financing Cash Flow": "Cash from or to lenders and shareholders (borrowing, repayments, dividends, buybacks).",
  "Cash Dividends Paid": "Dividends paid to shareholders.",
  "Repurchase Of Capital Stock": "Cash spent buying back the company's own shares.",
  "End Cash Position": "Cash at the end of the period.",
};

const pct = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
const signed = (v: number | null | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const eps = (v: number | null | undefined) => (v == null ? "—" : `$${v.toFixed(2)}`);
const fmtDate = (d: string | null | undefined) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—");
function big(v: number | null | undefined, cur = "USD"): string {
  if (v == null) return "—";
  const sym = cur === "USD" ? "$" : `${cur} `;
  const a = Math.abs(v), sign = v < 0 ? "−" : "";
  const [n, u] = a >= 1e12 ? [a / 1e12, "T"] : a >= 1e9 ? [a / 1e9, "B"] : a >= 1e6 ? [a / 1e6, "M"] : [a, ""];
  return `${sign}${sym}${n.toFixed(n >= 100 ? 0 : 1)}${u}`;
}
const count = (v: number | null | undefined) => (v == null ? "—" : v >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v.toLocaleString());
const cell = (name: string, v: number | null, cur: string) =>
  name.endsWith("EPS") ? eps(v) : name.includes("Shares") ? count(v) : big(v, cur);

/** Company research: earnings and analyst estimates, the key lines of the financial statements, and dividends / splits. */
export default function StockResearch({ onAsk }: { onAsk: (q: string) => void }) {
  const [symbol, setSymbol] = useState("AAPL");
  const [input, setInput] = useState("AAPL");
  const [env, setEnv] = useState<Envelope<StockProfile> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [section, setSection] = useState<Section>("Earnings & estimates");

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true); setError(null);
    api.stock(symbol)
      .then((e) => { if (alive) setEnv(e); })
      .catch((e) => { if (alive) { setError(e.message); setEnv(null); } })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [symbol]);

  const look = (s: string) => { const v = s.trim().toUpperCase(); setInput(v); setSymbol(v); };
  const s = env?.data;
  const company = s?.quote_type === "EQUITY";
  const shown = company ? section : "Dividends & splits";            // a fund has no statements or estimates
  return (
    <div>
      <h2>Stock research</h2>
      <p className="muted small">How a company is doing: its earnings and what analysts expect, its financial statements, and what it pays shareholders.</p>
      <form className="row" onSubmit={(e) => { e.preventDefault(); look(input); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Stock ticker, e.g. AAPL" aria-label="Stock ticker" />
        <button disabled={loading}>{loading ? "Loading…" : "Look up"}</button>
      </form>
      <div className="row chips" aria-label="Examples">
        <span className="muted small">Try:</span>
        {EXAMPLES.map((x) => <button key={x} type="button" className="secondary chip" aria-pressed={x === symbol} onClick={() => look(x)}>{x}</button>)}
      </div>
      {loading && !env && <p className="muted small">Loading company data from Yahoo Finance (the first look-up can take a few seconds)…</p>}
      <ErrorBanner message={error} />
      {s && env && (
        <>
          <div className="card wide">
            <div className="muted small">
              {[company ? "Stock" : s.quote_type === "MUTUALFUND" ? "Mutual fund" : s.quote_type, s.sector, s.industry].filter(Boolean).join(" · ")}{" "}
              <FreshnessBadge freshness={env.freshness} provider={env.provider} fetchedAt={env.fetched_at} />
            </div>
            <div className="big">{s.name} <span className="muted">({s.symbol})</span></div>
            {!company && <p className="small">{s.symbol} is a fund, so it has no financial statements or earnings estimates of its own. Its dividends are below; see <b>Fund research</b> for what it holds.</p>}
            <button className="secondary" onClick={() => onAsk(`Can you explain ${s.symbol}'s latest earnings and financial health in simple terms?`)}>Ask Finnie about {s.symbol}</button>
          </div>
          {company && (
            <nav className="row pills" aria-label="Section">
              {SECTIONS.map((x) => <button key={x} className={x === section ? "chip active" : "secondary chip"} aria-pressed={x === section} onClick={() => setSection(x)}>{x}</button>)}
            </nav>
          )}
          {shown === "Earnings & estimates" && <Earnings s={s} />}
          {shown === "Financial statements" && <Statements s={s} />}
          {shown === "Dividends & splits" && <Actions s={s} />}
          <p className="muted small">Source: Yahoo Finance via yfinance, refreshed every 6 hours. "—" means Yahoo doesn't report it. Analyst estimates are opinions about the future, not facts or advice.</p>
        </>
      )}
    </div>
  );
}

function Earnings({ s }: { s: StockProfile }) {
  const e = s.earnings, n = e.next, cur = s.currency ?? "USD";
  const reported = e.dates.filter((d) => d.eps_reported != null);
  const beats = reported.filter((d) => (d.surprise ?? 0) > 0).length;
  return (
    <>
      <div className="cards facts">
        <div className="card"><div className="muted small">Next earnings report</div><div className="big">{fmtDate(n.date)}</div>
          <div className="muted small fact-help">When the company next reports its quarterly results.</div></div>
        <div className="card"><div className="muted small">Expected EPS this quarter</div><div className="big">{eps(n.eps_avg)}</div>
          <div className="muted small">range {eps(n.eps_low)} – {eps(n.eps_high)}</div>
          <div className="muted small fact-help">Analysts' average guess of earnings per share.</div></div>
        <div className="card"><div className="muted small">Expected revenue this quarter</div><div className="big">{big(n.revenue_avg, cur)}</div>
          <div className="muted small">range {big(n.revenue_low, cur)} – {big(n.revenue_high, cur)}</div></div>
        <div className="card"><div className="muted small">Next dividend</div><div className="big">{fmtDate(n.dividend_date)}</div>
          <div className="muted small">ex-dividend {fmtDate(n.ex_dividend_date)}</div>
          <div className="muted small fact-help">You must own the shares before the ex-dividend date to receive it.</div></div>
      </div>

      <div className="research-grid">
        {e.dates.length > 0 && (
          <div className="card"><h3>Earnings track record</h3>
            <div className="table-scroll"><table className="grid"><thead><tr><th>Report date</th><th className="right">Estimate</th><th className="right">Reported</th><th className="right">Surprise</th></tr></thead>
              <tbody>{e.dates.map((d) => (
                <tr key={d.date}><td>{fmtDate(d.date)}{d.eps_reported == null && <span className="muted small"> (upcoming)</span>}</td>
                  <td className="right">{eps(d.eps_estimate)}</td><td className="right">{eps(d.eps_reported)}</td>
                  <td className={`right ${d.surprise == null ? "" : d.surprise >= 0 ? "up" : "down"}`}>{signed(d.surprise)}</td></tr>))}</tbody></table></div>
            {reported.length > 0 && <p className="muted small">Beat the estimate in {beats} of the last {reported.length} reports. A "beat" means earnings per share came in above what analysts expected.</p>}</div>
        )}
        <EstimateTable title="Earnings per share (EPS) estimates" rows={e.eps_estimate} money={eps}
          help="What analysts expect earnings per share to be, with the spread of their guesses and the growth versus a year earlier." />
        <EstimateTable title="Revenue estimates" rows={e.revenue_estimate} money={(v) => big(v, cur)}
          help="What analysts expect the company to sell, and the growth versus a year earlier." />
        {e.eps_trend.length > 0 && (
          <div className="card"><h3>How the EPS estimate has moved</h3>
            <div className="table-scroll"><table className="grid"><thead><tr><th>Period</th><th className="right">Now</th><th className="right">7 days ago</th><th className="right">30 days</th><th className="right">90 days</th></tr></thead>
              <tbody>{e.eps_trend.map((r) => <tr key={r.period}><td>{r.period}</td><td className="right">{eps(r.current as number)}</td>
                <td className="right">{eps(r.d7 as number)}</td><td className="right">{eps(r.d30 as number)}</td><td className="right">{eps(r.d90 as number)}</td></tr>)}</tbody></table></div>
            <p className="muted small">A rising estimate means analysts have become more optimistic about earnings; a falling one, less.</p></div>
        )}
        {e.eps_revisions.length > 0 && (
          <div className="card"><h3>Analyst revisions</h3>
            <div className="table-scroll"><table className="grid"><thead><tr><th>Period</th><th className="right">Up (7d)</th><th className="right">Up (30d)</th><th className="right">Down (7d)</th><th className="right">Down (30d)</th></tr></thead>
              <tbody>{e.eps_revisions.map((r) => <tr key={r.period}><td>{r.period}</td><td className="right">{r.up_7d ?? "—"}</td><td className="right">{r.up_30d ?? "—"}</td>
                <td className="right">{r.down_7d ?? "—"}</td><td className="right">{r.down_30d ?? "—"}</td></tr>)}</tbody></table></div>
            <p className="muted small">How many analysts raised or cut their earnings estimate recently.</p></div>
        )}
        {e.growth.length > 0 && (
          <div className="card"><h3>Expected growth vs the S&P 500</h3>
            <div className="table-scroll"><table className="grid"><thead><tr><th>Period</th><th className="right">{s.symbol}</th><th className="right">S&P 500</th></tr></thead>
              <tbody>{e.growth.map((r) => <tr key={r.period}><td>{r.period}</td><td className="right">{pct(r.stock as number)}</td><td className="right">{pct(r.index as number)}</td></tr>)}</tbody></table></div>
            <p className="muted small">Expected earnings growth for the company next to the market as a whole.</p></div>
        )}
      </div>
    </>
  );
}

function EstimateTable({ title, rows, money, help }: { title: string; rows: EstimateRow[]; money: (v: number | null) => string; help: string }) {
  if (!rows.length) return null;
  const n = (r: EstimateRow, k: string) => (typeof r[k] === "number" ? (r[k] as number) : null);
  return (
    <div className="card"><h3>{title}</h3>
      <div className="table-scroll"><table className="grid"><thead><tr><th>Period</th><th className="right">Average</th><th className="right">Range</th><th className="right">Year ago</th><th className="right">Growth</th><th className="right">Analysts</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.period}><td>{r.period}</td><td className="right">{money(n(r, "avg"))}</td>
            <td className="right">{money(n(r, "low"))} – {money(n(r, "high"))}</td><td className="right">{money(n(r, "year_ago"))}</td>
            <td className="right">{signed(n(r, "growth"))}</td><td className="right">{n(r, "analysts") ?? "—"}</td></tr>))}</tbody></table></div>
      <p className="muted small">{help}</p></div>
  );
}

function Statements({ s }: { s: StockProfile }) {
  const [kind, setKind] = useState<Kind>("income");
  const [period, setPeriod] = useState<Period>("annual");
  const cur = s.currency ?? "USD";
  const st: Statement = s.statements[kind][period];
  const usable = (p: Period) => s.statements[kind][p].rows.length > 0;
  const shownPeriod = usable(period) ? period : (["annual", "quarterly", "ttm"] as Period[]).find(usable) ?? period;
  const data = s.statements[kind][shownPeriod];
  const [a, b] = CHART_ROWS[kind];
  const chart = data.periods.map((p, i) => ({ period: p.slice(0, shownPeriod === "annual" ? 4 : 7),
    [a]: data.rows.find((r) => r.name === a)?.values[i] ?? null, [b]: data.rows.find((r) => r.name === b)?.values[i] ?? null })).reverse();
  return (
    <div className="card wide">
      <div className="row">
        {(Object.keys(STATEMENTS) as Kind[]).map((k) => <button key={k} className={k === kind ? "chip active" : "secondary chip"} aria-pressed={k === kind} onClick={() => setKind(k)}>{STATEMENTS[k]}</button>)}
        <span className="spacer" />
        {(Object.keys(PERIODS) as Period[]).map((p) => <button key={p} className={p === shownPeriod ? "chip active" : "secondary chip"} aria-pressed={p === shownPeriod}
          disabled={!usable(p)} title={usable(p) ? "" : `Yahoo has no ${PERIODS[p].toLowerCase()} ${STATEMENTS[kind].toLowerCase()}`} onClick={() => setPeriod(p)}>{PERIODS[p]}</button>)}
      </div>
      {data.rows.length === 0 ? <p className="muted small">Yahoo has no {STATEMENTS[kind].toLowerCase()} for {s.symbol}.</p> : (
        <>
          {chart.length > 1 && (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="period" /><YAxis tickFormatter={(v) => big(v, cur)} width={70} />
                <Tooltip formatter={(v) => big(v as number, cur)} /><Legend />
                <Bar dataKey={a} fill={COLORS[0]} name={a.replace(" Net Minority Interest", "")} /><Bar dataKey={b} fill={COLORS[1]} name={b.replace(" Net Minority Interest", "")} />
              </BarChart>
            </ResponsiveContainer>
          )}
          <div className="table-scroll">
            <table className="grid statement"><thead><tr><th>{s.currency ?? ""}</th>{data.periods.map((p) => <th key={p} className="right">{shownPeriod === "ttm" ? `12 months to ${p}` : p}</th>)}</tr></thead>
              <tbody>{data.rows.map((r) => (
                <tr key={r.name}><td title={LINE_HELP[r.name] ?? ""}>{r.name.replace(" Net Minority Interest", "")}{LINE_HELP[r.name] && <span className="help-dot" aria-hidden="true">?</span>}</td>
                  {r.values.map((v, i) => <td key={i} className={`right ${v != null && v < 0 ? "down" : ""}`}>{cell(r.name, v, cur)}</td>)}</tr>))}</tbody></table>
          </div>
          <p className="muted small">Key lines only; hover a line for what it means. {kind === "income" ? "The income statement shows what the company earned and spent over a period." : kind === "balance" ? "The balance sheet is a snapshot of what the company owns and owes on one date." : "The cash flow statement follows the actual cash in and out, which profits alone can hide."}</p>
        </>
      )}
      {st.rows.length === 0 && shownPeriod !== period && <p className="muted small">Showing {PERIODS[shownPeriod].toLowerCase()}: Yahoo has no {PERIODS[period].toLowerCase()} figures for this statement.</p>}
    </div>
  );
}

function Actions({ s }: { s: StockProfile }) {
  const a = s.actions;
  const thisYear = new Date().getFullYear();
  const byYear = a.dividends_by_year.map((d) => ({ year: d.year === thisYear ? `${d.year} (so far)` : String(d.year), amount: d.amount }));
  const shares = a.shares.map((x) => ({ date: x.date.slice(0, 7), shares: x.shares }));
  const change = a.shares.length > 1 ? a.shares[a.shares.length - 1].shares / a.shares[0].shares - 1 : null;
  const split = (r: number | null) => (r == null ? "—" : r >= 1 ? `${r}-for-1` : `1-for-${Math.round(1 / r)} (reverse)`);
  return (
    <div className="research-grid">
      <div className="card"><h3>Dividends per share</h3>
        {byYear.length === 0 ? <p className="muted small">{s.symbol} hasn't paid dividends in Yahoo's records.</p> : (
          <>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={byYear}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="year" fontSize={11} /><YAxis tickFormatter={(v) => `$${v}`} width={45} />
                <Tooltip formatter={(v) => `$${(v as number).toFixed(2)}`} /><Bar dataKey="amount" name="Per share" fill={COLORS[1]} /></BarChart>
            </ResponsiveContainer>
            <p className="muted small">Cash paid to shareholders for each share they own, by year. Steady or rising payments are a sign of a mature, profitable business.</p>
          </>
        )}</div>
      {a.dividends.length > 0 && (
        <div className="card"><h3>Recent dividend payments</h3>
          <div className="table-scroll"><table className="grid"><thead><tr><th>Ex-dividend date</th><th className="right">Per share</th></tr></thead>
            <tbody>{a.dividends.map((d) => <tr key={d.date}><td>{fmtDate(d.date)}</td><td className="right">{d.amount == null ? "—" : `$${d.amount.toFixed(d.amount < 1 ? 3 : 2)}`}</td></tr>)}</tbody></table></div></div>
      )}
      {shares.length > 1 && (
        <div className="card"><h3>Shares outstanding</h3>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={shares}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="date" minTickGap={30} fontSize={11} /><YAxis tickFormatter={count} width={60} domain={["auto", "auto"]} />
              <Tooltip formatter={(v) => count(v as number)} /><Line dataKey="shares" stroke={COLORS[0]} dot={false} /></LineChart>
          </ResponsiveContainer>
          <p className="muted small">{change != null && `${change < 0 ? "Down" : "Up"} ${Math.abs(change * 100).toFixed(1)}% over this period. `}A falling count usually means the company is buying back its own shares, which gives each remaining share a bigger slice of the profits.</p></div>
      )}
      <div className="card"><h3>Stock splits</h3>
        {a.splits.length === 0 ? <p className="muted small">No splits in Yahoo's records.</p> : (
          <div className="table-scroll"><table className="grid"><tbody>{a.splits.map((x) => <tr key={x.date}><td>{fmtDate(x.date)}</td><td className="right">{split(x.ratio)}</td></tr>)}</tbody></table></div>
        )}
        <p className="muted small">A 4-for-1 split turns each share into 4 cheaper ones. The total value you own doesn't change.</p></div>
      {a.capital_gains.length > 0 && (
        <div className="card"><h3>Capital gains distributions</h3>
          <div className="table-scroll"><table className="grid"><tbody>{a.capital_gains.map((g) => <tr key={g.date}><td>{fmtDate(g.date)}</td><td className="right">{g.amount == null ? "—" : `$${g.amount.toFixed(3)}`}</td></tr>)}</tbody></table></div>
          <p className="muted small">Profits a fund made selling holdings, paid out to shareholders (and usually taxable).</p></div>
      )}
    </div>
  );
}
