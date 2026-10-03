import { useEffect, useRef, useState } from "react";

export interface Tick {
  symbol: string; price: number; change: number | null; change_pct: number | null; volume: number | null; ts: string;
  day_high?: number; day_low?: number; open?: number;
}
export type StreamState = "connecting" | "connected" | "reconnecting" | "closed";

const wsUrl = () => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/market/stream`;

/** Subscribes to live ticks for `symbols` over one WebSocket (auto-reconnects, re-subscribes, diffs symbol changes).
 *  `state` reflects the browser<->API link; "connected" also requires the API's own upstream feed to be up. */
export function useLiveStream(symbols: string[]) {
  const [ticks, setTicks] = useState<Record<string, Tick>>({});
  const [state, setState] = useState<StreamState>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const wanted = useRef<Set<string>>(new Set());        // what we want subscribed
  const sent = useRef<Set<string>>(new Set());          // what the current socket has been told
  const key = [...symbols].sort().join(",");

  const sync = () => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const add = [...wanted.current].filter((s) => !sent.current.has(s));
    const drop = [...sent.current].filter((s) => !wanted.current.has(s));
    if (add.length) ws.send(JSON.stringify({ action: "subscribe", symbols: add }));
    if (drop.length) ws.send(JSON.stringify({ action: "unsubscribe", symbols: drop }));
    add.forEach((s) => sent.current.add(s)); drop.forEach((s) => sent.current.delete(s));
  };

  useEffect(() => {
    let closed = false, retry = 1000, timer: number | undefined;
    const connect = () => {
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws; sent.current = new Set();
      ws.onopen = () => { retry = 1000; sync(); };
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.type === "tick") setTicks((t) => ({ ...t, [m.symbol]: m }));
        else if (m.type === "status") setState(m.state === "connected" ? "connected" : m.state === "idle" ? "connecting" : m.state);
      };
      ws.onclose = () => {
        if (closed) return;
        setState("reconnecting");
        timer = window.setTimeout(connect, retry); retry = Math.min(retry * 2, 15000);
      };
    };
    connect();
    return () => { closed = true; window.clearTimeout(timer); wsRef.current?.close(); setState("closed"); };
  }, []);

  useEffect(() => { wanted.current = new Set(symbols); sync(); }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps

  return { ticks, state };
}
