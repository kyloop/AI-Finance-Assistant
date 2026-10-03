import { useRef, useSyncExternalStore } from "react";
import type { FlowEvent, FlowStatus } from "./types";

export type NodeState = "idle" | "running" | "done" | "error";
export interface NodeRun { state: NodeState; ms?: number; status?: FlowStatus; detail?: string; runs?: number }   // runs > 1: the node ran again in a loop
export interface FlowSnapshot {
  phase: "idle" | "running" | "done" | "error";
  question: string;
  nodes: Record<string, NodeRun>;
  picked: string[] | null;          // the agents the router (and any replan round) chose; the rest are "not used" for this question
  taken: string[];                  // edges the run followed, as "from>to", in the order they were taken
  startedAt: number;                // performance.now() when the question was sent
  totalMs: number;                  // server-side time for the whole turn, once done
}

const IDLE: FlowSnapshot = { phase: "idle", question: "", nodes: {}, picked: null, taken: [], startedAt: 0, totalMs: 0 };
const FIRST = "__start__", LAST = "__end__";
/** A node stays lit at least this long, so steps that finish in a few milliseconds (basic mode) are still visible. */
const MIN_DWELL_MS = 280;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
type Queued = FlowEvent | { type: "end"; ok: boolean };

/** Plays the graph's node events onto a snapshot the panel renders. Events are applied in order, each node's end
 *  held back until its start has been visible for MIN_DWELL_MS; finish() resolves once everything has played. */
export class FlowRunner {
  private snap: FlowSnapshot = IDLE;
  private listeners = new Set<() => void>();
  private queue: Queued[] = [];
  private began: Record<string, number> = {};
  private lastT = 0;
  // LangGraph runs in supersteps: the nodes that start together were triggered by the nodes that finished in the step before.
  private prevStep: string[] = [];        // the nodes that finished just before the current step started
  private stepEnds: string[] = [];        // the nodes that have finished since the current step started
  private lastWasEnd = true;
  private pumping = false;
  private waiters: (() => void)[] = [];
  private turn = 0;

  subscribe = (l: () => void) => { this.listeners.add(l); return () => { this.listeners.delete(l); }; };
  getSnapshot = () => this.snap;

  begin(question: string) {
    this.turn++; this.queue = []; this.began = {}; this.lastT = 0; this.pumping = false;
    this.prevStep = []; this.stepEnds = [FIRST]; this.lastWasEnd = true;
    this.waiters.splice(0).forEach((w) => w());
    this.set({ ...IDLE, phase: "running", question, startedAt: performance.now() });
  }
  push(ev: FlowEvent) { this.queue.push(ev); void this.pump(); }
  /** Mark the turn finished (ok = an answer arrived). Resolves when the animation has caught up with the server. */
  finish(ok: boolean): Promise<void> {
    this.queue.push({ type: "end", ok });
    void this.pump();
    return new Promise((r) => (this.pumping || this.queue.length ? this.waiters.push(r) : r()));
  }

  private set(next: FlowSnapshot) { this.snap = next; this.listeners.forEach((l) => l()); }

  private async pump() {
    if (this.pumping) return;
    this.pumping = true;
    const turn = this.turn;
    while (this.queue.length) {
      const ev = this.queue[0];
      if (ev.type === "node_end") {
        const wait = (this.began[ev.node] ?? 0) + MIN_DWELL_MS - performance.now();
        if (wait > 0) await sleep(wait);
      }
      if (turn !== this.turn) return;                     // begin() started a new turn while we waited
      this.queue.shift();
      this.apply(ev);
    }
    this.pumping = false;
    this.waiters.splice(0).forEach((w) => w());
  }

  private apply(ev: Queued) {
    const s = this.snap;
    if (ev.type === "node_start") {
      this.began[ev.node] = performance.now(); this.lastT = ev.t;
      if (this.lastWasEnd) { this.prevStep = this.stepEnds; this.stepEnds = []; this.lastWasEnd = false; }   // a new superstep
      const runs = (s.nodes[ev.node]?.runs ?? 0) + 1;
      this.set({ ...s, taken: [...s.taken, ...this.prevStep.map((p) => `${p}>${ev.node}`)],
        nodes: { ...s.nodes, [ev.node]: { state: "running", runs } } });
    } else if (ev.type === "node_end") {
      this.lastT = ev.t; this.stepEnds.push(ev.node); this.lastWasEnd = true;
      const picked = ev.picked ? [...new Set([...(s.picked ?? []), ...ev.picked])] : s.picked;   // replan adds to the router's pick
      this.set({ ...s, picked,
        nodes: { ...s.nodes, [ev.node]: { state: ev.status === "error" ? "error" : "done", ms: ev.ms, status: ev.status, detail: ev.detail, runs: s.nodes[ev.node]?.runs } } });
    } else {
      this.set({ ...s, phase: ev.ok ? "done" : "error", totalMs: Math.round(this.lastT * 1000),
        taken: ev.ok ? [...s.taken, ...this.stepEnds.map((p) => `${p}>${LAST}`)] : s.taken });
    }
  }
}

export function useFlowRunner(): [FlowRunner, FlowSnapshot] {
  const ref = useRef<FlowRunner>();
  if (!ref.current) ref.current = new FlowRunner();
  const snap = useSyncExternalStore(ref.current.subscribe, ref.current.getSnapshot);
  return [ref.current, snap];
}
