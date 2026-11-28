import type { Freshness } from "../types";

export const DISCLAIMER = "This is for educational purposes only and is not financial advice.";
export const usd = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
export const pct = (n: number, d = 1) => `${(n * 100).toFixed(d)}%`;
export const COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#64748b"];

/** XAxis props for a bar chart's category axis: Recharts drops labels it thinks would overlap
 *  (interval "preserveEnd"), so 5 bars can show 3 labels. Show every label, tilted when crowded. */
export function categoryAxis(data: Record<string, unknown>[], key: string) {
  const longest = Math.max(0, ...data.map((r) => String(r[key] ?? "").length));
  const tilt = data.length * longest > 40 || data.length > 8;
  return tilt
    ? { dataKey: key, interval: 0, angle: -35, textAnchor: "end" as const, height: Math.min(90, 18 + longest * 5.5) }
    : { dataKey: key, interval: 0 };
}

const LABEL: Record<Freshness, string> = { live: "Live", cached: "Cached", stale: "Stale", sample: "Sample data" };

export function FreshnessBadge({ freshness, provider, fetchedAt }: { freshness: Freshness; provider?: string; fetchedAt?: string }) {
  const when = fetchedAt ? new Date(fetchedAt).toLocaleTimeString() : "";
  return (
    <span className={`badge badge-${freshness}`} title={[provider, when].filter(Boolean).join(" · ")}>
      {LABEL[freshness]}{when && ` · ${when}`}
    </span>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  return message ? <div className="error" role="alert">{message}</div> : null;
}
