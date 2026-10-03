import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { api } from "../api";
import type { FlowSnapshot, NodeRun } from "../flow";
import type { FlowEdge, FlowNode } from "../types";
import FlowEdges, { END, START } from "./FlowEdges";

const OPEN_KEY = "finnie_flow_open";
const HEIGHT_KEY = "finnie_flow_height";
const CLOSED_H = 38, MIN_H = 120, DEFAULT_H = 188, STEP = 24;
const MAX_ZOOM = 2.5;
const TEXT_KEY = "finnie_flow_text";
const TEXT_MIN = 0.5, TEXT_MAX = 1.5, TEXT_STEP = 0.1, TEXT_DEFAULT = 0.85;      // relative to the node's normal size
const BOX_KEY = "finnie_flow_box";
const BOX_MIN = 0.6, BOX_MAX = 2, BOX_STEP = 0.1, BOX_DEFAULT = 1;               // size of the squares, 1 = normal
const AGENT_H = 30;                                                               // px height of an agent square at BOX_DEFAULT (see styles.css)
const stepper = (key: string, min: number, max: number, fallback: number) => ({
  clamp: (v: number) => Math.min(max, Math.max(min, Math.round(v * 100) / 100)),
  load() { const n = Number(localStorage.getItem(key)); return n ? this.clamp(n) : fallback; },
});
const textSize = stepper(TEXT_KEY, TEXT_MIN, TEXT_MAX, TEXT_DEFAULT);
const boxSize = stepper(BOX_KEY, BOX_MIN, BOX_MAX, BOX_DEFAULT);

function Stepper({ label, noun, value, min, max, step, fallback, minus, plus, onChange }: { label: string; noun: string; value: number; min: number; max: number; step: number; fallback: number; minus: string; plus: string; onChange: (v: number) => void }) {
  return (
    <div className="flow-text" role="group" aria-label={`${label} in the agent flow`}>
      <span className="muted small">{label}</span>
      <button className="secondary" aria-label={`Smaller ${noun}`} title={`Smaller ${noun}`} disabled={value <= min} onClick={() => onChange(value - step)}>{minus}</button>
      <button className="secondary flow-text-val" aria-label={`Reset ${noun} size`} title={`Reset ${noun} size`} onClick={() => onChange(fallback)}>{Math.round(value * 100)}%</button>
      <button className="secondary" aria-label={`Larger ${noun}`} title={`Larger ${noun}`} disabled={value >= max} onClick={() => onChange(value + step)}>{plus}</button>
    </div>
  );
}
const maxHeight = () => Math.max(MIN_H, Math.round(window.innerHeight * 0.85));
const clampHeight = (h: number) => Math.min(maxHeight(), Math.max(MIN_H, Math.round(h)));
const loadHeight = () => { const n = Number(localStorage.getItem(HEIGHT_KEY)); return n ? clampHeight(n) : DEFAULT_H; };
const secs = (ms: number) => `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`;
const SHORT: Record<string, string> = { not_found: "not found", need_info: "needs info", error: "failed" };

type View = "idle" | "running" | "done" | "error" | "skipped";

function viewOf(node: FlowNode, run: NodeRun | undefined, s: FlowSnapshot): View {
  if (run && run.state !== "idle") return run.state;
  if (s.phase === "done" || s.phase === "error") return "skipped";                       // never ran for this question
  if (node.kind === "agent" && s.picked && !s.picked.includes(node.id)) return "skipped"; // router chose other agents
  return "idle";
}

function NodeCard({ node, run, view }: { node: FlowNode; run?: NodeRun; view: View }) {
  const again = (run?.runs ?? 0) > 1 ? ` ×${run!.runs}` : "";                       // ran more than once (the verifier/replan loop)
  const meta = (run?.state === "done" || run?.state === "error"
    ? (run.status && SHORT[run.status]) || secs(run.ms ?? 0)
    : view === "running" ? "working…" : view === "skipped" && node.kind === "step" ? "not used" : "") + (run ? again : "");
  const label = `${node.label} (${view === "skipped" ? "not used" : view}${run?.detail ? `: ${run.detail}` : ""}). ${node.description}`;
  return (
    <div data-flow-id={node.id} className={`flow-node ${node.kind} ${view}${run?.status && run.status !== "ok" && run.status !== "answered" ? ` st-${run.status}` : ""}`} title={label} aria-label={label}>
      <span className="flow-dot" aria-hidden="true" />
      <span className="flow-name">{node.label}</span>
      <span className="flow-meta">{meta}</span>
    </div>
  );
}

