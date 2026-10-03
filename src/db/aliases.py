"""Persistence for resolved company-name -> ticker lookups (registered as `market_service.alias_store` by the API)."""
from __future__ import annotations

from src.db.models import SymbolAlias
from src.db.session import SessionLocal


def get_alias(key: str) -> dict | None:
    with SessionLocal() as db:
        row = db.get(SymbolAlias, key)
        return {"symbol": row.symbol, "name": row.name} if row else None


def put_alias(key: str, hit: dict) -> None:
    with SessionLocal() as db:
        db.merge(SymbolAlias(key=key, symbol=hit["symbol"], name=hit["name"]))
        db.commit()
