"""Chat endpoint: loads the session's history/profile/portfolio, runs the LangGraph orchestrator, stores the reply."""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSession

from src.api import schemas
from src.api.deps import get_session
from src.core.config import DISCLAIMER, get_config
from src.core.llm import ask_llm, llm_status
from src.db.models import Conversation, Message, Session
from src.db.session import get_db
from src.workflow.graph import flow_edges, flow_layout, run_chat, stream_chat
from src.workflow.safety import REFUSAL_NOTE  # noqa: F401  (re-exported for tests)

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])
EMPTY_REPLY = "I didn't catch a question there. Try asking about a term like “ETF”, or ask about your portfolio or goals."
ERROR_REPLY = "Sorry, something went wrong while I was working on that. Please try again."
RETITLE_AFTER_ROUNDS = 3   # once a thread reaches this many rounds, the LLM renames it from the whole conversation
RETITLE_SYSTEM = ("You name chat threads. Given a conversation between a user and a personal-finance assistant, reply with "
                  "a short title (3 to 6 words, no quotes, no trailing punctuation) describing what the conversation is about.")


@router.get("/chat/status")
def status():
    """Which mode the assistant is in, so the UI can be honest about it."""
    return {"llm": llm_status(), "tools": ["knowledge_base_search", "wikipedia_search", "market_quotes", "news_search", "portfolio_analysis", "goal_projection", "finance_calculator"]}


def _title(text: str) -> str:
    t = " ".join(text.split())
    return t if len(t) <= 60 else t[:57] + "…"


def retitle(conv: Conversation, db: DBSession) -> None:
    """Rename the thread from its conversation so far. Without an LLM (or if the call fails) the first-question title stays."""
    recent = "\n".join(f"{m.role}: {' '.join(m.content.split())[:300]}" for m in conv.messages[-2 * RETITLE_AFTER_ROUNDS:])
    reply = ask_llm(RETITLE_SYSTEM, recent)
    title = _title(reply.splitlines()[0].strip(" \"'*#.")) if reply else ""
    if title:
        conv.title = title
        db.commit()


def resolve_conversation(s: Session, db: DBSession, cid: int | None) -> Conversation:
    """The requested conversation, or the session's latest (created on demand).
    Messages stored before conversations existed are adopted into one thread."""
    orphans = [m for m in s.messages if m.conversation_id is None]
    if orphans:
        first_user = next((m.content for m in orphans if m.role == "user"), "Earlier chat")
        legacy = Conversation(session_id=s.id, title=_title(first_user), created_at=orphans[0].created_at, updated_at=orphans[-1].created_at)
        db.add(legacy)
        db.flush()
        for m in orphans:
            m.conversation_id = legacy.id
        db.commit()
        db.refresh(s)
    if cid is not None:
        conv = next((c for c in s.conversations if c.id == cid), None)
        if not conv:
            raise HTTPException(404, "Conversation not found")
        return conv
    if s.conversations:
        return s.conversations[-1]
    conv = Conversation(session_id=s.id)
    db.add(conv)
    db.commit()
    db.refresh(s)
    return conv


@router.get("/sessions/{session_id}/conversations", response_model=list[schemas.ConversationOut])
def list_conversations(s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    """History: non-empty conversations, most recently active first."""
    resolve_conversation(s, db, None)
    rows = [schemas.ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at, message_count=len(c.messages))
            for c in s.conversations if c.messages]
    return sorted(rows, key=lambda r: r.updated_at, reverse=True)


