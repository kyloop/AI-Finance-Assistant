import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects import registry
from sqlalchemy.pool import NullPool, StaticPool

from src.core.config import database_url, market_cache_url

from .base import Base
from . import models  # noqa: F401  (register tables)


registry.register("sqlite.turso", "src.db.turso_http", "TursoDialect")


def _turso_engine(url: str):
    """Remote Turso database over its HTTP API, through the pure-Python driver in db/turso_http.py."""
    token = (os.getenv("TURSO_AUTH_TOKEN") or os.getenv("TURSO_API_KEY") or "").strip()
    if not token:
        raise RuntimeError("TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is empty (create one with `turso db tokens create <db>`)")
    return create_engine(url, connect_args={"auth_token": token}, pool_pre_ping=True)


def make_engine(url: str | None = None, pool=None):
    url = url or database_url()
    if url.startswith("sqlite+turso"):
        return _turso_engine(url)
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs["poolclass"] = StaticPool
    elif pool is not None:
        kwargs["poolclass"] = pool
    return create_engine(url, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
_cache_url = market_cache_url()
# the market cache's own local database, when the main one is remote. NullPool: a local SQLite connection is cheap to open,
# and a pool's 15-connection cap made the Live Market tab's ~25 parallel fetches queue for connections
cache_engine = make_engine(_cache_url, pool=NullPool) if _cache_url else None
CacheSessionLocal = sessionmaker(bind=cache_engine, autoflush=False, expire_on_commit=False) if cache_engine else None


@contextmanager
def market_cache_session(db: DBSession) -> Iterator[DBSession]:
    """The session the market cache is read and written through: a local one when the main database is remote, else `db` itself."""
    if CacheSessionLocal is None:
        yield db
        return
    with CacheSessionLocal() as local:
        yield local


def _add_missing_columns(bind) -> None:
    """create_all never alters existing tables; add columns introduced after a dev database was created."""
    insp = inspect(bind)
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(bind.dialect)}'
                    conn.execute(text(ddl))


def init_db(bind=None) -> None:
    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    _add_missing_columns(bind)
    if cache_engine is not None and bind is engine:
        Base.metadata.create_all(bind=cache_engine, tables=[models.MarketCache.__table__])


def get_db() -> Iterator[DBSession]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
