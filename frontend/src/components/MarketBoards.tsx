import { useEffect, useState } from "react";
import type { DependencyList, ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { Board, BoardItem, BoardRange } from "../types";
import { FreshnessBadge } from "./common";

const RANGES: BoardRange[] = ["1D", "1M", "3M", "YTD", "1Y"];
const DEFAULT_SECTOR = "XLK";
const POLL_MS = 60_000;                  // the server's poller refreshes the charts' data every minute; reloads read its cache
const signedPct = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
const compact = (n: number) => Intl.NumberFormat("en-US", { notation: "compact" }).format(n);

interface Loaded { board: Board | null; error: string | null; loading: boolean }

/** One board from the API, reloaded when `deps` change (and every `pollMs` when set); the last board stays shown while reloading. */
function useBoard(load: () => Promise<Board>, deps: DependencyList, pollMs = 0): Loaded {
  const [state, setState] = useState<Loaded>({ board: null, error: null, loading: true });
  useEffect(() => {
    let alive = true;
    const run = () => load()
      .then((board) => { if (alive) setState({ board, error: null, loading: false }); })
      .catch((e: Error) => { if (alive) setState((s) => ({ board: s.board, error: e.message, loading: false })); });
    setState((s) => ({ ...s, loading: true }));
    run();
    const id = pollMs ? window.setInterval(run, pollMs) : 0;
    return () => { alive = false; if (id) window.clearInterval(id); };
  }, deps);                                                 // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}

/** The Live Market tab's market overview: sectors (click one for its industries and news), the largest companies, regions and
 * today's most active stocks. One range selector drives every chart but the most-active list, which is always today's. */
export default function MarketBoards({ newsSector, onSectorNews }: { newsSector: string; onSectorNews: (fund: string) => void }) {
  const [range, setRange] = useState<BoardRange>("1M");
  const [sector, setSector] = useState(DEFAULT_SECTOR);
  const sectors = useBoard(() => api.board("sectors", range), [range], POLL_MS);
  const industries = useBoard(() => api.industries(sector, range), [sector, range], POLL_MS);
  const largest = useBoard(() => api.board("largest", range), [range], POLL_MS);
  const regions = useBoard(() => api.board("regions", range), [range], POLL_MS);
  const active = useBoard(() => api.mostActive(), [], POLL_MS);
  const sectorName = sectors.board?.items.find((i) => i.symbol === sector)?.name ?? industries.board?.sector?.name ?? sector;

  return (
    <div className="boards">
      <div className="boards-head">
        <h3>Market overview <span className="muted small">(% change, {sectors.board?.label ?? range})</span></h3>
        <div className="tabs-small" role="tablist" aria-label="Period for the market overview charts">
          {RANGES.map((r) => (
            <button key={r} role="tab" aria-selected={r === range} className={r === range ? "tab active" : "tab"} onClick={() => setRange(r)}>{r}</button>
          ))}
        </div>
      </div>
      <div className="charts">
        <BoardPanel title="Sector performance" hint="Each sector is measured by its SPDR sector fund. Click a sector to see its industries." state={sectors}>
          {sectors.board && <ReturnBars items={sectors.board.items} label={(i) => `${i.name} (${i.symbol})`} labelWidth={170}
                                        selected={sector} onPick={setSector} range={range} />}
          {sectors.board && (
            <button className="secondary small" disabled={newsSector === sector} onClick={() => onSectorNews(sector)}>
              {newsSector === sector ? `Showing ${sectorName} news below` : `Show ${sectorName} news`}
            </button>
          )}
        </BoardPanel>
        <BoardPanel title={`Industries in ${sectorName}`} hint="Yahoo's industry indices; the share is each industry's weight in the sector." state={industries}>
          {industries.board && <ReturnBars items={industries.board.items} labelWidth={190} range={range}
                                           label={(i) => `${i.name}${i.weight != null ? ` · ${(i.weight * 100).toFixed(0)}%` : ""}`} />}
        </BoardPanel>
        <BoardPanel title="Largest companies" hint="The 10 largest US-listed companies by market value, in that order." state={largest}>
          {largest.board && <ReturnBars items={largest.board.items} labelWidth={150} range={range}
                                        label={(i) => `${i.symbol}${i.market_cap ? ` · $${compact(i.market_cap)}` : ""}`} />}
        </BoardPanel>
        <BoardPanel title="Region performance" hint="Each country's or area's main stock index, in its own currency." state={regions}>
          {regions.board && <ReturnBars items={regions.board.items} label={(i) => `${i.region} · ${i.name}`} labelWidth={190} range={range} />}
        </BoardPanel>
      </div>
      <BoardPanel title="Most active stocks today" hint="The 20 stocks with the most shares traded today; bar colour shows today's change." state={active}>
        {active.board && <VolumeBars items={active.board.items} />}
      </BoardPanel>
    </div>
  );
}

function BoardPanel({ title, hint, state, children }: { title: string; hint: string; state: Loaded; children?: ReactNode }) {
  const b = state.board;
  const dates = b?.start_date && b.end_date ? `${b.start_date} to ${b.end_date}` : null;
  return (
    <div className="panel board">
      <h3>
        {title}{" "}
        {b?.freshness && <FreshnessBadge freshness={b.freshness} provider={b.provider ?? undefined} fetchedAt={b.as_of ?? undefined} />}
        {state.loading && b && <span className="muted small"> updating…</span>}
      </h3>
      <p className="muted small">{hint}{dates && ` ${dates}.`}</p>
      {state.error && <p className="muted small">{state.error}</p>}
      {state.loading && !b && !state.error && <p className="muted small">Loading…</p>}
      {b && b.items.length === 0 && <p className="muted small">No figures available right now.</p>}
      {children}
      {b && b.missing.length > 0 && <p className="muted small">No figures for: {b.missing.join(", ")}.</p>}
    </div>
  );
}

/** Horizontal bars of each item's return, in the order given (the first at the top): green up, red down. With `onPick`, a bar is
 * clickable and the `selected` one stays bright. */
function ReturnBars({ items, label, labelWidth, range, selected, onPick }: {
  items: BoardItem[]; label: (i: BoardItem) => string; labelWidth: number; range: BoardRange;
  selected?: string; onPick?: (symbol: string) => void;
}) {
  const rows = items.filter((i) => i.return != null).map((i) => ({ id: i.symbol, name: i.name, label: label(i), value: i.return as number }));
  const digits = range === "1D" ? 1 : 0;
  return (
    <ResponsiveContainer width="100%" height={Math.max(160, rows.length * 26 + 40)}>
      <BarChart data={rows} layout="vertical" margin={{ left: 4, right: 16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" horizontal={false} />
        <XAxis type="number" tickFormatter={(v: number) => `${(v * 100).toFixed(digits)}%`} />
        <YAxis type="category" dataKey="label" width={labelWidth} interval={0} tick={{ fontSize: 12 }} />
        <Tooltip formatter={(v: number) => signedPct(v)} labelFormatter={(l: string) => rows.find((r) => r.label === l)?.name ?? l} />
        <ReferenceLine x={0} stroke="var(--muted)" />
        <Bar dataKey="value" name="Change" isAnimationActive={false} cursor={onPick ? "pointer" : undefined}
             onClick={onPick ? (d: { id?: string }) => d.id && onPick(d.id) : undefined}>
          {rows.map((r) => (
            <Cell key={r.id} fill={r.value >= 0 ? "var(--up)" : "var(--down)"} fillOpacity={selected && r.id !== selected ? 0.45 : 1} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Today's most active stocks: bar length is shares traded, colour is today's change. */
function VolumeBars({ items }: { items: BoardItem[] }) {
  const rows = items.map((i) => ({ label: i.symbol, name: i.name, volume: i.volume ?? 0, change: i.change_pct ?? 0, price: i.price }));
  return (
    <ResponsiveContainer width="100%" height={Math.max(200, rows.length * 24 + 40)}>
      <BarChart data={rows} layout="vertical" margin={{ left: 4, right: 16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" horizontal={false} />
        <XAxis type="number" tickFormatter={(v: number) => compact(v)} />
        <YAxis type="category" dataKey="label" width={60} interval={0} tick={{ fontSize: 12 }} />
        <Tooltip content={({ active, payload }) => {
          const r = active && payload?.[0]?.payload as (typeof rows)[number] | undefined;
          if (!r) return null;
          return (
            <div className="card small">
              <strong>{r.name} ({r.label})</strong>
              <div>{compact(r.volume)} shares traded</div>
              <div className={r.change >= 0 ? "up" : "down"}>{signedPct(r.change)} today{r.price != null ? ` · $${r.price.toFixed(2)}` : ""}</div>
            </div>
          );
        }} />
        <Bar dataKey="volume" name="Shares traded" isAnimationActive={false}>
          {rows.map((r) => <Cell key={r.label} fill={r.change >= 0 ? "var(--up)" : "var(--down)"} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
