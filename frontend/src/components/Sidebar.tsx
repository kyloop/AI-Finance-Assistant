import type { Knowledge, Profile, Risk } from "../types";

interface Props { profile: Profile; onChange: (p: Profile) => void; onReset: () => void; saving: boolean; collapsed: boolean; onCollapse: (c: boolean) => void }

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

export default function Sidebar({ profile, onChange, onReset, saving, collapsed, onCollapse }: Props) {
  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => onChange({ ...profile, [k]: v });
  const summary = `${cap(profile.knowledge_level)} · ${cap(profile.risk_tolerance)} risk · ${profile.horizon_years} yr`;

  if (collapsed) {
    return (
      <aside className="sidebar collapsed">
        <button className="profile-icon" onClick={() => onCollapse(false)} aria-label={`Edit your profile (${summary})`} title={`Your profile: ${summary}\nClick to edit`}>
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" />
          </svg>
        </button>
        <span className="profile-mini" aria-hidden="true">{profile.knowledge_level[0].toUpperCase()}·{profile.risk_tolerance[0].toUpperCase()}·{profile.horizon_years}y</span>
      </aside>
    );
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <h2>Your profile</h2>
        <button className="icon-btn" onClick={() => onCollapse(true)} aria-label="Minimize profile" title="Minimize">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 6l-6 6 6 6" /></svg>
        </button>
      </div>
      <label>Knowledge level
        <select value={profile.knowledge_level} onChange={(e) => set("knowledge_level", e.target.value as Knowledge)}>
          <option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option>
        </select>
      </label>
      <label>Risk tolerance
        <select value={profile.risk_tolerance} onChange={(e) => set("risk_tolerance", e.target.value as Risk)}>
          <option value="conservative">Conservative</option><option value="moderate">Moderate</option><option value="aggressive">Aggressive</option>
        </select>
      </label>
      <label>Investment horizon (years)
        <input type="number" min={1} max={60} value={profile.horizon_years}
               onChange={(e) => set("horizon_years", Math.min(60, Math.max(1, Number(e.target.value) || 1)))} />
      </label>
      <label>Goals (comma separated)
        <input value={profile.goals.join(", ")} placeholder="retirement, house"
               onChange={(e) => set("goals", e.target.value.split(",").map((g) => g.trim()).filter(Boolean))} />
      </label>
      <p className="muted">{saving ? "Saving…" : "Saved"}</p>
      <button onClick={() => onCollapse(true)} disabled={saving}>Done</button>
      <button className="secondary" onClick={onReset}>Reset conversation</button>
      <p className="muted small">Market data: Yahoo Finance (live), with bundled sample data as an offline fallback.</p>
    </aside>
  );
}
