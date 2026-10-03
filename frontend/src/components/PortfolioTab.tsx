import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { Analysis, Holding, Mover } from "../types";
import { COLORS, ErrorBanner, FreshnessBadge, pct, usd } from "./common";

const signedUsd = (n: number) => `${n >= 0 ? "+" : "−"}${usd(Math.abs(n))}`;
const signedPct = (n: number, d = 1) => `${n >= 0 ? "+" : "−"}${pct(Math.abs(n), d)}`;
const tone = (n: number | null | undefined) => (n == null || n === 0 ? "" : n > 0 ? "up" : "down");
const ratio = (n: number | null | undefined) => (n == null ? "n/a" : n.toFixed(2));
const mdy = (iso: string) => iso.replace(/^(\d{4})-(\d{2})-(\d{2})$/, "$2-$3-$1");      // 2026-01-01 -> 01-01-2026

function parseCsv(text: string): Holding[] {
  const [head, ...lines] = text.trim().split(/\r?\n/);
  const cols = head.split(",").map((c) => c.trim().toLowerCase());
  const idx = (n: string) => cols.indexOf(n);
  if (idx("ticker") < 0 || idx("shares") < 0) throw new Error("CSV needs columns: ticker, shares[, cost_basis, purchase_date]");
  return lines.filter(Boolean).map((l) => {
    const c = l.split(",");
    const cb = idx("cost_basis") >= 0 && c[idx("cost_basis")]?.trim() ? Number(c[idx("cost_basis")]) : null;
    const bought = idx("purchase_date") >= 0 ? c[idx("purchase_date")]?.trim() || null : null;      // YYYY-MM-DD
    return { ticker: c[idx("ticker")].trim().toUpperCase(), shares: Number(c[idx("shares")]), cost_basis: cb, purchase_date: bought };
  });
}

