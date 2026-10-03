from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from src.api import schemas
from src.api.deps import get_session
from src.api.routers.chat import resolve_conversation
from src.db.models import Session, UserProfile
from src.db.session import get_db

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=schemas.SessionOut, status_code=201)
def create_session(db: DBSession = Depends(get_db)):
    s = Session(profile=UserProfile())
    db.add(s)
    db.commit()
    return s


@router.get("/sessions/{session_id}/profile", response_model=schemas.ProfileOut)
def get_profile(s: Session = Depends(get_session)):
    return s.profile


@router.put("/sessions/{session_id}/profile", response_model=schemas.ProfileOut)
def put_profile(body: schemas.ProfileIn, s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    for k, v in body.model_dump().items():
        setattr(s.profile, k, v)
    db.commit()
    return s.profile


@router.delete("/sessions/{session_id}/messages", status_code=204)
def reset_conversation(conversation_id: int | None = None, s: Session = Depends(get_session), db: DBSession = Depends(get_db)):
    conv = resolve_conversation(s, db, conversation_id)
    conv.messages.clear()
    conv.title = "New chat"
    db.commit()
