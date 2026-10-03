import { useLayoutEffect, useMemo, useState, type RefObject } from "react";
import type { FlowSnapshot } from "../flow";
import type { FlowEdge, FlowNode } from "../types";

export const START = "__start__";
export const END = "__end__";
type Rect = { l: number; r: number; t: number; b: number; cy: number };
type EdgeView = "idle" | "taken" | "active";

/** Which edges the run actually followed, from the order the nodes ran in (FlowRunner records each one as it is taken).
 *  The graph has loops (research → verifier, replan → agents), so this can't be worked out from which nodes ran. */
export function edgeViews(edges: FlowEdge[], s: FlowSnapshot): EdgeView[] {
  const taken = new Set(s.taken);
  return edges.map((e) =>
    !taken.has(`${e.from}>${e.to}`) ? "idle" : e.to !== END && s.nodes[e.to]?.state === "running" ? "active" : "taken");
}

/** Curves between the node cards (found by data-flow-id), drawn behind them. An edge that jumps over a whole stage (verifier ->
 *  illustrate, past research and replan) is routed beneath the nodes it skips; an edge that goes back to an earlier stage
 *  (research -> verifier, replan -> agents) arcs over the top of the diagram and comes down onto its target's column. */
export default function FlowEdges({ edges, nodes, snap, canvas, scale, version }: { edges: FlowEdge[]; nodes: FlowNode[]; snap: FlowSnapshot; canvas: RefObject<HTMLDivElement>; scale: number; version: unknown }) {
  const [geo, setGeo] = useState<{ w: number; h: number; rects: Record<string, Rect> }>({ w: 0, h: 0, rects: {} });
  useLayoutEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const measure = () => {
      const box = el.getBoundingClientRect();
      const rects: Record<string, Rect> = {};
      el.querySelectorAll<HTMLElement>("[data-flow-id]").forEach((n) => {
        const r = n.getBoundingClientRect();
        const k = 1 / scale;                                 // the canvas may be scaled: work in its own (unscaled) pixels
        rects[n.dataset.flowId!] = { l: (r.left - box.left) * k, r: (r.right - box.left) * k, t: (r.top - box.top) * k, b: (r.bottom - box.top) * k, cy: ((r.top + r.bottom) / 2 - box.top) * k };
      });
      setGeo({ w: box.width / scale, h: box.height / scale, rects });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [canvas, scale, version]);

  const views = useMemo(() => edgeViews(edges, snap), [edges, snap]);
  const shapes = edges.flatMap((e, i) => {
    const a = geo.rects[e.from], b = geo.rects[e.to];
    if (!a || !b) return [];
    const stage = (id: string) => id === START ? -1 : id === END ? Infinity : nodes.find((n) => n.id === id)?.stage ?? 0;
    if (stage(e.to) <= stage(e.from)) {                         // a loop back to an earlier step
      const column = nodes.filter((n) => n.stage === stage(e.to) && geo.rects[n.id]).map((n) => geo.rects[n.id].t);
      const top = Math.min(...Object.values(geo.rects).map((r) => r.t)) - 16;
      const x1 = (a.l + a.r) / 2, y1 = a.t, x2 = (b.l + b.r) / 2, y2 = Math.min(b.t, ...column);
      return [{ key: `${e.from}>${e.to}`, view: views[i], bypass: false, back: true,
        d: `M${x1},${y1} C${x1},${top} ${x2},${top} ${x2},${y2}`, tip: `translate(${x2},${y2}) rotate(90)` }];
    }
    const x1 = a.r, y1 = a.cy, x2 = b.l, y2 = b.cy, mid = (x1 + x2) / 2;
    const skipped = nodes.filter((n) => stage(e.from) < n.stage && n.stage < stage(e.to) && geo.rects[n.id]);
    const blocker = skipped.length > 0;
    const dip = blocker ? Math.max(...skipped.map((n) => geo.rects[n.id].b)) - y1 + 14 : 0;     // clear the bottom of the node it skips
    const c1 = blocker ? [x1 + 24, y1 + dip * 1.3] : [mid, y1], c2 = blocker ? [x2 - 24, y2 + dip * 1.3] : [mid, y2];
    const ang = Math.atan2(y2 - c2[1], x2 - c2[0]) * 180 / Math.PI;
    return [{ key: `${e.from}>${e.to}`, view: views[i], bypass: blocker, back: false,
      d: `M${x1},${y1} C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${x2},${y2}`, tip: `translate(${x2},${y2}) rotate(${ang})` }];
  });
  const order = { idle: 0, taken: 1, active: 2 };
  shapes.sort((p, q) => order[p.view] - order[q.view]);          // followed edges on top

  return (
    <svg className="flow-edges" width={geo.w} height={geo.h} aria-hidden="true">
      {shapes.map((s) => (
        <g key={s.key} className={`edge ${s.view}${s.bypass ? " bypass" : ""}${s.back ? " back" : ""}`}>
          <path d={s.d} />
          <polygon points="0,0 -7,-3.5 -7,3.5" transform={s.tip} />
        </g>
      ))}
    </svg>
  );
}
