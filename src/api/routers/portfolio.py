from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from src.api import schemas
from src.api.deps import get_session
from src.core.calculators import analyze_portfolio
from src.core.config import get_config
from src.core.portfolio_data import portfolio_dividends, portfolio_history, portfolio_instruments
from src.db.models import Holding, Portfolio, Session
from src.db.session import get_db

router = APIRouter(tags=["portfolio"])


def _holdings(s: Session) -> list[dict]:
    return [{"ticker": h.ticker, "shares": h.shares, "cost_basis": h.cost_basis, "purchase_date": h.purchase_date.isoformat() if h.purchase_date else None}
            for h in (s.portfolio.holdings if s.portfolio else [])]


def _portfolio(s: Session) -> dict:
    return {"holdings": _holdings(s), "default_purchase_date": get_config()["portfolio"]["default_purchase_date"]}


@router.get("/sessions/{session_id}/portfolio", response_model=schemas.PortfolioOut)
def get_portfolio(s: Session = Depends(get_session)):
    return _portfolio(s)


@router.put("/sessions/{session_id}/portfolio", response_model=schemas.PortfolioOut)
def put_portfolio(body: schemas.PortfolioIn, s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    """Replaces all holdings (the UI edits the whole table / uploads a CSV)."""
    if not s.portfolio:
        s.portfolio = Portfolio()
    s.portfolio.holdings = [Holding(ticker=h.ticker.upper(), shares=h.shares, cost_basis=h.cost_basis, purchase_date=h.purchase_date) for h in body.holdings]
    db.commit()
    return _portfolio(s)


@router.get("/sessions/{session_id}/portfolio/analysis")
def analysis(s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    """The Portfolio tab's whole report in one call: allocation and risk, then performance against the benchmark and dividends."""
    holdings = _holdings(s)
    instruments, data_info = portfolio_instruments(db, [h["ticker"] for h in holdings])
    result = analyze_portfolio(holdings, instruments, s.profile.risk_tolerance)
    result["data_info"] = data_info
    if not result["empty"]:
        result["performance"] = portfolio_history(db, result["holdings"])
        result["dividends"] = portfolio_dividends(db, result["holdings"])
    return result
