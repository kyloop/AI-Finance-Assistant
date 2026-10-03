import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { api } from "./api";
import AgentFlow from "./components/AgentFlow";
import ChatTab from "./components/ChatTab";
import { DISCLAIMER, ErrorBanner } from "./components/common";
import GoalsTab from "./components/GoalsTab";
import LiveTab, { loadWatchlist } from "./components/LiveTab";
import MarketTab from "./components/MarketTab";
import PortfolioTab from "./components/PortfolioTab";
import ResearchTab from "./components/ResearchTab";
import Sidebar from "./components/Sidebar";
import { useFlowRunner } from "./flow";
import type { ChatView, Message, Profile } from "./types";

const TABS = ["Portfolio", "Market", "Research", "Live", "Goals"] as const;
type Tab = (typeof TABS)[number];
const DEFAULT_PROFILE: Profile = { knowledge_level: "beginner", risk_tolerance: "moderate", horizon_years: 10, goals: [] };
const CHAT_W_KEY = "finnie_chat_w", CHAT_MIN_W = 320, CHAT_DEFAULT_W = 400;
const chatMaxW = () => Math.max(CHAT_MIN_W, Math.min(1000, window.innerWidth - 480));
const clampChatW = (w: number) => Math.round(Math.min(chatMaxW(), Math.max(CHAT_MIN_W, w)));

let sessionPromise: Promise<string> | null = null;
/** One session per page load: StrictMode runs the init effect twice, and two concurrent calls would create two sessions. */
function ensureSession(): Promise<string> {
  sessionPromise ??= (async () => {
    const saved = localStorage.getItem("finnie_session");
    if (saved) { try { await api.getProfile(saved); return saved; } catch { /* expired -> new */ } }
    const { id } = await api.createSession();
    localStorage.setItem("finnie_session", id);
    return id;
  })();
  return sessionPromise;
}

