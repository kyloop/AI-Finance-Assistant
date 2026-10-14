import base64
import json
import sqlite3
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.core.config import ROOT, database_url
from src.db import models, turso_http
from src.db import session as db_session
from src.db.session import get_db, init_db


class FakeTurso:
    """Turso's /v2/pipeline (Hrana over HTTP) backed by an in-memory sqlite3 database, one stream at a time."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.baton = None
        self.requests = []

    @staticmethod
    def _value(v):
        if v is None:
            return {"type": "null"}
        if isinstance(v, int):
            return {"type": "integer", "value": str(v)}
        if isinstance(v, float):
            return {"type": "float", "value": v}
        if isinstance(v, bytes):
            return {"type": "blob", "base64": base64.b64encode(v).decode()}
        return {"type": "text", "value": v}

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/pipeline"
        if request.headers["authorization"] != "Bearer tok":
            return httpx.Response(401, text="unauthorized")
        body = json.loads(request.content)
        self.requests.append(body)
        assert body["baton"] == self.baton, "request must carry the stream's baton"
        self.baton = uuid.uuid4().hex
        results = []
        for req in body["requests"]:
            if req["type"] == "close":
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                self.baton = None
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            stmt = req["stmt"]
            args = [turso_http._decode(a) for a in stmt.get("args", [])]
            try:
                cur = self.db.execute(stmt["sql"], args)
                rows = cur.fetchall()
            except sqlite3.Error as e:
                code = "SQLITE_CONSTRAINT" if isinstance(e, sqlite3.IntegrityError) else "SQLITE_ERROR"
                results.append({"type": "error", "error": {"message": str(e), "code": code}})
                continue
            results.append({"type": "ok", "response": {"type": "execute", "result": {
                "cols": [{"name": d[0], "decltype": None} for d in cur.description or []],
                "rows": [[self._value(v) for v in row] for row in rows],
                "affected_row_count": max(cur.rowcount, 0),
                "last_insert_rowid": str(cur.lastrowid) if cur.lastrowid is not None else None}}})
        return httpx.Response(200, json={"baton": self.baton, "base_url": None, "results": results})


@pytest.fixture
def turso():
    return FakeTurso()


@pytest.fixture
def engine(turso):
    return create_engine("sqlite+turso://finnie-kev.turso.io",
                         connect_args={"auth_token": "tok", "transport": httpx.MockTransport(turso.handle)})


def test_local_sqlite_without_turso(monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url() == f"sqlite:///{ROOT / 'finnie.db'}"


@pytest.mark.parametrize("given", ["libsql://finnie-kev.turso.io", "https://finnie-kev.turso.io/",
                                   "turso://finnie-kev.turso.io", "finnie-kev.turso.io"])
def test_turso_url_becomes_turso_dialect(monkeypatch, given):
    monkeypatch.setenv("TURSO_DATABASE_URL", given)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///ignored.db")          # Turso wins
    assert database_url() == "sqlite+turso://finnie-kev.turso.io"


def test_local_turso_dev_is_plain_http(monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "http://127.0.0.1:8080")
    assert database_url() == "sqlite+turso://127.0.0.1:8080?secure=false"
    e = create_engine(database_url(), connect_args={"auth_token": "t"})
    assert e.dialect.create_connect_args(e.url) == ([], {"url": "http://127.0.0.1:8080"})


def test_turso_without_token_fails_loudly(monkeypatch):
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TURSO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TURSO_AUTH_TOKEN"):
        db_session.make_engine("sqlite+turso://finnie-kev.turso.io")


@pytest.mark.parametrize("var", ["TURSO_AUTH_TOKEN", "TURSO_API_KEY"])
def test_turso_engine_takes_token_from_either_variable(monkeypatch, var):
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TURSO_API_KEY", raising=False)
    monkeypatch.setenv(var, "secret-token")
    e = db_session.make_engine("sqlite+turso://finnie-kev.turso.io")
    assert e.dialect.driver == "turso"
    assert e.dialect.create_connect_args(e.url) == ([], {"url": "https://finnie-kev.turso.io"})


def test_schema_and_orm_round_trip(engine):
    init_db(engine)
    init_db(engine)                                                      # idempotent: tables already there
    Local = sessionmaker(bind=engine, expire_on_commit=False)
    with Local() as db:
        s = models.Session()
        s.profile = models.UserProfile(goals=["retire"], horizon_years=25)
        db.add(s)
        db.commit()
        sid, created = s.id, s.created_at
    with Local() as db:
        got = db.get(models.Session, sid)
        assert got.profile.goals == ["retire"] and got.profile.horizon_years == 25
        assert got.created_at.replace(tzinfo=None) == created.replace(tzinfo=None)


def test_writes_run_in_one_transaction_and_roll_back(engine, turso):
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, x TEXT UNIQUE)"))
        conn.commit()
    with engine.connect() as conn:
        conn.execute(text("INSERT INTO t (x) VALUES ('a')"))
        assert turso.baton is not None                                   # stream kept open mid-transaction
        conn.rollback()
    assert turso.baton is None
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM t")).scalar() == 0
        conn.execute(text("INSERT INTO t (x) VALUES (:x)"), [{"x": "a"}, {"x": "b"}])
        conn.commit()
        assert conn.execute(text("SELECT x FROM t ORDER BY x")).scalars().all() == ["a", "b"]


def test_constraint_violation_is_integrity_error(engine):
    from sqlalchemy.exc import IntegrityError
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE u (x TEXT UNIQUE)"))
        conn.execute(text("INSERT INTO u VALUES ('a')"))
        conn.commit()
        with pytest.raises(IntegrityError):
            conn.execute(text("INSERT INTO u VALUES ('a')"))


def test_bad_token_says_what_token_is_needed(turso):
    e = create_engine("sqlite+turso://finnie-kev.turso.io",
                      connect_args={"auth_token": "wrong", "transport": httpx.MockTransport(turso.handle)})
    from sqlalchemy.exc import OperationalError
    with pytest.raises(OperationalError, match="turso db tokens create"):
        with e.connect() as conn:
            conn.execute(text("SELECT 1"))


def test_api_runs_on_turso(engine):
    init_db(engine)
    Local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        with Local() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        c = TestClient(app)                                              # no lifespan: no pollers, no global engine
        sid = c.post("/api/sessions").json()["id"]
        r = c.put(f"/api/sessions/{sid}/profile", json={"horizon_years": 30})
        assert r.status_code == 200, r.text
        assert c.get(f"/api/sessions/{sid}/profile").json()["horizon_years"] == 30
    finally:
        app.dependency_overrides.clear()
