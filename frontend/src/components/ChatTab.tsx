import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { FlowRunner } from "../flow";
import type { ChatStatus, ChatView, Conversation, Message } from "../types";
import { ErrorBanner, FreshnessBadge } from "./common";
import RichText from "./RichText";

const STARTERS = ["What is an ETF?", "How is that different from a mutual fund?", "What does diversification mean?", "How does a Roth IRA work?"];

interface Props { flow: FlowRunner; sid: string; cid: number; onNew: () => Promise<void>; onOpen: (id: number) => Promise<void>; getView: () => ChatView; messages: Message[]; setMessages: (m: Message[]) => void; initialQuestion: string | null; onConsumed: () => void }

export default function ChatTab({ flow, sid, cid, onNew, onOpen, getView, messages, setMessages, initialQuestion, onConsumed }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<ChatStatus | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<Conversation[]>([]);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { api.chatStatus().then(setStatus).catch(() => undefined); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  async function send(q: string) {
    const msg = q.trim();
    if (!msg || busy) return;
    setError(null); setBusy(true); setText("");
    const optimistic: Message = { id: -Date.now(), role: "user", content: msg, agents: [], sources: [], data_info: null, trace: [], created_at: new Date().toISOString() };
    setMessages([...messages, optimistic]);
    flow.begin(msg);
    try {
      const reply = await api.chatStream(sid, cid, msg, getView(), (e) => flow.push(e));
      await flow.finish(true);                                      // let the flow panel catch up before the answer appears
      setMessages([...messages, optimistic, reply]);
      api.chatStatus().then(setStatus).catch(() => undefined);      // pick up "model failing" / "recovered"
    } catch (e) {
      void flow.finish(false);
      setError((e as Error).message);
    } finally { setBusy(false); }
  }

  async function toggleHistory() {
    if (historyOpen) { setHistoryOpen(false); return; }
    try { setHistory(await api.conversations(sid)); setHistoryOpen(true); setError(null); }
    catch (e) { setError((e as Error).message); }
  }
  async function guarded(fn: () => Promise<void>) {
    if (busy) return;
    try { setError(null); await fn(); setHistoryOpen(false); } catch (e) { setError((e as Error).message); }
  }
  async function remove(id: number) {
    try {
      await api.deleteConversation(sid, id);
      setHistory((h) => h.filter((c) => c.id !== id));
      if (id === cid) await onNew();
    } catch (e) { setError((e as Error).message); }
  }

  useEffect(() => {
    if (initialQuestion) { onConsumed(); send(initialQuestion); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);

  return (
    <section className="chat">
      {status && (
        <div className="chat-status muted small">
          {status.llm.enabled && status.llm.last_error
            ? <span className="warn-text">AI model <strong>{status.llm.model}</strong> is connected but not responding: {status.llm.last_error} Using basic mode (Wikipedia excerpts + calculators) meanwhile.</span>
            : status.llm.enabled
            ? <>AI model: <strong>{status.llm.model}</strong>. Answers are written from Wikipedia, market data and calculators.</>
            : <>Basic mode: no AI model connected, so answers are excerpts from Wikipedia plus live calculators. Add an API key to enable full AI answers.</>}
        </div>
      )}
      <div className="chat-toolbar">
        <button className="secondary" disabled={busy || messages.length === 0} onClick={() => guarded(onNew)}>+ New chat</button>
        <button className="secondary" disabled={busy} aria-expanded={historyOpen} onClick={toggleHistory}>History</button>
      </div>
      {historyOpen && (
        <div className="history-panel" role="list">
          {history.length === 0 && <p className="muted small">No previous chats yet.</p>}
          {history.map((c) => (
            <div key={c.id} role="listitem" className={c.id === cid ? "history-item current" : "history-item"}>
              <button className="history-open" onClick={() => c.id === cid ? setHistoryOpen(false) : guarded(() => onOpen(c.id))}>
                <span className="history-title">{c.title}</span>
                <span className="muted small">{new Date(c.updated_at).toLocaleString()} · {c.message_count} messages</span>
              </button>
              <button className="link" aria-label={`Delete chat ${c.title}`} onClick={() => remove(c.id)}>Delete</button>
            </div>
          ))}
        </div>
      )}
      <div className="chat-log">
        {messages.length === 0 && (
          <div className="starters">
            <p>Ask me anything about personal finance and investing.</p>
            {STARTERS.map((s) => <button key={s} className="chip" onClick={() => send(s)}>{s}</button>)}
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`bubble ${m.role}`}>
            {m.role === "assistant" && m.agents.length > 0 && (
              <div className="agents">{m.agents.map((a) => <span key={a} className="badge badge-agent">{a}</span>)}</div>
            )}
            {m.role === "assistant" ? <RichText text={m.content} /> : <p>{m.content}</p>}
            {m.data_info && <FreshnessBadge freshness={m.data_info.freshness} provider={m.data_info.provider} fetchedAt={m.data_info.fetched_at} />}
            {m.role === "assistant" && m.trace?.length > 0 && (
              <details className="trace"><summary>How I answered</summary><ol>{m.trace.map((t, i) => <li key={i}>{t}</li>)}</ol></details>
            )}
            {m.role === "assistant" && (m.choices?.length ?? 0) > 0 && (
              <div className="choices">
                <span className="muted small choices-label">You could ask next:</span>
                {m.choices!.map((c) => <button key={c} className="chip" disabled={busy} onClick={() => send(c)}>{c}</button>)}
              </div>
            )}
            {m.sources.length > 0 && (
              <ul className="sources"><li className="muted small">Sources</li>
                {m.sources.map((s) => <li key={s.id}>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> : s.title}</li>)}
              </ul>
            )}
          </div>
        ))}
        {busy && <div className="bubble assistant muted">Thinking…</div>}
        <div ref={end} />
      </div>
      <ErrorBanner message={error} />
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} placeholder="Ask a question…" aria-label="Message" />
        <button disabled={busy || !text.trim()}>Send</button>
      </form>
    </section>
  );
}
