from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from src.api import schemas
from src.api.deps import get_session
from src.core.calculators import project_goal
from src.core.config import get_config
from src.db.models import Goal, Session
from src.db.session import get_db

router = APIRouter(tags=["goals"])


@router.get("/sessions/{session_id}/goals", response_model=list[schemas.GoalOut])
def list_goals(s: Session = Depends(get_session)):
    return s.goals


@router.post("/sessions/{session_id}/goals/project")
def project(body: schemas.GoalIn, s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    """Runs the projection and saves the goal for the session."""
    cfg = get_config()
    result = project_goal(body.target_amount, body.horizon_years, body.current_savings, body.monthly_contribution,
                          cfg["risk_profiles"][body.risk_tolerance])
    goal = Goal(session_id=s.id, **body.model_dump())
    db.add(goal)
    db.commit()
    result["goal_id"] = goal.id
    result["suggested_allocation"] = cfg["allocations"][body.risk_tolerance]
    return result
