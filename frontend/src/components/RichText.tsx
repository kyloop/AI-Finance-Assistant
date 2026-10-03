import { useState, type ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { COLORS } from "./common";

/** Safe Markdown subset for assistant answers. No raw HTML.
 *  Blocks: paragraphs, # headings, "- " and "1. " lists, | tables |, ``` code ```, > quotes, and ```chart JSON``` blocks.
 *  Inline: **bold**, _italic_ / *italic*, `code`, [links](https://…), signed percentages coloured up/down.
 *  A table whose columns after the first are all numbers gets a Chart / Table toggle. */

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|(?<![\w*])\*[^*\s][^*]*\*(?!\w)|(?<!\w)_[^_]+_(?!\w)|(?<![\w.])[+\-−]\d[\d,]*(?:\.\d+)?%)/g;

function inline(text: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={i}>{inline(part.slice(2, -2))}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={i}>{part.slice(1, -1)}</code>;
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
    if (link) return <a key={i} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    if (part.length > 2 && ((part.startsWith("_") && part.endsWith("_")) || (part.startsWith("*") && part.endsWith("*")))) return <em key={i}>{part.slice(1, -1)}</em>;
    if (/^[+\-−]\d[\d,]*(?:\.\d+)?%$/.test(part)) return <span key={i} className={`num ${part[0] === "+" ? "up" : "down"}`}>{part}</span>;
    return part;
  });
}

/** "$1,234.50", "12.5%", "−3", "(4.2)" -> number; anything else -> NaN. */
export function parseNum(s: string): number {
  const t = s.replace(/\*\*/g, "").trim();
  const neg = /^\(.*\)$/.test(t) || /^[-−]/.test(t);
  const core = t.replace(/[()$€£¥,%\s+\-−]/g, "");
  if (!/^\d+(\.\d+)?[kKmMbB]?$/.test(core)) return NaN;
  const mult = { k: 1e3, m: 1e6, b: 1e9 }[core.slice(-1).toLowerCase()] ?? 1;
  const n = parseFloat(core) * mult;
  return neg ? -n : n;
}

const splitRow = (line: string) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const isSeparator = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);

// ------------------------------------------------------------------ charts
export interface ChartSpec { type?: "line" | "bar" | "pie"; title?: string; x: string; y: string[]; data: Record<string, string | number>[]; unit?: string }

const fmtTick = (unit?: string) => (v: number) => {
  const a = Math.abs(v);
  const s = a >= 1e9 ? `${+(v / 1e9).toFixed(1)}B` : a >= 1e6 ? `${+(v / 1e6).toFixed(1)}M` : a >= 1e3 ? `${+(v / 1e3).toFixed(1)}k` : `${+v.toFixed(2)}`;
  return unit === "$" ? `$${s}` : unit === "%" ? `${s}%` : s;
};
const fmtFull = (unit?: string) => (v: number) =>
  unit === "$" ? v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 })
  : `${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}${unit === "%" ? "%" : ""}`;

export function ChatChart({ spec }: { spec: ChartSpec }) {
  const { type = "line", title, x, y, data, unit } = spec;
  const tip = <Tooltip formatter={(v: number) => fmtFull(unit)(v)} contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }} />;
  const axes = <>
    <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
    <XAxis dataKey={x} tick={{ fontSize: 11, fill: "var(--muted)" }} stroke="var(--line)" />
    <YAxis tickFormatter={fmtTick(unit)} tick={{ fontSize: 11, fill: "var(--muted)" }} stroke="var(--line)" width={52} />
  </>;
  const legend = y.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />;
  return (
    <figure className="chat-chart">
      {title && <figcaption>{title}</figcaption>}
      <ResponsiveContainer width="100%" height={220}>
        {type === "pie" ? (
          <PieChart>
            <Pie data={data} dataKey={y[0]} nameKey={x} outerRadius={80} label={(d) => d.name}>
              {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Pie>{tip}
          </PieChart>
        ) : type === "bar" ? (
          <BarChart data={data}>{axes}{tip}{legend}
            {y.map((k, i) => <Bar key={k} dataKey={k} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} />)}
          </BarChart>
        ) : (
          <LineChart data={data}>{axes}{tip}{legend}
            {y.map((k, i) => <Line key={k} dataKey={k} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={data.length <= 12} />)}
          </LineChart>
        )}
      </ResponsiveContainer>
    </figure>
  );
}

function parseChart(src: string): ChartSpec | null {
  try {
    const s = JSON.parse(src);
    if (!Array.isArray(s.data) || !s.data.length || typeof s.x !== "string") return null;
    const y: string[] = Array.isArray(s.y) ? s.y : typeof s.y === "string" ? [s.y] : Object.keys(s.data[0]).filter((k) => k !== s.x);
    const data = s.data.map((r: Record<string, unknown>) => Object.fromEntries(Object.entries(r).map(([k, v]) =>
      [k, k !== s.x && typeof v === "string" && !isNaN(parseNum(v)) ? parseNum(v) : v])));
    return { type: s.type, title: s.title, x: s.x, y, data, unit: s.unit };
  } catch { return null; }
}