function Cap({ id, label, sub, view }: { id: string; label: string; sub?: string; view: View }) {
  return (
    <div data-flow-id={id} className={`flow-cap ${view}`} title={sub}>
      <span className="flow-name">{label}</span>
      {sub && <span className="flow-meta">{sub}</span>}
    </div>
  );
}

export default function AgentFlow({ state }: { state: FlowSnapshot }) {
  const [nodes, setNodes] = useState<FlowNode[] | null>(null);
  const [edges, setEdges] = useState<FlowEdge[]>([]);
  const canvas = useRef<HTMLDivElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) !== "0");
  const [height, setHeight] = useState(loadHeight);
  const [text, setText] = useState(() => textSize.load());
  const [box, setBox] = useState(() => boxSize.load());
  const [scale, setScale] = useState(1);
  const [size, setSize] = useState({ w: 0, h: 0 });          // the diagram at scale 1
  const drag = useRef<{ y: number; h: number } | null>(null);
  const [now, setNow] = useState(0);
  useEffect(() => { api.flowLayout().then((r) => { setEdges(r.edges); setNodes(r.nodes); }).catch(() => setNodes([])); }, []);
  useEffect(() => {                                       // keep the page's scroll area clear of the fixed dock
    document.documentElement.style.setProperty("--flow-h", `${open ? height : CLOSED_H}px`);
    return () => { document.documentElement.style.removeProperty("--flow-h"); };
  }, [open, height]);
  useEffect(() => {
    const onResize = () => setHeight((h) => clampHeight(h));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  useLayoutEffect(() => {                                 // scale the diagram to the dock's height, whatever size it is dragged to
    const t = track.current, c = canvas.current;
    if (!open || !t || !c) return;
    const fit = () => {
      const w = c.offsetWidth, h = c.offsetHeight;
      if (!w || !h) return;
      setSize({ w, h });
      const rows = Math.ceil((nodes ?? []).filter((n) => n.kind === "agent").length / 2);          // the agent grid sets the diagram's height
      const normalH = h - rows * AGENT_H * (box - 1);                                              // ...as it would be at 100% boxes: box size doesn't change the zoom
      setScale(Math.min(MAX_ZOOM, Math.max(0.45, (t.clientHeight - 16) / normalH)));              // as tall as the dock allows; wider than the screen scrolls sideways
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(t); ro.observe(c);
    return () => ro.disconnect();
  }, [open, height, nodes, text, box]);
  useEffect(() => {
    if (state.phase !== "running") return;
    const t = window.setInterval(() => setNow(performance.now() - state.startedAt), 100);
    return () => window.clearInterval(t);
  }, [state.phase, state.startedAt]);
  const setTextSaved = (t: number) => { const v = textSize.clamp(t); setText(v); localStorage.setItem(TEXT_KEY, String(v)); };
  const setBoxSaved = (b: number) => { const v = boxSize.clamp(b); setBox(v); localStorage.setItem(BOX_KEY, String(v)); };
  const setOpenSaved = (o: boolean) => { localStorage.setItem(OPEN_KEY, o ? "1" : "0"); setOpen(o); };
  const toggle = () => setOpenSaved(!open);
  const resize = (h: number) => { const v = clampHeight(h); setHeight(v); localStorage.setItem(HEIGHT_KEY, String(v)); };
  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    if (!open) setOpenSaved(true);
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { y: e.clientY, h: open ? height : CLOSED_H };
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => { if (drag.current) setHeight(clampHeight(drag.current.h + drag.current.y - e.clientY)); };
  const onUp = () => { if (drag.current) { drag.current = null; resize(height); } };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const next = e.key === "ArrowUp" ? height + STEP : e.key === "ArrowDown" ? height - STEP : e.key === "Home" ? MIN_H : e.key === "End" ? maxHeight() : null;
    if (next === null) return;
    e.preventDefault();
    if (!open) setOpenSaved(true);
    resize(next);
  };

  const stages = new Map<number, FlowNode[]>();
  (nodes ?? []).forEach((n) => stages.set(n.stage, [...(stages.get(n.stage) ?? []), n]));
  const label = (id: string) => nodes?.find((n) => n.id === id)?.label ?? id;
  const running = Object.entries(state.nodes).filter(([, r]) => r.state === "running").map(([id]) => label(id));
  const agentsUsed = nodes?.filter((n) => n.kind === "agent" && state.nodes[n.id]?.state === "done").map((n) => n.label) ?? [];

  const status =
    state.phase === "idle" ? "Ask a question in the chat to watch the agents work on it."
    : state.phase === "running" ? (running.length ? `Working: ${running.join(" + ")}` : "Starting…")
    : state.phase === "done" ? `Answered${agentsUsed.length ? ` via ${agentsUsed.join(" + ")}` : ""}`
    : "Something went wrong";
  const elapsed = state.phase === "running" ? secs(now) : state.phase === "done" ? secs(state.totalMs) : "";
  const started = state.phase !== "idle";

  return (
    <section className={`flow-dock ${open ? "" : "collapsed"}`} style={{ height: open ? height : CLOSED_H }} aria-label="Agent flow">
      <div className="flow-resize" role="separator" aria-orientation="horizontal" aria-label="Resize agent flow: drag, or use the up and down arrow keys; double-click to hide or show"
        aria-valuemin={MIN_H} aria-valuemax={maxHeight()} aria-valuenow={open ? height : CLOSED_H} tabIndex={0} title="Drag to resize · double-click to hide or show"
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp} onKeyDown={onKey} onDoubleClick={toggle}><span /></div>
      <div className="flow-head">
        <strong>Agent flow</strong>
        <span className={`flow-status ${state.phase}`} role="status">{status}</span>
        {elapsed && <span className="flow-time muted small">{elapsed}</span>}
        {open && (
          <>
            <Stepper label="Text" noun="text" value={text} min={TEXT_MIN} max={TEXT_MAX} step={TEXT_STEP} fallback={TEXT_DEFAULT} minus="A−" plus="A+" onChange={setTextSaved} />
            <Stepper label="Boxes" noun="boxes" value={box} min={BOX_MIN} max={BOX_MAX} step={BOX_STEP} fallback={BOX_DEFAULT} minus="−" plus="+" onChange={setBoxSaved} />
          </>
        )}
        <button className="secondary flow-toggle" aria-expanded={open} onClick={toggle}>{open ? "Hide ▾" : "Show ▴"}</button>
      </div>
      {open && (
        <div className="flow-track" ref={track}>
          {nodes === null ? <span className="muted small">Loading…</span> : nodes.length === 0 ? <span className="muted small">The agent flow isn't available.</span> : (
            <div className="flow-scale" style={{ width: size.w * scale || undefined, height: size.h * scale || undefined }}>
            <div className="flow-canvas" ref={canvas} style={{ transform: `scale(${scale})`, fontSize: `${text}rem`, "--b": box } as CSSProperties}>
              <FlowEdges edges={edges} nodes={nodes} snap={state} canvas={canvas} scale={scale} version={`${nodes.length}:${open}:${state.question}:${scale}`} />
              <Cap id={START} label="You" sub={state.question.length > 18 ? `${state.question.slice(0, 17)}…` : state.question} view={started ? "done" : "idle"} />
              {[...stages.keys()].sort((a, b) => a - b).map((stage) => (
                <div className={stages.get(stage)!.length > 1 ? "flow-col multi" : "flow-col"} key={stage}>
                  {stages.get(stage)!.map((n) => <NodeCard key={n.id} node={n} run={state.nodes[n.id]} view={viewOf(n, state.nodes[n.id], state)} />)}
                </div>
              ))}
              <Cap id={END} label="Answer" view={state.phase === "done" ? "done" : state.phase === "error" ? "error" : "idle"} />
            </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
