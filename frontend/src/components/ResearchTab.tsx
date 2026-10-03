import { useEffect, useState } from "react";
import { api } from "../api";
import type { Envelope, FundProfile, Weight } from "../types";
import { COLORS, ErrorBanner, FreshnessBadge } from "./common";
import StockResearch from "./StockResearch";

const EXAMPLES = ["VOO", "QQQ", "VXUS", "BND", "VFIAX"];
const DESC_CHARS = 320;

const pct = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
const fee = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(2)}%`);   // 0.0003 -> 0.03%
const num = (v: number | null | undefined, d = 1) => (v == null ? "—" : v.toFixed(d));
function money(v: number | null | undefined): string {
  if (v == null) return "—";
  const [n, u] = v >= 1e12 ? [v / 1e12, "T"] : v >= 1e9 ? [v / 1e9, "B"] : v >= 1e6 ? [v / 1e6, "M"] : [v, ""];
  return `$${n.toFixed(n >= 100 ? 0 : 1)}${u}`;
}

const SUBTABS = ["Fund research", "Stock research"] as const;
type SubTab = (typeof SUBTABS)[number];
const SUBTAB_KEY = "finnie_research_tab";

/** Research: look inside a fund (Fund research) or a company (Stock research). The chosen sub-tab is remembered. */
export default function ResearchTab({ onAsk }: { onAsk: (q: string) => void }) {
  const [sub, setSub] = useState<SubTab>(() => {
    try { return (SUBTABS as readonly string[]).includes(localStorage.getItem(SUBTAB_KEY) ?? "") ? localStorage.getItem(SUBTAB_KEY) as SubTab : "Fund research"; }
    catch { return "Fund research"; }
  });
  const pick = (t: SubTab) => { setSub(t); try { localStorage.setItem(SUBTAB_KEY, t); } catch { /* private mode */ } };
  return (
    <section className="research">
      <nav className="subtabs" aria-label="Research">
        {SUBTABS.map((t) => <button key={t} className={t === sub ? "tab active" : "tab"} aria-pressed={t === sub} onClick={() => pick(t)}>{t}</button>)}
      </nav>
      {sub === "Fund research" ? <FundResearch onAsk={onAsk} /> : <StockResearch onAsk={onAsk} />}
    </section>
  );
}

/** ETF and mutual-fund research: what a fund holds, what it costs and how it compares with its category (yfinance `funds_data`). */
function FundResearch({ onAsk }: { onAsk: (q: string) => void }) {
  const [symbol, setSymbol] = useState("VOO");
  const [input, setInput] = useState("VOO");
  const [env, setEnv] = useState<Envelope<FundProfile> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true); setError(null);
    api.fund(symbol)
      .then((e) => { if (alive) setEnv(e); })
      .catch((e) => { if (alive) { setError(e.message); setEnv(null); } })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [symbol]);

  const look = (s: string) => { const v = s.trim().toUpperCase(); setInput(v); setSymbol(v); };
  const f = env?.data;
  return (
    <div>
      <h2>Fund research</h2>
      <p className="muted small">Look inside an ETF or mutual fund: what it holds, what it costs and how it compares with similar funds.</p>
      <form className="row" onSubmit={(e) => { e.preventDefault(); look(input); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Fund or ETF ticker, e.g. VOO" aria-label="Fund ticker" />
        <button disabled={loading}>{loading ? "Loading…" : "Look up"}</button>
      </form>
      <div className="row chips" aria-label="Examples">
        <span className="muted small">Try:</span>
        {EXAMPLES.map((s) => <button key={s} type="button" className="secondary chip" aria-pressed={s === symbol} onClick={() => look(s)}>{s}</button>)}
      </div>
      <ErrorBanner message={error} />
      {f && env && <FundView f={f} env={env} onAsk={onAsk} />}
    </div>
  );
}

function FundView({ f, env, onAsk }: { f: FundProfile; env: Envelope<FundProfile>; onAsk: (q: string) => void }) {
  const [more, setMore] = useState(false);
  const o = f.operations, eq = f.equity, b = f.bond;
  const holdsBonds = f.asset_classes.some((a) => a.name === "Bonds") || f.bond_ratings.length > 0;
  const hasEquity = [eq.pe, eq.pb, eq.ps, eq.pcf, eq.median_market_cap].some((v) => v != null);
  const topShare = f.top_holdings.reduce((s, h) => s + (h.weight ?? 0), 0);
  const desc = f.description.length > DESC_CHARS && !more ? `${f.description.slice(0, DESC_CHARS)}…` : f.description;

  return (
    <>
      <div className="card wide">
        <div className="muted small">
          {[f.quote_type === "MUTUALFUND" ? "Mutual fund" : f.quote_type, f.category, f.family].filter(Boolean).join(" · ")}{" "}
          <FreshnessBadge freshness={env.freshness} provider={env.provider} fetchedAt={env.fetched_at} />
        </div>
        <div className="big">{f.name} <span className="muted">({f.symbol})</span></div>
        {f.description && (
          <p className="small">{desc}{f.description.length > DESC_CHARS && <button className="link-more" onClick={() => setMore(!more)}>{more ? " less" : " more"}</button>}</p>
        )}
        <button className="secondary" onClick={() => onAsk(`Can you explain what ${f.symbol} invests in and what its fees mean for me?`)}>Ask Finnie about {f.symbol}</button>
      </div>

      <div className="cards facts">
        <Fact label="Expense ratio" value={fee(o.expense_ratio)} vs={o.category_expense_ratio != null ? `category average ${fee(o.category_expense_ratio)}` : null}
          help="The share of your money taken in fees each year. On $10,000, 0.03% is $3 a year; 1% is $100." />
        <Fact label="Total assets" value={money(f.total_assets)} help="How much money the whole fund manages, across all its share classes." />
        <Fact label="Yield" value={pct(f.yield, 2)} help="Income (dividends or interest) paid out over the last year, as a share of the price." />
        <Fact label="Turnover" value={pct(o.turnover, 0)} vs={o.category_turnover != null ? `category average ${pct(o.category_turnover, 0)}` : null}
          help="How much of the portfolio is bought and sold in a year. Lower usually means lower trading costs and taxes." />
      </div>

      <div className="research-grid">
        {f.asset_classes.length > 0 && (
          <div className="card"><h3>What it holds</h3><Bars items={f.asset_classes} />
            <p className="muted small">The mix of stocks, bonds and cash: the biggest driver of how much the fund's value swings.</p></div>
        )}
        {f.sector_weights.length > 0 && (
          <div className="card"><h3>Sectors</h3><Bars items={f.sector_weights} />
            <p className="muted small">A large share in one sector means the fund moves a lot with that part of the economy.</p></div>
        )}
        {f.top_holdings.length > 0 && (
          <div className="card"><h3>Top holdings</h3>
            <table className="grid"><thead><tr><th>Symbol</th><th>Name</th><th className="right">Weight</th></tr></thead>
              <tbody>{f.top_holdings.map((h) => <tr key={h.symbol}><td>{h.symbol}</td><td>{h.name}</td><td className="right">{pct(h.weight)}</td></tr>)}</tbody></table>
            <p className="muted small">These {f.top_holdings.length} make up {pct(topShare)} of the fund.</p></div>
        )}
        {hasEquity && (
          <div className="card"><h3>Valuation of its stocks</h3>
            <table className="grid"><thead><tr><th></th><th className="right">{f.symbol}</th><th className="right">Category</th></tr></thead>
              <tbody>
                <tr><td>Price / earnings</td><td className="right">{num(eq.pe)}</td><td className="right">{num(eq.category_pe)}</td></tr>
                <tr><td>Price / book</td><td className="right">{num(eq.pb)}</td><td className="right">{num(eq.category_pb)}</td></tr>
                <tr><td>Price / sales</td><td className="right">{num(eq.ps)}</td><td className="right">—</td></tr>
                <tr><td>Price / cash flow</td><td className="right">{num(eq.pcf)}</td><td className="right">—</td></tr>
                {eq.median_market_cap != null && <tr><td>Median company size</td><td className="right">{money(eq.median_market_cap)}</td><td /></tr>}
                {eq.earnings_growth_3y != null && <tr><td>Earnings growth (3 yr)</td><td className="right">{pct(eq.earnings_growth_3y)}</td><td /></tr>}
              </tbody></table>
            <p className="muted small">Averages over the stocks the fund holds. Higher ratios mean investors pay more for each dollar of earnings or sales, often because they expect growth.</p></div>
        )}
        {holdsBonds && (
          <div className="card"><h3>Bonds</h3>
            <table className="grid"><tbody>
              <tr><td>Average maturity</td><td className="right">{b.maturity != null ? `${num(b.maturity)} yrs` : "—"}</td></tr>
              <tr><td>Duration</td><td className="right">{b.duration != null ? `${num(b.duration)} yrs` : "—"}</td></tr>
              {f.government_share != null && <tr><td>In government bonds</td><td className="right">{pct(f.government_share)}</td></tr>}
            </tbody></table>
            {f.bond_ratings.length > 0 && <><h4 className="small">Credit ratings</h4><Bars items={f.bond_ratings} sort={false} color={COLORS[0]} /></>}
            <p className="muted small">Longer maturity and duration mean the price reacts more when interest rates change. AAA is the safest rating; below BBB is "high yield" (riskier).</p></div>
        )}
      </div>
      <p className="muted small">Source: Yahoo Finance via yfinance, refreshed daily. "—" means Yahoo doesn't report it for this fund. Total assets cover every share class (an ETF and its mutual-fund twin report the same figure).</p>
    </>
  );
}

function Fact({ label, value, vs, help }: { label: string; value: string; vs?: string | null; help: string }) {
  return (
    <div className="card" title={help}>
      <div className="muted small">{label}</div><div className="big">{value}</div>
      {vs && <div className="muted small">{vs}</div>}
      <div className="muted small fact-help">{help}</div>
    </div>
  );
}

export function Bars({ items, sort = true, color }: { items: Weight[]; sort?: boolean; color?: string }) {
  const rows = sort ? [...items].sort((a, b) => b.weight - a.weight) : items;
  const max = Math.max(...rows.map((r) => r.weight), 0.0001);
  return (
    <ul className="bars">
      {rows.map((r, i) => (
        <li key={r.name}>
          <span className="bar-label">{r.name}</span>
          <span className="bar-track"><span className="bar-fill" style={{ width: `${(r.weight / max) * 100}%`, background: color ?? COLORS[i % COLORS.length] }} /></span>
          <span className="bar-value">{r.weight > 0 && r.weight < 0.0005 ? "<0.1%" : pct(r.weight)}</span>
        </li>
      ))}
    </ul>
  );
}
