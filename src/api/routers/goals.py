from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from src.api import schemas
from src.api.deps import get_session
from src.core.calculators import project_goal, simulate_goal
from src.core.config import get_config
from src.db.models import Goal, Session
from src.db.session import get_db

router = APIRouter(tags=["goals"])
FIELDS = ("goal_type", "target_amount", "horizon_years", "current_savings", "monthly_contribution", "risk_tolerance")


@router.get("/sessions/{session_id}/goals", response_model=list[schemas.GoalOut])
def list_goals(s: Session = Depends(get_session)):
    return s.goals


@router.post("/sessions/{session_id}/goals/project")
def project(body: schemas.GoalIn, s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    """Runs the projection and the Monte Carlo simulation, and saves the goal for the session. Re-projecting an
    identical goal replaces the old row, so the list has no duplicates and the latest plan (read by chat) is last."""
    cfg = get_config()
    mc = cfg["monte_carlo"]
    annual_return = cfg["risk_profiles"][body.risk_tolerance]
    result = project_goal(body.target_amount, body.horizon_years, body.current_savings, body.monthly_contribution, annual_return)
    result["monte_carlo"] = simulate_goal(body.target_amount, body.horizon_years, body.current_savings, body.monthly_contribution,
                                          annual_return, cfg["risk_volatility"][body.risk_tolerance],
                                          simulations=mc["simulations"], seed=mc["seed"], confidence=mc["confidence"])
    values = body.model_dump()
    for old in [g for g in s.goals if all(getattr(g, k) == values[k] for k in FIELDS)]:
        s.goals.remove(old)
    goal = Goal(session_id=s.id, **values)
    s.goals.append(goal)
    db.commit()
    result["goal_id"] = goal.id
    result["suggested_allocation"] = cfg["allocations"][body.risk_tolerance]
    return result


@router.delete("/sessions/{session_id}/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    goal = next((g for g in s.goals if g.id == goal_id), None)
    if not goal:
        raise HTTPException(404, "Goal not found")
    s.goals.remove(goal)
    db.commit()
