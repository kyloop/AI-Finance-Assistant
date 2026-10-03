import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api";
import type { Tick } from "../liveStream";
import type { Envelope, HistoryPoint, IntradayPoint, LiveQuote, Quote, SymbolInfo } from "../types";
import { COLORS, ErrorBanner, FreshnessBadge } from "./common";
import Sparkline from "./Sparkline";
import { useLiveStream } from "../liveStream";
import type { StreamState } from "../liveStream";

const RANGES = { "1D": 0, "1M": 21, "3M": 63, "6M": 126, "1Y": 250 } as const;
type Range = keyof typeof RANGES;
const INTERVALS = [{ label: "Off", s: 0 }, { label: "15s", s: 15 }, { label: "30s", s: 30 }, { label: "60s", s: 60 }];
const STREAM_LABEL: Record<StreamState, string> = { connecting: "Connecting…", connected: "Live stream", reconnecting: "Reconnecting…", closed: "Stream off" };
const DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "VTI", "QQQ", "BND"];
const INDEX_SYMBOLS = ["^GSPC", "^IXIC", "^DJI"];
const STORAGE_KEY = "finnie_watchlist";

export const loadWatchlist = (): string[] => {
  try { const v = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null"); if (Array.isArray(v) && v.length) return v; } catch { /* fall through */ }
  return DEFAULT_WATCHLIST;
};
const money = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });
const signedPct = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
const compact = (n: number) => Intl.NumberFormat("en-US", { notation: "compact" }).format(n);

