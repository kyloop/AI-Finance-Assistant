from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Knowledge = Literal["beginner", "intermediate", "advanced"]
Risk = Literal["conservative", "moderate", "aggressive"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SessionOut(ORM):
    id: str


class ConversationOut(ORM):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ProfileIn(BaseModel):
    knowledge_level: Knowledge = "beginner"
    risk_tolerance: Risk = "moderate"
    horizon_years: int = Field(10, ge=1, le=60)
    goals: list[str] = []


class ProfileOut(ProfileIn, ORM):
    pass


class ChatView(BaseModel):
    """What the user is looking at in the app, so "this stock" / "my watchlist" can be resolved."""
    tab: str = Field(default="", max_length=24)
    selected: str | None = Field(default=None, max_length=15)
    watchlist: list[str] = Field(default_factory=list, max_length=20)


class ChatIn(BaseModel):
    message: str = Field(max_length=4000)
    view: ChatView | None = None
    conversation_id: int | None = None       # omitted -> the session's latest conversation


class Source(BaseModel):
    id: str
    title: str
    url: str | None = None


class DataInfo(BaseModel):
    provider: str
    fetched_at: str = ""
    freshness: Literal["live", "cached", "stale", "sample"]


class MessageOut(ORM):
    id: int
    role: str
    content: str
    agents: list[str] = []
    sources: list[Source] = []
    data_info: DataInfo | None = None
    trace: list[str] = []
    choices: list[str] = []
    created_at: datetime

    @field_validator("trace", "agents", "sources", "choices", mode="before")
    @classmethod
    def none_to_empty(cls, v):
        return [] if v is None else v            # older rows / rows saved without these fields


class HoldingIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    shares: float = Field(gt=0)
    cost_basis: float | None = Field(None, ge=0)
    purchase_date: date | None = None


class PortfolioIn(BaseModel):
    holdings: list[HoldingIn]


class PortfolioOut(PortfolioIn):
    default_purchase_date: date              # performance counts a holding from here when it has no purchase date


class GoalIn(BaseModel):
    goal_type: Literal["retirement", "house", "education", "other"] = "retirement"
    target_amount: float = Field(gt=0)
    horizon_years: int = Field(ge=1, le=60)
    current_savings: float = Field(0, ge=0)
    monthly_contribution: float = Field(0, ge=0)
    risk_tolerance: Risk = "moderate"


class GoalOut(GoalIn, ORM):
    id: int
