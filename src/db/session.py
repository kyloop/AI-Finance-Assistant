from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.config import database_url

from .base import Base
from . import models  # noqa: F401  (register tables)


def make_engine(url: str | None = None):
    url = url or database_url()
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


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


def get_db() -> Iterator[DBSession]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