export default function LiveTab({ onSelect }: { onSelect?: (symbol: string) => void }) {
  const [watchlist, setWatchlist] = useState<string[]>(loadWatchlist);
  const [selected, setSelected] = useState<string>(() => loadWatchlist()[0]);
  const [range, setRange] = useState<Range>("1D");
  const [interval, setIntervalSec] = useState(30);
  const [countdown, setCountdown] = useState(30);
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({});
  const [indices, setIndices] = useState<LiveQuote[]>([]);
  const [intraday, setIntraday] = useState<{ prev_close: number; points: IntradayPoint[]; tz?: string } | null>(null);
  const [histories, setHistories] = useState<Record<string, HistoryPoint[]>>({});
  const [available, setAvailable] = useState<SymbolInfo[]>([]);
  const [adding, setAdding] = useState("");
  const [showMA, setShowMA] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(watchlist)); } catch { /* storage unavailable */ } }, [watchlist]);
  useEffect(() => { onSelect?.(selected); }, [selected, onSelect]);
  useEffect(() => { api.symbols().then(setAvailable).catch(() => undefined); }, []);
  useEffect(() => { if (!watchlist.includes(selected)) setSelected(watchlist[0] ?? ""); }, [watchlist, selected]);

  // ---- live data: quotes + indices + selected intraday ------------------------------------------------
  // One request per symbol, in parallel: the provider is ~1s per symbol, so rows fill in as each one lands.
  const refresh = useCallback(async () => {
    if (!watchlist.length) { setQuotes({}); return; }
    setLoading(true);
    const one = (s: string, into: "quotes" | "indices") => api.quotes([s]).then((r) => {
      if (into === "quotes") setQuotes((prev) => ({ ...prev, ...Object.fromEntries(r.items.map((i) => [i.data.symbol, i])) }));
      else setIndices((prev) => [...prev.filter((i) => i.data.symbol !== s), ...r.items].sort((x, y) => INDEX_SYMBOLS.indexOf(x.data.symbol) - INDEX_SYMBOLS.indexOf(y.data.symbol)));
      return r.errors;
    });
    try {
      const results = await Promise.all([
        ...watchlist.map((s) => one(s, "quotes")),
        ...INDEX_SYMBOLS.map((s) => one(s, "indices")),
        selected ? api.intraday(selected).then((intra) => setIntraday({ prev_close: intra.data.prev_close, points: intra.data.points, tz: intra.data.tz })) : Promise.resolve(),
      ]);
      const bad = results.flatMap((r) => (Array.isArray(r) ? r : []));
      if (bad.length) setWatchlist((w) => w.filter((s) => !bad.includes(s)));
      setUpdatedAt(new Date()); setError(null);
    } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  }, [watchlist, selected]);

  const refreshRef = useRef(refresh);
  useEffect(() => { refreshRef.current = refresh; }, [refresh]);
  useEffect(() => { refresh(); }, [refresh]);

  // countdown / auto-refresh
  useEffect(() => {
    setCountdown(interval);
    if (!interval) return;
    const id = window.setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) { refreshRef.current(); return interval; }
        return c - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [interval]);

  // ---- daily history for the selected symbol + comparison (fetched once per symbol) --------------------
  useEffect(() => {
    watchlist.filter((s) => !histories[s]).forEach((s) =>
      api.history(s).then((h) => setHistories((prev) => ({ ...prev, [s]: h.data.points }))).catch(() => undefined));
  }, [watchlist, histories]);

  async function addSymbol(e: React.FormEvent) {
    e.preventDefault();
    const sym = adding.trim().toUpperCase();
    if (!sym) return;
    if (watchlist.includes(sym)) { setNotice(`${sym} is already in your watchlist.`); return; }
    if (watchlist.length >= 12) { setNotice("Watchlist is limited to 12 tickers."); return; }
    try { await api.quote(sym); } catch (err) { setNotice((err as Error).message); return; }   // 404 = unknown ticker
    setNotice(null); setWatchlist((w) => [...w, sym]); setAdding("");
  }

  // ---- live ticks (WebSocket) override REST quotes when newer ---------------------------------------------
  const { ticks, state: streamState } = useLiveStream([...watchlist, ...INDEX_SYMBOLS]);
  const mergeTick = <T extends LiveQuote>(e: T | undefined, t: Tick | undefined): T | undefined => {
    if (!e || !t || new Date(t.ts).getTime() < new Date(e.fetched_at).getTime() - 60_000) return e;
    const prev = e.data.prev_close ?? e.data.price - e.data.change;
    const change = t.change ?? t.price - prev;
    return { ...e, freshness: "live", provider: "yfinance (stream)", fetched_at: t.ts,
      data: { ...e.data, price: t.price, change, change_pct: t.change_pct ?? change / prev, volume: t.volume ?? e.data.volume,
              day_high: Math.max(e.data.day_high ?? t.price, t.price), day_low: Math.min(e.data.day_low ?? t.price, t.price) } };
  };
  const liveQuotes = useMemo(
    () => Object.fromEntries(Object.entries(quotes).map(([s, e]) => [s, mergeTick(e, ticks[s])!])),
    [quotes, ticks]);                                            // eslint-disable-line react-hooks/exhaustive-deps
  const liveIndices = useMemo(() => indices.map((i) => mergeTick(i, ticks[i.data.symbol])!), [indices, ticks]);   // eslint-disable-line react-hooks/exhaustive-deps

  // grow the selected symbol's 1-minute chart from ticks: update the current minute's bar or start a new one
  const livePoints = useMemo(() => {
    const pts = intraday?.points ?? [];
    const t = ticks[selected];
    if (!intraday || !t) return pts;
    const label = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: intraday.tz || undefined })
      .format(new Date(t.ts));
    const last = pts[pts.length - 1];
    if (last && last.t === label) return [...pts.slice(0, -1), { ...last, close: t.price }];
    if (last && label < last.t && label > "00:05") return pts;     // stale/out-of-order tick (new day wraps handled by refresh)
    return [...pts, { t: label, close: t.price, volume: 0 }];
  }, [intraday, ticks, selected]);

  const q = liveQuotes[selected]?.data;
  const up = (q?.change_pct ?? 0) >= 0;
  const lineColor = up ? "var(--up)" : "var(--down)";
  const daily = useMemo(() => (histories[selected] ?? []).slice(range === "1D" ? 0 : -RANGES[range]), [histories, selected, range]);
  const hist = histories[selected] ?? [];
  const wk52 = hist.length && q
    ? { hi: Math.max(q.price, ...hist.map((p) => p.close)), lo: Math.min(q.price, ...hist.map((p) => p.close)) } : null;

  // normalised % change comparison across the watchlist
  const compare = useMemo(() => {
    const series: Record<string, number[]> = {};
    for (const s of watchlist) {
      const base = range === "1D" ? liveQuotes[s]?.spark : histories[s]?.slice(-RANGES[range]).map((p) => p.close);
      if (base && base.length > 1) series[s] = base.map((v) => v / base[0] - 1);
    }
    const n = Math.min(...Object.values(series).map((a) => a.length), Infinity);
    if (!isFinite(n)) return [];
    return Array.from({ length: n }, (_, i) => Object.fromEntries([["i", i], ...Object.entries(series).map(([s, a]) => [s, a[a.length - n + i]])]));
  }, [watchlist, quotes, histories, range]);

  const movers = useMemo(
    () => watchlist.filter((s) => liveQuotes[s]).map((s) => ({ symbol: s, pct: liveQuotes[s].data.change_pct })).sort((a, b) => b.pct - a.pct),
    [watchlist, liveQuotes]);

  const env: Envelope<Quote> | undefined = liveQuotes[selected];

  return (
    <section className="live">
      {/* toolbar */}
      <div className="live-toolbar">
        <div>
          <h2>Live market</h2>
          <span className="muted small">
            {updatedAt ? `Updated ${updatedAt.toLocaleTimeString()}` : "Loading…"}
            {interval > 0 && ` · next refresh in ${countdown}s`}
          </span>
        </div>
        <div className="row">
          <span className={`badge ${streamState === "connected" ? "badge-live" : "badge-stale"}`} title="Real-time ticks pushed over a WebSocket">
            {streamState === "connected" ? "● " : ""}{STREAM_LABEL[streamState]}
          </span>
          {env && <FreshnessBadge freshness={env.freshness} provider={env.provider} fetchedAt={env.fetched_at} />}
          <label className="inline">Re-sync
            <select value={interval} onChange={(e) => setIntervalSec(Number(e.target.value))}>
              {INTERVALS.map((o) => <option key={o.s} value={o.s}>{o.label}</option>)}
            </select>
          </label>
          <button className="secondary" onClick={() => { refresh(); setCountdown(interval); }} disabled={loading}>{loading ? "Refreshing…" : "Refresh now"}</button>
        </div>
      </div>
      <ErrorBanner message={error} />
      <p className="muted small live-note">
        {env?.freshness === "sample"
          ? <>Showing <strong>sample data</strong>: the live provider (Yahoo Finance) is unreachable, so these numbers are illustrative.</>
          : <>Prices stream in real time from Yahoo Finance and may be delayed or briefly unavailable. Charts and history come from the same provider.</>}
      </p>

      {/* index strip */}
      <div className="cards">
        {liveIndices.map((i) => (
          <div className="card" key={i.data.symbol}>
            <div className="muted small">{i.data.name}</div>
            <div className="big">{i.data.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
            <div className={i.data.change_pct >= 0 ? "up" : "down"}>{signedPct(i.data.change_pct)}</div>
            <Sparkline data={i.spark} up={i.data.change_pct >= 0} />
          </div>
        ))}
      </div>

      <div className="live-grid">
        {/* watchlist */}
        <div className="panel">
          <h3>Watchlist</h3>
          <table className="grid watch">
            <tbody>
              {watchlist.map((s) => {
                const w = liveQuotes[s];
                const wUp = (w?.data.change_pct ?? 0) >= 0;
                return (
                  <tr key={s} className={s === selected ? "selected" : ""} onClick={() => setSelected(s)}>
                    <td><strong>{s}</strong><div className="muted small ellipsis">{w?.data.name ?? "…"}</div></td>
                    <td className="spark-cell">{w && <Sparkline data={w.spark} up={wUp} />}</td>
                    <td className="right">
                      {w ? <><div>{money(w.data.price)}</div><div className={wUp ? "up small" : "down small"}>{signedPct(w.data.change_pct)}</div></> : "—"}
                    </td>
                    <td><button className="link" aria-label={`Remove ${s}`} onClick={(e) => { e.stopPropagation(); setWatchlist(watchlist.filter((x) => x !== s)); }}>✕</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {watchlist.length === 0 && <p className="muted">Your watchlist is empty. Add a ticker below.</p>}
          <form className="row" onSubmit={addSymbol}>
            <input list="live-symbols" value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="Add ticker" aria-label="Add ticker" />
            <datalist id="live-symbols">{available.filter((a) => !watchlist.includes(a.symbol)).map((a) => <option key={a.symbol} value={a.symbol}>{a.name}</option>)}</datalist>
            <button className="secondary">Add</button>
          </form>
          {notice && <p className="muted small">{notice}</p>}
        </div>

        {/* detail */}
        <div className="panel">
          {q ? (
            <>
              <div className="live-head">
                <div>
                  <div className="muted small">{q.name} ({q.symbol})</div>
                  <div className="big">{money(q.price)} <span className={up ? "up" : "down"}>{up ? "▲" : "▼"} {money(Math.abs(q.change))} ({signedPct(q.change_pct)})</span></div>
                </div>
                <div className="tabs-small" role="tablist">
                  {(Object.keys(RANGES) as Range[]).map((r) => (
                    <button key={r} role="tab" aria-selected={r === range} className={r === range ? "tab active" : "tab"} onClick={() => setRange(r)}>{r}</button>
                  ))}
                </div>
              </div>

              <ResponsiveContainer width="100%" height={300}>
                {range === "1D" ? (
                  <ComposedChart data={livePoints}>
                    <defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="currentColor" stopOpacity={0.25} /><stop offset="100%" stopColor="currentColor" stopOpacity={0} /></linearGradient></defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                    <XAxis dataKey="t" minTickGap={50} />
                    <YAxis yAxisId="p" domain={["auto", "auto"]} tickFormatter={(v) => v.toFixed(2)} width={62} />
                    <YAxis yAxisId="v" orientation="right" hide domain={[0, (max: number) => max * 5]} />
                    <Tooltip formatter={(v: number, n) => (n === "Volume" ? compact(v) : money(v))} />
                    {intraday && <ReferenceLine yAxisId="p" y={intraday.prev_close} stroke="var(--muted)" strokeDasharray="4 4" label={{ value: "Prev close", position: "insideTopLeft", fill: "var(--muted)", fontSize: 11 }} />}
                    <Bar yAxisId="v" dataKey="volume" name="Volume" fill="var(--muted)" fillOpacity={0.35} isAnimationActive={false} />
                    <Area yAxisId="p" dataKey="close" name="Price" stroke={lineColor} fill={lineColor} fillOpacity={0.12} strokeWidth={2} dot={false} isAnimationActive={false} />
                  </ComposedChart>
                ) : (
                  <ComposedChart data={daily}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                    <XAxis dataKey="date" minTickGap={50} />
                    <YAxis yAxisId="p" domain={["auto", "auto"]} tickFormatter={(v) => v.toFixed(0)} width={50} />
                    <YAxis yAxisId="v" orientation="right" hide domain={[0, (max: number) => max * 5]} />
                    <Tooltip formatter={(v: number, n) => (n === "Volume" ? compact(v) : money(v))} />
                    <Legend />
                    <Bar yAxisId="v" dataKey="volume" name="Volume" fill="var(--muted)" fillOpacity={0.35} isAnimationActive={false} />
                    <Area yAxisId="p" dataKey="close" name="Price" stroke={COLORS[0]} fill={COLORS[0]} fillOpacity={0.12} strokeWidth={2} dot={false} isAnimationActive={false} />
                    {showMA && <Line yAxisId="p" dataKey="ma50" name="50-day avg" stroke={COLORS[2]} dot={false} isAnimationActive={false} />}
                    {showMA && <Line yAxisId="p" dataKey="ma200" name="200-day avg" stroke={COLORS[3]} dot={false} isAnimationActive={false} />}
                  </ComposedChart>
                )}
              </ResponsiveContainer>
              {range !== "1D" && <label className="inline small"><input type="checkbox" checked={showMA} onChange={(e) => setShowMA(e.target.checked)} /> Show moving averages</label>}

              <div className="stats">
                <Stat label="Prev close" value={q.prev_close != null ? money(q.prev_close) : "—"} />
                <Stat label="Day range" value={q.day_low != null && q.day_high != null ? `${money(q.day_low)} – ${money(q.day_high)}` : "—"} />
                <Stat label="Volume" value={compact(q.volume)} />
                <Stat label="52-wk range" value={wk52 ? `${money(wk52.lo)} – ${money(wk52.hi)}` : "…"} />
              </div>
            </>
          ) : <p className="muted">{loading ? "Loading quote…" : "Select a ticker from your watchlist."}</p>}
        </div>
      </div>

      {/* comparison + movers */}
      <div className="charts">
        <div className="panel">
          <h3>Performance comparison <span className="muted small">({range === "1D" ? "today" : range}, % change)</span></h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={compare}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis dataKey="i" hide />
              <YAxis tickFormatter={(v) => `${(v * 100).toFixed(range === "1D" ? 1 : 0)}%`} width={52} />
              <Tooltip formatter={(v: number) => signedPct(v)} labelFormatter={() => ""} />
              <Legend wrapperStyle={{ paddingTop: 8 }} />
              <ReferenceLine y={0} stroke="var(--muted)" />
              {watchlist.map((s, i) => <Line key={s} dataKey={s} stroke={COLORS[i % COLORS.length]} strokeWidth={s === selected ? 3 : 1.5} dot={false} isAnimationActive={false} />)}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="panel">
          <h3>Today's movers <span className="muted small">(your watchlist)</span></h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={movers} layout="vertical" margin={{ left: 10, right: 16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" horizontal={false} />
              <XAxis type="number" tickFormatter={(v) => `${(v * 100).toFixed(1)}%`} />
              <YAxis type="category" dataKey="symbol" width={50} />
              <Tooltip formatter={(v: number) => signedPct(v)} />
              <ReferenceLine x={0} stroke="var(--muted)" />
              <Bar dataKey="pct" name="Change" isAnimationActive={false}>{movers.map((m) => <Cell key={m.symbol} fill={m.pct >= 0 ? "var(--up)" : "var(--down)"} />)}</Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <p className="muted small">Prices move for many reasons and past moves don't predict future ones. This view is for learning how to read market data.</p>
    </section>
  );
}

const Stat = ({ label, value }: { label: string; value: string }) => (
  <div><div className="muted small">{label}</div><div>{value}</div></div>
);