/** A table is chartable when it has 3+ rows and every cell outside the first column is a number. */
function tableChart(head: string[], rows: string[][]): ChartSpec | null {
  if (rows.length < 3 || head.length < 2) return null;
  if (!rows.every((r) => r.slice(1, head.length).every((c) => !isNaN(parseNum(c))))) return null;
  const sample = rows[0].slice(1).join(" ");
  const unit = sample.includes("$") ? "$" : sample.includes("%") ? "%" : undefined;
  const timeLike = /year|month|age|date|period|quarter/i.test(head[0]) || rows.every((r) => !isNaN(parseNum(r[0])));
  const x = head[0] || "Item";
  return { type: timeLike ? "line" : "bar", x, y: head.slice(1), unit,
           data: rows.map((r) => Object.fromEntries([[x, r[0]], ...head.slice(1).map((h, i) => [h, parseNum(r[i + 1])])])) };
}

function Table({ head, align, rows }: { head: string[]; align: string[]; rows: string[][] }) {
  const chart = tableChart(head, rows);
  const [view, setView] = useState<"chart" | "table">(chart && rows.length >= 4 ? "chart" : "table");
  const numeric = head.map((_, c) => rows.every((r) => !r[c] || !isNaN(parseNum(r[c]))));
  return (
    <div className="chat-table">
      {chart && (
        <div className="chat-table-toggle" role="group" aria-label="Show as">
          {(["chart", "table"] as const).map((v) => <button key={v} type="button" className={view === v ? "active" : ""} aria-pressed={view === v} onClick={() => setView(v)}>{v === "chart" ? "Chart" : "Table"}</button>)}
        </div>
      )}
      {chart && view === "chart" ? <ChatChart spec={chart} /> : (
        <div className="table-scroll">
          <table>
            <thead><tr>{head.map((h, i) => <th key={i} className={align[i] || (numeric[i] && i > 0 ? "right" : "")}>{inline(h)}</th>)}</tr></thead>
            <tbody>{rows.map((r, ri) => <tr key={ri}>{head.map((_, ci) => <td key={ci} className={align[ci] || (numeric[ci] && ci > 0 ? "right num" : "")}>{inline(r[ci] ?? "")}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ blocks
export default function RichText({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  const key = () => `b${blocks.length}`;
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^\s*```\s*(\w*)/);
    if (fence) {
      const body: string[] = [];
      for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) body.push(lines[i]);
      i++;
      const spec = fence[1] === "chart" ? parseChart(body.join("\n")) : null;
      blocks.push(spec ? <ChatChart key={key()} spec={spec} /> : <pre key={key()}><code>{body.join("\n")}</code></pre>);
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && isSeparator(lines[i + 1])) {
      const head = splitRow(line);
      const align = splitRow(lines[i + 1]).map((c) => (c.endsWith(":") ? (c.startsWith(":") ? "center" : "right") : ""));
      const rows: string[][] = [];
      for (i += 2; i < lines.length && lines[i].includes("|") && lines[i].trim(); i++) rows.push(splitRow(lines[i]));
      blocks.push(<Table key={key()} head={head} align={align} rows={rows} />);
      continue;
    }
    const h = line.match(/^\s*(#{1,4})\s+(.*)$/);
    if (h) { blocks.push(<div key={key()} className={`rich-h rich-h${h[1].length}`} role="heading" aria-level={Math.min(6, h[1].length + 2)}>{inline(h[2])}</div>); i++; continue; }
    const listRe = /^\s*([-•*]|\d+[.)])\s+(.*)$/;
    const li = line.match(listRe);
    if (li) {
      const ordered = /\d/.test(li[1]);
      const items: string[] = [];
      for (; i < lines.length; i++) {
        const m = lines[i].match(listRe);
        if (!m || /\d/.test(m[1]) !== ordered) break;
        items.push(m[2]);
      }
      const Tag = ordered ? "ol" : "ul";
      blocks.push(<Tag key={key()}>{items.map((b, j) => <li key={j}>{inline(b)}</li>)}</Tag>);
      continue;
    }
    if (/^\s*>\s?/.test(line)) {
      const q: string[] = [];
      for (; i < lines.length && /^\s*>\s?/.test(lines[i]); i++) q.push(lines[i].replace(/^\s*>\s?/, ""));
      blocks.push(<blockquote key={key()}>{q.map((l, j) => <p key={j}>{inline(l)}</p>)}</blockquote>);
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { blocks.push(<hr key={key()} />); i++; continue; }
    if (line.trim()) blocks.push(<p key={key()}>{inline(line)}</p>);
    i++;
  }
  return <div className="rich">{blocks}</div>;
}