@router.post("/sessions/{session_id}/conversations", response_model=schemas.ConversationOut, status_code=201)
def create_conversation(s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    """Start a new chat. An existing empty conversation is reused rather than piling up blanks."""
    resolve_conversation(s, db, None)
    conv = next((c for c in reversed(s.conversations) if not c.messages), None)
    if conv is None:
        conv = Conversation(session_id=s.id)
        db.add(conv)
        db.commit()
    return schemas.ConversationOut(id=conv.id, title=conv.title, created_at=conv.created_at, updated_at=conv.updated_at, message_count=0)


@router.delete("/sessions/{session_id}/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    conv = resolve_conversation(s, db, conversation_id)
    db.delete(conv)
    db.commit()


@router.get("/sessions/{session_id}/messages", response_model=list[schemas.MessageOut])
def list_messages(conversation_id: int | None = None, s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    return resolve_conversation(s, db, conversation_id).messages


class _Turn:
    """One user message, recorded and ready to run: shared by the plain and the streaming endpoints."""
    def __init__(self, body: schemas.ChatIn, s: Session, db: DBSession):
        self.s, self.db = s, db
        self.text = body.message.strip()
        conv = resolve_conversation(s, db, body.conversation_id)
        self.history = [{"role": m.role, "content": m.content} for m in conv.messages[-get_config()["workflow"]["history_turns"]:]]
        last = next((m for m in reversed(conv.messages) if m.role == "assistant"), None)
        context = last.context if last else None                     # what the previous answer worked out (workflow/context.py)
        if not conv.messages:
            conv.title = _title(self.text) if self.text else "New chat"
        conv.updated_at = datetime.now(timezone.utc)
        self.conv, self.cid = conv, conv.id
        db.add(Message(session_id=s.id, conversation_id=self.cid, role="user", content=self.text or "(empty)"))
        holdings = [{"ticker": h.ticker, "shares": h.shares, "cost_basis": h.cost_basis, "purchase_date": h.purchase_date.isoformat() if h.purchase_date else None}
                    for h in (s.portfolio.holdings if s.portfolio else [])]
        profile = {"knowledge_level": s.profile.knowledge_level, "risk_tolerance": s.profile.risk_tolerance,
                   "horizon_years": s.profile.horizon_years, "goals": s.profile.goals}
        g = s.goals[-1] if s.goals else None
        saved_goal = {k: getattr(g, k) for k in ("goal_type", "target_amount", "horizon_years", "current_savings", "monthly_contribution", "risk_tolerance")} if g else None
        self.graph_args = dict(history=self.history, profile=profile, holdings=holdings, db=db, saved_goal=saved_goal,
                               view=body.view.model_dump() if body.view else None, context=context)

    def _reply(self, **fields) -> Message:
        return Message(session_id=self.s.id, conversation_id=self.cid, role="assistant", **fields)

    def empty_reply(self) -> Message:
        return self._reply(content=f"{EMPTY_REPLY}\n\n{DISCLAIMER}", agents=[], sources=[])

    def failed_reply(self) -> Message:
        log.exception("chat graph failed")                    # never show a stack trace to the user (FR-C8)
        return self._reply(content=f"{ERROR_REPLY}\n\n{DISCLAIMER}", agents=[], sources=[], trace=["graph failed unexpectedly"])

    def reply_from(self, out: dict) -> Message:
        return self._reply(content=out["final_response"], agents=out["agents"], sources=out["sources"], data_info=out.get("data_info"),
                           trace=out.get("trace", []), choices=out.get("choices") or [], context=out.get("context"))

    def save(self, reply: Message) -> Message:
        self.db.add(reply)
        self.db.commit()
        self.db.refresh(self.conv)
        if sum(m.role == "user" for m in self.conv.messages) == RETITLE_AFTER_ROUNDS:
            retitle(self.conv, self.db)
        return reply


@router.post("/sessions/{session_id}/chat", response_model=schemas.MessageOut)
def chat(body: schemas.ChatIn, s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    turn = _Turn(body, s, db)
    if not turn.text:
        return turn.save(turn.empty_reply())
    try:
        reply = turn.reply_from(run_chat(turn.text, **turn.graph_args))
    except Exception:  # noqa: BLE001
        reply = turn.failed_reply()
    return turn.save(reply)


@router.get("/chat/flow")
def flow():
    """The graph's nodes (in left-to-right stages) and edges, for the agent-flow panel."""
    return {"nodes": flow_layout(), "edges": flow_edges()}


@router.post("/sessions/{session_id}/chat/stream")
def chat_stream(body: schemas.ChatIn, s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    """Same as /chat, but streams newline-delimited JSON: a node_start / node_end event as each graph node runs (see
    workflow.graph.stream_chat), then {"type": "done", "message": <the stored reply>}."""
    turn = _Turn(body, s, db)

    def events():
        try:
            if not turn.text:
                reply = turn.empty_reply()
            else:
                try:
                    for ev in stream_chat(turn.text, **turn.graph_args):
                        if ev["type"] == "final":
                            reply = turn.reply_from(ev["state"])
                        else:
                            yield _line(ev)
                except Exception:  # noqa: BLE001
                    reply = turn.failed_reply()
            message = schemas.MessageOut.model_validate(turn.save(reply)).model_dump(mode="json")
            yield _line({"type": "done", "message": message})
        except Exception:  # noqa: BLE001 — the stream is already open, so report the failure inside it
            log.exception("chat stream failed")
            yield _line({"type": "error", "message": ERROR_REPLY})

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _line(event: dict) -> str:
    return json.dumps(event) + "\n"
