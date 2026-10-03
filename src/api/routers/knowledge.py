from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from src.db.models import GlossaryTerm, KBDocument
from src.db.session import get_db

router = APIRouter(tags=["knowledge"], prefix="/kb")


@router.get("/documents")
def documents(category: str | None = None, db: DBSession = Depends(get_db)):
    q = select(KBDocument).order_by(KBDocument.category, KBDocument.title)
    if category:
        q = q.where(KBDocument.category == category)
    return [{"id": d.id, "title": d.title, "category": d.category, "source_name": d.source_name, "source_url": d.source_url}
            for d in db.scalars(q)]


@router.get("/glossary")
def glossary(q: str = Query("", max_length=64), db: DBSession = Depends(get_db)):
    stmt = select(GlossaryTerm).order_by(GlossaryTerm.term)
    if q:
        stmt = stmt.where(GlossaryTerm.term.ilike(f"%{q}%"))
    return [{"term": t.term, "definition": t.definition, "category": t.category} for t in db.scalars(stmt)]
