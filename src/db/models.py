"""Relational schema (SQLite by default). The FAISS vector index is separate (src/rag);
`kb_documents` only stores article metadata so the UI/agents can list and cite sources."""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    profile: Mapped["UserProfile"] = relationship(back_populates="session", cascade="all, delete-orphan", uselist=False)
    messages: Mapped[list["Message"]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="Message.id")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="Conversation.id")
    portfolio: Mapped["Portfolio | None"] = relationship(back_populates="session", cascade="all, delete-orphan", uselist=False)
    goals: Mapped[list["Goal"]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="Goal.id")


class UserProfile(Base):
    __tablename__ = "user_profiles"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    knowledge_level: Mapped[str] = mapped_column(String(16), default="beginner")      # beginner|intermediate|advanced
    risk_tolerance: Mapped[str] = mapped_column(String(16), default="moderate")       # conservative|moderate|aggressive
    horizon_years: Mapped[int] = mapped_column(Integer, default=10)
    goals: Mapped[list] = mapped_column(JSON, default=list)

    session: Mapped[Session] = relationship(back_populates="profile")


class Conversation(Base):
    """One chat thread inside a session (profile, portfolio and goals stay shared across threads)."""
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[Session] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=True)
    role: Mapped[str] = mapped_column(String(16))                                     # user|assistant
    content: Mapped[str] = mapped_column(Text)
    agents: Mapped[list] = mapped_column(JSON, default=list)                          # FR-C6
    sources: Mapped[list] = mapped_column(JSON, default=list)                         # FR-C3 citations
    data_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)               # FR-C4 provider/timestamp/freshness
    trace: Mapped[list | None] = mapped_column(JSON, nullable=True)                   # orchestrator steps ("how I answered")
    choices: Mapped[list | None] = mapped_column(JSON, nullable=True)                 # follow-up questions the user can click
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)                 # assistant: what the turn used (corrected question,
                                                                                      # companies, period, figures); the next turn starts from it
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[Session] = relationship(back_populates="messages")
    conversation: Mapped["Conversation | None"] = relationship(back_populates="messages")


class Portfolio(Base):
    __tablename__ = "portfolios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), unique=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    session: Mapped[Session] = relationship(back_populates="portfolio")
    holdings: Mapped[list["Holding"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")


class Holding(Base):
    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(16))
    shares: Mapped[float] = mapped_column(Float)
    cost_basis: Mapped[float | None] = mapped_column(Float, nullable=True)            # per share, optional
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)           # optional; performance is measured from here

    portfolio: Mapped[Portfolio] = relationship(back_populates="holdings")


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    goal_type: Mapped[str] = mapped_column(String(32))                                # retirement|house|education|other
    target_amount: Mapped[float] = mapped_column(Float)
    horizon_years: Mapped[int] = mapped_column(Integer)
    current_savings: Mapped[float] = mapped_column(Float, default=0)
    monthly_contribution: Mapped[float] = mapped_column(Float, default=0)
    risk_tolerance: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[Session] = relationship(back_populates="goals")


class MarketCache(Base):
    """TTL cache keyed by (provider, symbol, endpoint, params) — FR-M2."""
    __tablename__ = "market_cache"
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    endpoint: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class KBDocument(Base):
    """Knowledge-base article metadata — FR-K4."""
    __tablename__ = "kb_documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(48), index=True)
    source_name: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str] = mapped_column(String(512))
    last_reviewed: Mapped[str] = mapped_column(String(10))                            # ISO date
    path: Mapped[str] = mapped_column(String(512))


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"
    term: Mapped[str] = mapped_column(String(96), primary_key=True)
    definition: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(48), nullable=True)


class SymbolAlias(Base):
    """A company name the symbol lookup resolved on Yahoo, kept so later lookups (and restarts) need no network call."""
    __tablename__ = "symbol_aliases"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)          # the name the user wrote, lower-cased
    symbol: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
