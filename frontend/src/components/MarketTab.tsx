import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { Envelope, HistoryPoint, NewsItem, Quote } from "../types";
import { COLORS, ErrorBanner, FreshnessBadge } from "./common";

export default function MarketTab() {
  const [symbol, setSymbol] = useState("AAPL");
  const [input, setInput] = useState("AAPL");
  const [quote, setQuote] = useState<Envelope<Quote> | null>(null);
  const [points, setPoints] = useState<HistoryPoint[]>([]);
  const [indices, setIndices] = useState<Envelope<Quote>[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.indices().then(setIndices).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    setError(null);
    if (!symbol) { setQuote(null); setPoints([]); return; }       // no stock picked: market news only
    Promise.all([api.quote(symbol), api.history(symbol)])
      .then(([q, h]) => { setQuote(q); setPoints(h.data.points); })
      .catch((e) => { setError(e.message); setQuote(null); setPoints([]); });
  }, [symbol]);

  return (
    <section>
      <div className="cards">
        {indices.map((i) => <Change key={i.data.symbol} q={i.data} env={i} />)}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); setSymbol(input.trim().toUpperCase()); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ticker, e.g. AAPL (blank = market news)" aria-label="Ticker" />
        <button>Look up</button>
        <button type="button" className="secondary" onClick={() => { setInput(""); setSymbol(""); }}>Market news</button>
      </form>
      <ErrorBanner message={error} />
      {quote && (
        <>
          <div className="card wide">
            <div className="muted small">{quote.data.name} ({quote.data.symbol}) <FreshnessBadge freshness={quote.freshness} provider={quote.provider} fetchedAt={quote.fetched_at} /></div>
            <div className="big">${quote.data.price.toFixed(2)} <Delta v={quote.data.change_pct} /></div>
            <div className="muted small">Volume {quote.data.volume.toLocaleString()}</div>
          </div>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={points}>
              <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="date" minTickGap={40} /><YAxis domain={["auto", "auto"]} /><Tooltip /><Legend />
              <Line dataKey="close" name="Price" stroke={COLORS[0]} dot={false} />
              <Line dataKey="ma50" name="50-day avg" stroke={COLORS[2]} dot={false} />
              <Line dataKey="ma200" name="200-day avg" stroke={COLORS[3]} dot={false} />
            </LineChart>
          </ResponsiveContainer>
          <p className="muted small">Moving averages smooth out daily noise: price above its long-term average is often read as an uptrend, but it predicts nothing.</p>
        </>
      )}
      <NewsSection symbol={symbol} />
    </section>
  );
}

const NEWS_POLL_MS = 60_000;     // Yahoo has no news stream, so poll; the server caches for 5 min so this is cheap

function ago(iso: string | null): string {
  if (!iso) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  return mins < 60 ? `${mins}m ago` : mins < 1440 ? `${Math.round(mins / 60)}h ago` : `${Math.round(mins / 1440)}d ago`;
}

function NewsSection({ symbol }: { symbol: string }) {
  const [env, setEnv] = useState<Envelope<{ symbol: string; items: NewsItem[] }> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setEnv(null); setError(null); setLoading(true);
    const load = () => api.news(symbol || undefined)
      .then((e) => { if (alive) { setEnv(e); setError(null); } })
      .catch((e) => { if (alive) setError(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    load();
    const id = setInterval(load, NEWS_POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, [symbol]);

  const items = env?.data.items ?? [];
  return (
    <div className="news">
      <h3>{symbol ? `${symbol} news` : "Market news"} {env && <FreshnessBadge freshness={env.freshness} provider={env.provider} fetchedAt={env.fetched_at} />}</h3>
      <ErrorBanner message={error} />
      {loading && !env && <p className="muted small">Loading news…</p>}
      {env && items.length === 0 && <p className="muted small">No news available right now.</p>}
      <ul className="news-list">
        {items.map((n) => (
          <li key={n.id} className="card news-item">
            {n.thumbnail && <img src={n.thumbnail} alt="" loading="lazy" />}
            <div>
              <a href={n.url} target="_blank" rel="noopener noreferrer">{n.title}</a>
              {n.summary && <p className="muted small">{n.summary.length > 220 ? `${n.summary.slice(0, 220)}…` : n.summary}</p>}
              <div className="muted small">{[n.publisher, ago(n.published)].filter(Boolean).join(" · ")}</div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

const Delta = ({ v }: { v: number }) => <span className={v >= 0 ? "up" : "down"}>{v >= 0 ? "▲" : "▼"} {(Math.abs(v) * 100).toFixed(2)}%</span>;
const Change = ({ q, env }: { q: Quote; env: Envelope<Quote> }) => (
  <div className="card"><div className="muted small">{q.name}</div><div className="big">{q.price.toLocaleString()}</div><Delta v={q.change_pct} /> <FreshnessBadge freshness={env.freshness} /></div>
);
