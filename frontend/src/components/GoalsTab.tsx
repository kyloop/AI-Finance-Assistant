import { useEffect, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { GoalInput, GoalResult, Profile, SavedGoal } from "../types";
import { COLORS, ErrorBanner, pct, usd } from "./common";

const GOAL_LABELS: Record<GoalInput["goal_type"], string> = { retirement: "Retirement", house: "House", education: "Education", other: "Other" };
const toInput = ({ id: _id, ...g }: SavedGoal): GoalInput => g;

/** Chart rows: the steady projection plus the Monte Carlo bands (as [low, high] ranges) for each year. */
function chartRows(r: GoalResult) {
  return r.series.map((s, i) => {
    const b = r.monte_carlo.bands[i];
    return { ...s, median: b.p50, outer: [b.p10, b.p90], inner: [b.p25, b.p75] };
  });
}

function fmtTooltip(v: number | number[], name: string): [string, string] {
  return [Array.isArray(v) ? `${usd(v[0])} – ${usd(v[1])}` : usd(v), name];
}

export default function GoalsTab({ sid, profile }: { sid: string; profile: Profile }) {
  const [g, setG] = useState<GoalInput>({ goal_type: "retirement", target_amount: 1_000_000, horizon_years: profile.horizon_years, current_savings: 10_000, monthly_contribution: 500, risk_tolerance: profile.risk_tolerance });
  const [result, setResult] = useState<GoalResult | null>(null);
  const [saved, setSaved] = useState<SavedGoal[]>([]);
  const [showBands, setShowBands] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const num = (k: keyof GoalInput) => (e: React.ChangeEvent<HTMLInputElement>) => setG({ ...g, [k]: Number(e.target.value) });

  useEffect(() => { api.goals(sid).then(setSaved).catch(() => setSaved([])); }, [sid]);

  async function project(input: GoalInput) {
    setError(null);
    if (!(input.target_amount > 0) || input.horizon_years < 1) return setError("Enter a target amount above 0 and a horizon of at least 1 year.");
    setBusy(true);
    try {
      setResult(await api.projectGoal(sid, input));
      setSaved(await api.goals(sid));
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  function run(e: React.FormEvent) { e.preventDefault(); project(g); }

  function load(s: SavedGoal) { const input = toInput(s); setG(input); project(input); }

  async function remove(id: number) {
    setError(null);
    try {
      await api.deleteGoal(sid, id);
      setSaved(saved.filter((s) => s.id !== id));
      if (result?.goal_id === id) setResult(null);
    } catch (err) { setError((err as Error).message); }
  }

  const mc = result?.monte_carlo;
  return (
    <section>
      <form className="form-grid" onSubmit={run}>
        <label>Goal
          <select value={g.goal_type} onChange={(e) => setG({ ...g, goal_type: e.target.value as GoalInput["goal_type"] })}>
            {Object.entries(GOAL_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></label>
        <label>Target amount ($)<input type="number" min={1} value={g.target_amount} onChange={num("target_amount")} /></label>
        <label>Years<input type="number" min={1} max={60} value={g.horizon_years} onChange={num("horizon_years")} /></label>
        <label>Current savings ($)<input type="number" min={0} value={g.current_savings} onChange={num("current_savings")} /></label>
        <label>Monthly contribution ($)<input type="number" min={0} value={g.monthly_contribution} onChange={num("monthly_contribution")} /></label>
        <label>Risk
          <select value={g.risk_tolerance} onChange={(e) => setG({ ...g, risk_tolerance: e.target.value as GoalInput["risk_tolerance"] })}>
            <option value="conservative">Conservative</option><option value="moderate">Moderate</option><option value="aggressive">Aggressive</option>
          </select></label>
        <button disabled={busy}>{busy ? "Projecting…" : "Project"}</button>
      </form>
      <ErrorBanner message={error} />

      {saved.length > 0 && (
        <div className="card wide goal-saved">
          <div className="muted small">Saved goals — the latest one is what the chat uses for “am I on track?”</div>
          <ul>
            {[...saved].reverse().map((s) => (
              <li key={s.id} className={result?.goal_id === s.id ? "active" : undefined}>
                <button type="button" className="link-more" onClick={() => load(s)} disabled={busy}>
                  {GOAL_LABELS[s.goal_type]}: {usd(s.target_amount)} in {s.horizon_years} yrs · {usd(s.monthly_contribution)}/mo · {s.risk_tolerance}
                </button>
                <button type="button" className="link" onClick={() => remove(s.id)} aria-label="Delete goal">Delete</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {result && mc && (
        <>
          <div className="cards">
            <div className="card"><div className="muted small">Projected value (steady return)</div><div className="big">{usd(result.projected_value)}</div>
              <div className={result.on_track ? "up" : "down"}>{result.on_track ? "On track" : `Short by ${usd(result.shortfall)}`}</div></div>
            <div className="card"><div className="muted small">Chance of reaching target</div>
              <div className={`big ${mc.probability_of_success >= mc.confidence ? "up" : mc.probability_of_success >= 0.5 ? "" : "down"}`}>{pct(mc.probability_of_success, 0)}</div>
              <div className="muted small">in {mc.simulations.toLocaleString()} simulated markets</div></div>
            <div className="card"><div className="muted small">Simulated outcome (middle 80%)</div><div className="big">{usd(mc.final_percentiles.p50)}</div>
              <div className="muted small">median · {usd(mc.final_percentiles.p10)} – {usd(mc.final_percentiles.p90)}</div></div>
            <div className="card"><div className="muted small">Monthly needed to reach target</div><div className="big">{usd(result.required_monthly)}</div>
              <div className="muted small">{usd(mc.required_monthly_for_confidence)} for a {pct(mc.confidence, 0)} chance</div></div>
            <div className="card"><div className="muted small">Illustrative mix</div>
              <div>{Object.entries(result.suggested_allocation).map(([k, v]) => `${v}% ${k}`).join(" · ")}</div></div>
          </div>
          <label className="goal-toggle"><input type="checkbox" checked={showBands} onChange={(e) => setShowBands(e.target.checked)} /> Show Monte Carlo range</label>
          <ResponsiveContainer width="100%" height={340}>
            <ComposedChart data={chartRows(result)}>
              <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="year" label={{ value: "Years", position: "insideBottom", offset: -4 }} />
              <YAxis tickFormatter={(v) => usd(v)} width={90} /><Tooltip formatter={fmtTooltip} labelFormatter={(y) => `Year ${y}`} /><Legend />
              {showBands && <Area dataKey="outer" name="10th–90th percentile" stroke="none" fill={COLORS[0]} fillOpacity={0.12} isAnimationActive={false} />}
              {showBands && <Area dataKey="inner" name="25th–75th percentile" stroke="none" fill={COLORS[0]} fillOpacity={0.22} isAnimationActive={false} />}
              {showBands && <Line dataKey="median" name="Simulated median" stroke={COLORS[4]} dot={false} isAnimationActive={false} />}
              <Line dataKey="projected" name="Steady projection" stroke={COLORS[0]} dot={false} />
              <Line dataKey="contributed" name="You contribute" stroke={COLORS[1]} dot={false} />
              <Line dataKey="target" name="Target" stroke={COLORS[3]} strokeDasharray="6 4" dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
          <p className="muted small">
            The steady projection assumes a {pct(result.annual_return_assumption, 0)} nominal yearly return every year for a {g.risk_tolerance} profile.
            The Monte Carlo range replays {mc.simulations.toLocaleString()} random market paths with the same average return and {pct(mc.volatility_assumption, 0)} yearly
            volatility. Ups and downs pull the typical (median) result below the steady line. These are illustrative assumptions; real returns are never guaranteed.
          </p>
        </>
      )}
    </section>
  );
}
