import type { ChatView, Analysis, FlowEdge, FlowEvent, FlowNode, ChatStatus, Envelope, FundProfile, GoalInput, StockProfile, GoalResult, HistoryPoint, Holding, IntradayData, IntradayPoint, Conversation, LiveQuote, Message, NewsItem, Portfolio, Profile, Quote, SymbolInfo } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    let detail = "Something went wrong. Please try again.";
    try { const j = await res.json(); if (typeof j.detail === "string") detail = j.detail; } catch { /* keep default */ }
    throw new Error(detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}
const body = (b: unknown) => JSON.stringify(b);

/** Send a chat message and read the NDJSON stream: graph progress goes to onEvent, the stored reply is returned. */
async function chatStream(sid: string, cid: number, message: string, view: ChatView | undefined, onEvent: (e: FlowEvent) => void): Promise<Message> {
  const res = await fetch(`/api/sessions/${sid}/chat/stream`, { method: "POST", headers: { "Content-Type": "application/json" }, body: body({ message, conversation_id: cid, view }) });
  if (!res.ok || !res.body) {
    let detail = "Something went wrong. Please try again.";
    try { const j = await res.json(); if (typeof j.detail === "string") detail = j.detail; } catch { /* keep default */ }
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let reply: Message | null = null;
  const handle = (line: string) => {
    if (!line.trim()) return;
    const ev = JSON.parse(line);
    if (ev.type === "done") reply = ev.message as Message;
    else if (ev.type === "error") throw new Error(ev.message);
    else onEvent(ev as FlowEvent);
  };
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    lines.forEach(handle);
    if (done) break;
  }
  handle(buffer);
  if (!reply) throw new Error("The connection closed before the answer arrived. Please try again.");
  return reply;
}

export const api = {
  createSession: () => req<{ id: string }>("/sessions", { method: "POST" }),
  getProfile: (sid: string) => req<Profile>(`/sessions/${sid}/profile`),
  saveProfile: (sid: string, p: Profile) => req<Profile>(`/sessions/${sid}/profile`, { method: "PUT", body: body(p) }),
  chatStatus: () => req<ChatStatus>("/chat/status"),
  conversations: (sid: string) => req<Conversation[]>(`/sessions/${sid}/conversations`),
  newConversation: (sid: string) => req<Conversation>(`/sessions/${sid}/conversations`, { method: "POST" }),
  deleteConversation: (sid: string, cid: number) => req<void>(`/sessions/${sid}/conversations/${cid}`, { method: "DELETE" }),
  messages: (sid: string, cid: number) => req<Message[]>(`/sessions/${sid}/messages?conversation_id=${cid}`),
  chatStream,
  flowLayout: () => req<{ nodes: FlowNode[]; edges: FlowEdge[] }>("/chat/flow"),
  chat: (sid: string, cid: number, message: string, view?: ChatView) => req<Message>(`/sessions/${sid}/chat`, { method: "POST", body: body({ message, conversation_id: cid, view }) }),
  resetChat: (sid: string, cid: number) => req<void>(`/sessions/${sid}/messages?conversation_id=${cid}`, { method: "DELETE" }),
  getPortfolio: (sid: string) => req<Portfolio>(`/sessions/${sid}/portfolio`),
  savePortfolio: (sid: string, holdings: Holding[]) => req<Portfolio>(`/sessions/${sid}/portfolio`, { method: "PUT", body: body({ holdings }) }),
  analysis: (sid: string) => req<Analysis>(`/sessions/${sid}/portfolio/analysis`),
  quote: (sym: string) => req<Envelope<Quote>>(`/market/quote/${encodeURIComponent(sym)}`),
  history: (sym: string) => req<Envelope<{ symbol: string; points: HistoryPoint[] }>>(`/market/history/${encodeURIComponent(sym)}`),
  quotes: (syms: string[]) => req<{ items: LiveQuote[]; errors: string[] }>(`/market/quotes?symbols=${encodeURIComponent(syms.join(","))}&refresh=true`),
  intraday: (sym: string) => req<Envelope<IntradayData>>(`/market/intraday/${encodeURIComponent(sym)}`),
  news: (sym?: string) => req<Envelope<{ symbol: string; items: NewsItem[] }>>(`/market/news${sym ? `?symbol=${encodeURIComponent(sym)}` : ""}`),
  symbols: () => req<SymbolInfo[]>("/market/symbols"),
  indices: () => req<Envelope<Quote>[]>("/market/indices"),
  fund: (sym: string) => req<Envelope<FundProfile>>(`/market/fund/${encodeURIComponent(sym)}`),
  stock: (sym: string) => req<Envelope<StockProfile>>(`/market/stock/${encodeURIComponent(sym)}`),
  projectGoal: (sid: string, g: GoalInput) => req<GoalResult>(`/sessions/${sid}/goals/project`, { method: "POST", body: body(g) }),
};
