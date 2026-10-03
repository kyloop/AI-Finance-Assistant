from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from src.db.models import Session
from src.db.session import get_db


def get_session(session_id: str, db: DBSession = Depends(get_db)) -> Session:
    s = db.get(Session, session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return s