export default function PortfolioTab({ sid, onAsk }: { sid: string; onAsk: (q: string) => void }) {
  const [rows, setRows] = useState<Holding[]>([]);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [defaultDate, setDefaultDate] = useState("");

  useEffect(() => { api.getPortfolio(sid).then((p) => { setRows(p.holdings); setDefaultDate(p.default_purchase_date); if (p.holdings.length) api.analysis(sid).then(setAnalysis); }).catch((e) => setError(e.message)); }, [sid]);

  async function analyze(next: Holding[] = rows) {
    setError(null);
    const bad = next.find((r) => !r.ticker.trim() || !(r.shares > 0));
    if (bad) return setError("Each row needs a ticker and a number of shares greater than 0.");
    setBusy(true);
    try { await api.savePortfolio(sid, next); setAnalysis(await api.analysis(sid)); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const update = (i: number, patch: Partial<Holding>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  async function onFile(f?: File) {
    if (!f) return;
    try { const parsed = parseCsv(await f.text()); setRows(parsed); await analyze(parsed); } catch (e) { setError((e as Error).message); }
  }
  async function loadSample(name: string) {
    const text = await (await fetch(`/samples/${name}.csv`)).text();
    const parsed = parseCsv(text); setRows(parsed); await analyze(parsed);
  }

  const today = new Date().toLocaleDateString("en-CA");       // YYYY-MM-DD, local
  const perf = analysis?.performance, divs = analysis?.dividends, movers = analysis?.movers;

  return (
    <section>
      <h2>Your holdings</h2>
      <table className="grid">
        <thead><tr><th>Ticker</th><th>Shares</th><th>Cost basis / share (optional)</th><th>Purchase date (optional)</th><th /></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><input value={r.ticker} onChange={(e) => update(i, { ticker: e.target.value.toUpperCase() })} aria-label="Ticker" /></td>
              <td><input type="number" min={0} value={r.shares || ""} onChange={(e) => update(i, { shares: Number(e.target.value) })} aria-label="Shares" /></td>
              <td><input type="number" min={0} value={r.cost_basis ?? ""} onChange={(e) => update(i, { cost_basis: e.target.value === "" ? null : Number(e.target.value) })} aria-label="Cost basis" /></td>
              <td><DateInput value={r.purchase_date} max={today} placeholder={mdy(defaultDate)} onChange={(d) => update(i, { purchase_date: d })} /></td>
              <td><button className="link" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row">
        <button className="secondary" onClick={() => setRows([...rows, { ticker: "", shares: 0, cost_basis: null, purchase_date: null }])}>Add holding</button>
        <label className="secondary file">Upload CSV<input type="file" accept=".csv" hidden onChange={(e) => onFile(e.target.files?.[0])} /></label>
        <button className="secondary" onClick={() => loadSample("balanced")}>Load balanced sample</button>
        <button className="secondary" onClick={() => loadSample("tech_heavy")}>Load tech-heavy sample</button>
        <button onClick={() => analyze()} disabled={busy}>{busy ? "Analyzing…" : "Analyze"}</button>
      </div>
      <ErrorBanner message={error} />

      {analysis?.empty && <p className="muted">Add holdings or load a sample portfolio to see your analysis.</p>}
      {analysis && !analysis.empty && (
        <>
          {analysis.data_info && <div className="muted small">Prices: <FreshnessBadge freshness={analysis.data_info.freshness} provider={analysis.data_info.provider} fetchedAt={analysis.data_info.fetched_at} /></div>}
          <div className="cards">
            <Card label="Total value" value={usd(analysis.total_value)} sub={`${analysis.holdings.length} holdings`} />
            {analysis.total_gain_loss != null && <Card label="Total return" value={signedUsd(analysis.total_gain_loss)} tone={tone(analysis.total_gain_loss)}
              sub={analysis.total_return_pct != null ? `${signedPct(analysis.total_return_pct)} on cost basis` : undefined} />}
            {analysis.day_change != null && <Card label="Today" value={signedUsd(analysis.day_change)} tone={tone(analysis.day_change)}
              sub={analysis.day_change_pct != null ? signedPct(analysis.day_change_pct, 2) : undefined} />}
            <Card label="Diversification" value={`${analysis.diversification_score}/100`} sub={`${analysis.effective_holdings} effective holdings`} />
            <Card label="Risk level" value={`${analysis.risk_level}/5`} sub={analysis.risk_label} />
            <Card label="Yearly fees" value={`$${analysis.annual_fee?.toFixed(2)}`} sub={`${pct(analysis.weighted_expense_ratio ?? 0, 2)} weighted`} />
          </div>
          {analysis.warnings.length > 0 && <ul className="warnings">{analysis.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
          {perf && perf.period_return != null && (
            <>
              <h3>Performance vs {perf.benchmark.name}</h3>
              <div className="cards">
                <Card label={`Return since ${perf.start}`} value={signedPct(perf.period_return)} tone={tone(perf.period_return)}
                  sub={perf.annualized_return != null ? `${signedPct(perf.annualized_return)} annualized` : undefined} />
                {perf.benchmark_return != null && <Card label={perf.benchmark.name} value={signedPct(perf.benchmark_return)} tone={tone(perf.benchmark_return)}
                  sub={perf.excess_return != null ? `you: ${signedPct(perf.excess_return)} vs the index` : undefined} />}
                <Card label="Volatility" value={perf.volatility != null ? pct(perf.volatility) : "n/a"} sub="yearly swing in value" />
                <Card label="Max drawdown" value={signedPct(perf.max_drawdown ?? 0)} sub="largest fall from a peak" />
                <Card label="Sharpe ratio" value={ratio(perf.sharpe)} sub={`return per unit of risk, over ${pct(perf.risk_free_rate, 0)} risk-free`} />
                <Card label="Sortino ratio" value={ratio(perf.sortino)} sub="counts downside swings only" />
              </div>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={perf.points}>
                  <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="date" minTickGap={40} />
                  <YAxis domain={["auto", "auto"]} tickFormatter={(v) => usd(v)} width={80} /><Tooltip formatter={(v: number) => usd(v)} /><Legend />
                  <Line dataKey="value" name="Your portfolio" stroke={COLORS[0]} dot={false} />
                  <Line dataKey="benchmark" name={`${perf.benchmark.name} (same starting value)`} stroke={COLORS[2]} dot={false} />
                </LineChart>
              </ResponsiveContainer>
              <p className="muted small">Each holding counts from its purchase date, as if bought in full that day; a purchase adds to the value but is not counted as a gain.
                The {perf.benchmark.name} line puts the same money into the index on the same dates.
                {perf.assumed.length > 0 && ` No purchase date for ${perf.assumed.join(", ")}: ${perf.default_start} is assumed.`}
                {perf.clamped.map((t) => ` ${t} has no prices before ${perf.clamped_from[t]}, so it counts from then.`)}
                {perf.pending.length > 0 && ` ${perf.pending.join(", ")} bought after the latest close: not counted yet.`}
                {perf.excluded.length > 0 && ` No price history for ${perf.excluded.join(", ")}, so they are left out here.`}
                {perf.annualized_return == null && " Under 30 trading days: too short for annualized return, volatility and the ratios."}</p>
            </>
          )}
          <div className="charts">
            {movers && (movers.winners.length > 0 || movers.losers.length > 0) && (
              <div><h3>Top winners and losers ({movers.basis === "total" ? "since purchase" : "today"})</h3>
                <table className="grid"><tbody>
                  {[...movers.winners, ...movers.losers].map((m: Mover) => (
                    <tr key={m.ticker}><td>{m.ticker} <span className="muted small">{m.name}</span></td>
                      <td className={tone(m.change_pct)}>{signedPct(m.change_pct)}</td><td className={tone(m.change)}>{signedUsd(m.change)}</td></tr>
                  ))}
                </tbody></table></div>
            )}
            {divs && (
              <div><h3>Dividend income (last 12 months)</h3>
                {divs.by_month.length === 0 ? <p className="muted">No dividend payments found for these holdings.</p> : (
                  <>
                    <div className="muted small">{usd(divs.total)} a year at today's share counts, a {pct(divs.yield, 2)} yield</div>
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={divs.by_month}><XAxis dataKey="month" /><YAxis tickFormatter={(v) => usd(v)} width={70} />
                        <Tooltip formatter={(v: number) => usd(v)} /><Bar dataKey="amount" name="Dividends" fill={COLORS[1]} /></BarChart>
                    </ResponsiveContainer>
                  </>
                )}</div>
            )}
          </div>
          <div className="charts">
            <div><h3>Allocation</h3>
              <ResponsiveContainer width="100%" height={260}>
                <PieChart><Pie data={analysis.allocation} dataKey="weight" nameKey="name" outerRadius={90} label={(d) => pct(d.weight, 0)}>
                  {analysis.allocation?.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Pie>
                  <Tooltip formatter={(v: number) => pct(v)} /><Legend /></PieChart>
              </ResponsiveContainer></div>
            <div><h3>Sector exposure (incl. fund look-through)</h3>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={analysis.sectors} layout="vertical" margin={{ left: 20 }}>
                  <XAxis type="number" tickFormatter={(v) => pct(v, 0)} /><YAxis type="category" dataKey="name" width={90} />
                  <Tooltip formatter={(v: number) => pct(v)} /><Bar dataKey="weight" fill={COLORS[0]} /></BarChart>
              </ResponsiveContainer></div>
            <div><h3>Geographic exposure (approximate)</h3>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={analysis.geography} layout="vertical" margin={{ left: 20 }}>
                  <XAxis type="number" tickFormatter={(v) => pct(v, 0)} /><YAxis type="category" dataKey="name" width={130} />
                  <Tooltip formatter={(v: number) => pct(v)} /><Bar dataKey="weight" fill={COLORS[4]} /></BarChart>
              </ResponsiveContainer>
              <p className="muted small">From each holding's type: funds don't report a country split, and single stocks count as US.</p></div>
          </div>
          <table className="grid"><thead><tr><th>Asset</th><th>Symbol</th><th>Class</th><th>Value</th><th>Allocation</th><th>Today</th><th>Gain / loss</th></tr></thead>
            <tbody>
              {analysis.holdings.map((h) => (
                <tr key={h.ticker}><td>{h.name}</td><td>{h.ticker}</td><td>{h.asset_class}</td><td>{usd(h.value)}</td><td>{pct(h.weight)}</td>
                  <td className={tone(h.day_change)}>{h.day_change_pct != null ? signedPct(h.day_change_pct, 2) : "n/a"}</td>
                  <td className={tone(h.gain_loss)}>{h.gain_loss != null ? `${signedUsd(h.gain_loss)}${h.gain_loss_pct != null ? ` (${signedPct(h.gain_loss_pct)})` : ""}` : "n/a"}</td></tr>
              ))}
              <tr><td><b>Total</b></td><td /><td /><td><b>{usd(analysis.total_value)}</b></td><td><b>100%</b></td>
                <td className={tone(analysis.day_change)}>{analysis.day_change_pct != null ? signedPct(analysis.day_change_pct, 2) : "n/a"}</td>
                <td className={tone(analysis.total_gain_loss)}>{analysis.total_gain_loss != null ? signedUsd(analysis.total_gain_loss) : "n/a"}</td></tr>
            </tbody></table>
          <button className="secondary" onClick={() => onAsk("Can you explain my portfolio's diversification and risk?")}>Ask Finnie about this portfolio</button>
        </>
      )}
    </section>
  );
}

/** A date field that shows a placeholder while empty (a date input cannot), becoming a date picker once focused or filled. */
function DateInput({ value, max, placeholder, onChange }: { value?: string | null; max: string; placeholder: string; onChange: (d: string | null) => void }) {
  const [focused, setFocused] = useState(false);
  return <input type={value || focused ? "date" : "text"} max={max} value={value ?? ""} placeholder={placeholder} aria-label="Purchase date"
    onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} onChange={(e) => onChange(e.target.value || null)} />;
}

const Card = ({ label, value, sub, tone = "" }: { label: string; value: string; sub?: string; tone?: string }) => (
  <div className="card"><div className="muted small">{label}</div><div className={`big ${tone}`}>{value}</div>{sub && <div className="muted small">{sub}</div>}</div>
);
