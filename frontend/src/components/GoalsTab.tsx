import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { GoalInput, GoalResult, Profile } from "../types";
import { COLORS, ErrorBanner, pct, usd } from "./common";

export default function GoalsTab({ sid, profile }: { sid: string; profile: Profile }) {
  const [g, setG] = useState<GoalInput>({ goal_type: "retirement", target_amount: 1_000_000, horizon_years: profile.horizon_years, current_savings: 10_000, monthly_contribution: 500, risk_tolerance: profile.risk_tolerance });
  const [result, setResult] = useState<GoalResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const num = (k: keyof GoalInput) => (e: React.ChangeEvent<HTMLInputElement>) => setG({ ...g, [k]: Number(e.target.value) });

  async function run(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    if (!(g.target_amount > 0) || g.horizon_years < 1) return setError("Enter a target amount above 0 and a horizon of at least 1 year.");
    setBusy(true);
    try { setResult(await api.projectGoal(sid, g)); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <section>
      <form className="form-grid" onSubmit={run}>
        <label>Goal
          <select value={g.goal_type} onChange={(e) => setG({ ...g, goal_type: e.target.value as GoalInput["goal_type"] })}>
            <option value="retirement">Retirement</option><option value="house">House</option><option value="education">Education</option><option value="other">Other</option>
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
      {result && (
        <>
          <div className="cards">
            <div className="card"><div className="muted small">Projected value</div><div className="big">{usd(result.projected_value)}</div>
              <div className={result.on_track ? "up" : "down"}>{result.on_track ? "On track" : `Short by ${usd(result.shortfall)}`}</div></div>
            <div className="card"><div className="muted small">Monthly needed to reach target</div><div className="big">{usd(result.required_monthly)}</div></div>
            <div className="card"><div className="muted small">Illustrative mix</div>
              <div>{Object.entries(result.suggested_allocation).map(([k, v]) => `${v}% ${k}`).join(" · ")}</div></div>
          </div>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={result.series}>
              <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="year" label={{ value: "Years", position: "insideBottom", offset: -4 }} />
              <YAxis tickFormatter={(v) => usd(v)} width={90} /><Tooltip formatter={(v: number) => usd(v)} /><Legend />
              <Line dataKey="projected" name="Projected" stroke={COLORS[0]} dot={false} />
              <Line dataKey="contributed" name="You contribute" stroke={COLORS[1]} dot={false} />
              <Line dataKey="target" name="Target" stroke={COLORS[3]} strokeDasharray="6 4" dot={false} />
            </LineChart>
          </ResponsiveContainer>
          <p className="muted small">Assumes a steady {pct(result.annual_return_assumption, 0)} nominal yearly return for a {g.risk_tolerance} profile. Real returns vary a lot year to year and are never guaranteed.</p>
        </>
      )}
    </section>
  );
}