export default function App() {
  const [sid, setSid] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Portfolio");
  const [profile, setProfile] = useState<Profile>(DEFAULT_PROFILE);
  const [cid, setCid] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(() => localStorage.getItem("finnie_chat_open") !== "0");
  const [profileCollapsed, setProfileCollapsed] = useState(() => localStorage.getItem("finnie_profile_collapsed") === "1");
  const [chatW, setChatW] = useState(() => { const n = Number(localStorage.getItem(CHAT_W_KEY)); return n ? clampChatW(n) : CHAT_DEFAULT_W; });
  const drag = useRef<{ x: number; w: number } | null>(null);
  const [liveSelected, setLiveSelected] = useState<string | null>(null);
  const [pendingQ, setPendingQ] = useState<string | null>(null);
  const timer = useRef<number>();
  const [flow, flowState] = useFlowRunner();

  useEffect(() => {
    (async () => {
      const id = await ensureSession();
      setSid(id);
      const saved = Number(localStorage.getItem("finnie_conversation"));
      const known = saved ? (await api.conversations(id)).some((c) => c.id === saved) : false;
      const conv = known ? { id: saved } : await api.newConversation(id);    // reuses an empty thread if one exists
      const [p, m] = await Promise.all([api.getProfile(id), api.messages(id, conv.id)]);
      localStorage.setItem("finnie_conversation", String(conv.id));
      setProfile(p); setCid(conv.id); setMessages(m);
    })().catch(() => setError("Can't reach the Finnie server. Is the backend running on port 8000?"));
  }, []);

  const onProfile = useCallback((p: Profile) => {
    setProfile(p); setSaving(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => sid && api.saveProfile(sid, p).catch((e) => setError(e.message)).finally(() => setSaving(false)), 500);
  }, [sid]);

  async function reset() { if (sid && cid) { await api.resetChat(sid, cid); setMessages([]); } }
  async function openConversation(id: number) {
    if (!sid || cid === null) return;
    setMessages(await api.messages(sid, id)); setCid(id);
    localStorage.setItem("finnie_conversation", String(id));
  }
  async function startConversation() { if (sid) await openConversation((await api.newConversation(sid)).id); }
  const getView = (): ChatView => ({ tab, selected: tab === "Live" ? liveSelected : null, watchlist: loadWatchlist() });
  function toggleChat() {
    setChatOpen((o) => { localStorage.setItem("finnie_chat_open", o ? "0" : "1"); return !o; });
  }
  function collapseProfile(c: boolean) { setProfileCollapsed(c); localStorage.setItem("finnie_profile_collapsed", c ? "1" : "0"); }
  const saveChatW = (w: number) => { const v = clampChatW(w); setChatW(v); localStorage.setItem(CHAT_W_KEY, String(v)); };
  const onDragStart = (e: PointerEvent<HTMLDivElement>) => { drag.current = { x: e.clientX, w: chatW }; e.currentTarget.setPointerCapture(e.pointerId); document.body.classList.add("resizing"); };
  const onDragMove = (e: PointerEvent<HTMLDivElement>) => { if (drag.current) setChatW(clampChatW(drag.current.w + drag.current.x - e.clientX)); };
  const onDragEnd = () => { if (drag.current) { drag.current = null; saveChatW(chatW); document.body.classList.remove("resizing"); } };
  const onDragKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 80 : 20;
    if (e.key === "ArrowLeft") saveChatW(chatW + step); else if (e.key === "ArrowRight") saveChatW(chatW - step); else return;
    e.preventDefault();
  };
  function askInChat(q: string) { setPendingQ(q); setChatOpen(true); localStorage.setItem("finnie_chat_open", "1"); }

  if (!sid || cid === null) return <div className="center-screen">{error ? <ErrorBanner message={error} /> : "Loading Finnie…"}</div>;

  return (
    <>
    <div className={`layout${chatOpen ? " chat-open" : ""}${profileCollapsed ? " profile-collapsed" : ""}`} style={{ "--chat-w": `${chatW}px` } as CSSProperties}>
      <Sidebar profile={profile} onChange={onProfile} onReset={reset} saving={saving} collapsed={profileCollapsed} onCollapse={collapseProfile} />
      <main>
        <header><h1>Finnie <span className="muted">your finance learning assistant</span></h1>
          <nav>{TABS.map((t) => <button key={t} className={t === tab ? "tab active" : "tab"} onClick={() => setTab(t)}>{t}</button>)}
            <button className="secondary chat-toggle" aria-pressed={chatOpen} onClick={toggleChat}>{chatOpen ? "Hide chat" : "Show chat"}</button></nav></header>
        <ErrorBanner message={error} />
        {tab === "Portfolio" && <PortfolioTab sid={sid} onAsk={askInChat} />}
        {tab === "Market" && <MarketTab />}
        {tab === "Research" && <ResearchTab onAsk={askInChat} />}
        {tab === "Live" && <LiveTab onSelect={setLiveSelected} />}
        {tab === "Goals" && <GoalsTab sid={sid} profile={profile} />}
        <footer className="muted small">{DISCLAIMER}</footer>
      </main>
      {chatOpen && (
        <aside className="chat-dock" aria-label="Chat">
          <div className="chat-resize" role="separator" aria-orientation="vertical" aria-label="Resize chat: drag, or use the left and right arrow keys; double-click to reset"
            aria-valuemin={CHAT_MIN_W} aria-valuemax={chatMaxW()} aria-valuenow={chatW} tabIndex={0} title="Drag to resize · double-click to reset"
            onPointerDown={onDragStart} onPointerMove={onDragMove} onPointerUp={onDragEnd} onPointerCancel={onDragEnd} onKeyDown={onDragKey} onDoubleClick={() => saveChatW(CHAT_DEFAULT_W)}><span /></div>
          <ChatTab flow={flow} sid={sid} cid={cid} onNew={startConversation} onOpen={openConversation} getView={getView} messages={messages} setMessages={setMessages} initialQuestion={pendingQ} onConsumed={() => setPendingQ(null)} />
        </aside>
      )}
    </div>
    <AgentFlow state={flowState} />
    </>
  );
}
