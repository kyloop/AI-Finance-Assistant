"""Turso over HTTP: a small pure-Python DB-API 2 driver for Turso's Hrana-over-HTTP API (POST /v2/pipeline) and the
SQLAlchemy dialect `sqlite+turso://<db>-<org>.turso.io` on top of it.

Used instead of sqlalchemy-libsql because its native libsql driver has no wheels for Python 3.14. Each statement is
one HTTPS round trip. Outside a transaction every request closes its stream; inside one the stream is kept open with
the server's baton, so BEGIN ... COMMIT runs on one server-side connection. Like sqlite3's legacy mode, a transaction
is begun implicitly before the first INSERT/UPDATE/DELETE/REPLACE (unless autocommit), and SQLAlchemy commits or
rolls it back.
"""
import base64
import datetime as dt
from decimal import Decimal

import httpx
from sqlalchemy import pool
from sqlalchemy.dialects.sqlite.base import SQLiteDialect
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite

apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"
sqlite_version_info = (3, 45, 1)   # the SQLite release libSQL is based on; SQLAlchemy picks features from it
sqlite_version = ".".join(map(str, sqlite_version_info))


class Warning(Exception):  # noqa: A001  (PEP 249 name)
    pass


class Error(Exception):
    pass


class InterfaceError(Error):
    pass


class DatabaseError(Error):
    pass


class DataError(DatabaseError):
    pass


class OperationalError(DatabaseError):
    disconnect = False


class IntegrityError(DatabaseError):
    pass


class InternalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


class NotSupportedError(DatabaseError):
    pass


_WRITES = ("INSERT", "UPDATE", "DELETE", "REPLACE")


def _keyword(sql: str) -> str:
    return sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""


def _encode(v) -> dict:
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool | int):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, bytes | bytearray | memoryview):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    if isinstance(v, dt.datetime):
        return {"type": "text", "value": v.isoformat(" ")}
    if isinstance(v, dt.date | dt.time | Decimal):
        return {"type": "text", "value": str(v)}
    if isinstance(v, str):
        return {"type": "text", "value": v}
    raise InterfaceError(f"unsupported parameter type {type(v).__name__}")


def _decode(v: dict):
    t = v.get("type")
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "text":
        return v["value"]
    if t == "blob":
        return base64.b64decode(v["base64"])
    return None


def _error(err: dict) -> DatabaseError:
    code, msg = err.get("code") or "", err.get("message") or "Turso error"
    if code.startswith("SQLITE_CONSTRAINT") or "constraint failed" in msg.lower():
        return IntegrityError(msg)
    if "syntax error" in msg.lower() or "no such" in msg.lower():
        return ProgrammingError(msg)
    e = OperationalError(f"{msg} [{code}]" if code else msg)
    e.disconnect = code in ("STREAM_EXPIRED", "STREAM_NOT_FOUND") or "baton" in msg.lower()
    return e


class Connection:
    def __init__(self, url: str, auth_token: str, timeout: float = 30.0, transport=None):
        self._url = url.rstrip("/")
        self._base_url: str | None = None   # the server may route the rest of a stream to another node
        self._baton: str | None = None
        self._in_tx = False
        self.isolation_level: str | None = ""   # None = autocommit, as in sqlite3
        self._http = httpx.Client(headers={"Authorization": f"Bearer {auth_token}"}, timeout=timeout,
                                  transport=transport)

    @property
    def in_transaction(self) -> bool:
        return self._in_tx

    def _pipeline(self, requests: list[dict]) -> list[dict]:
        body = {"baton": self._baton, "requests": requests}
        try:
            r = self._http.post(f"{self._base_url or self._url}/v2/pipeline", json=body)
        except httpx.HTTPError as e:
            self._reset()
            err = OperationalError(f"Turso request failed: {e}")
            err.disconnect = True
            raise err from e
        if r.status_code in (401, 403):
            self._reset()
            raise OperationalError(f"Turso rejected the auth token (HTTP {r.status_code}); it must be a database "
                                   "token from `turso db tokens create <db>`")
        if r.status_code >= 400:
            self._reset()
            err = OperationalError(f"Turso HTTP {r.status_code}: {r.text[:300]}")
            err.disconnect = r.status_code >= 500 or "baton" in r.text.lower()
            raise err
        data = r.json()
        self._baton = data.get("baton")
        self._base_url = data.get("base_url") or self._base_url
        return data["results"]

    def _reset(self) -> None:
        self._baton, self._base_url, self._in_tx = None, None, False

    def _run(self, sql: str, many: list[tuple]) -> list[dict]:
        """Run `sql` once per parameter tuple in one round trip; returns each statement's result."""
        word = _keyword(sql)
        reqs = []
        if not self._in_tx and self.isolation_level is not None and word in _WRITES:
            reqs.append({"type": "execute", "stmt": {"sql": "BEGIN", "want_rows": False}})
            self._in_tx = True
        elif word == "BEGIN":
            self._in_tx = True
        elif word in ("COMMIT", "END") or (word == "ROLLBACK" and " TO " not in sql.upper()):
            self._in_tx = False
        first = len(reqs)
        reqs += [{"type": "execute", "stmt": {"sql": sql, "args": [_encode(a) for a in args], "want_rows": True}}
                 for args in many]
        if not self._in_tx:
            reqs.append({"type": "close"})
        results = self._pipeline(reqs)
        if not self._in_tx:
            self._baton = self._base_url = None
        out = []
        for res in results[first:first + len(many)]:
            if res.get("type") != "ok":
                raise _error(res.get("error") or {})
            out.append(res["response"]["result"])
        return out

    def _end(self, sql: str) -> None:
        if not self._in_tx:
            return
        try:
            self._pipeline([{"type": "execute", "stmt": {"sql": sql, "want_rows": False}}, {"type": "close"}])
        finally:
            self._reset()

    def commit(self) -> None:
        self._end("COMMIT")

    def rollback(self) -> None:
        try:
            self._end("ROLLBACK")
        except OperationalError:
            pass   # the stream is gone (expired or dropped), and with it the transaction

    def cursor(self) -> "Cursor":
        return Cursor(self)

    def close(self) -> None:
        if self._baton:
            try:
                self._pipeline([{"type": "close"}])   # closing the stream rolls back an open transaction
            except Error:
                pass
        self._reset()
        self._http.close()


class Cursor:
    arraysize = 1

    def __init__(self, conn: Connection):
        self.connection = conn
        self.description = None
        self.rowcount = -1
        self.lastrowid = None
        self._rows: list[tuple] = []

    def _load(self, result: dict) -> None:
        cols = result.get("cols") or []
        self.description = tuple((c.get("name"), None, None, None, None, None, None) for c in cols) or None
        self._rows = [tuple(_decode(v) for v in row) for row in result.get("rows") or []]
        rid = result.get("last_insert_rowid")
        self.lastrowid = int(rid) if rid is not None else None

    def execute(self, sql: str, parameters=()):
        result = self.connection._run(sql, [tuple(parameters or ())])[0]
        self._load(result)
        self.rowcount = result.get("affected_row_count", -1) if _keyword(sql) in _WRITES else -1
        return self

    def executemany(self, sql: str, seq_of_parameters):
        many = [tuple(p) for p in seq_of_parameters]
        if not many:
            self.rowcount = 0
            return self
        results = self.connection._run(sql, many)
        self._load(results[-1])
        self.rowcount = sum(r.get("affected_row_count", 0) for r in results)
        return self

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchmany(self, size: int | None = None):
        size = size or self.arraysize
        out, self._rows = self._rows[:size], self._rows[size:]
        return out

    def fetchall(self):
        out, self._rows = self._rows, []
        return out

    def __iter__(self):
        while self._rows:
            yield self._rows.pop(0)

    def setinputsizes(self, sizes):
        pass

    def setoutputsize(self, size, column=None):
        pass

    def close(self) -> None:
        self._rows = []


def connect(url: str, auth_token: str, timeout: float = 30.0, transport=None) -> Connection:
    return Connection(url, auth_token, timeout=timeout, transport=transport)


class TursoDialect(SQLiteDialect_pysqlite):
    """SQLite dialect over the HTTP driver above: `sqlite+turso://host[:port][?secure=false]`."""

    driver = "turso"
    supports_statement_cache = True
    colspecs = SQLiteDialect.colspecs   # dates go over the wire as text, not through sqlite3's adapters

    @classmethod
    def import_dbapi(cls):
        import sys
        return sys.modules[__name__]

    @classmethod
    def get_pool_class(cls, url):
        return pool.QueuePool

    def create_connect_args(self, url):
        scheme = "http" if url.query.get("secure") == "false" else "https"
        host = url.host + (f":{url.port}" if url.port else "")
        return [], {"url": f"{scheme}://{host}"}

    def on_connect(self):
        return None   # no sqlite3 create_function on a remote database

    def get_isolation_level(self, dbapi_connection):
        return "AUTOCOMMIT" if dbapi_connection.isolation_level is None else "SERIALIZABLE"

    def set_isolation_level(self, dbapi_connection, level):
        dbapi_connection.isolation_level = None if level == "AUTOCOMMIT" else ""

    def is_disconnect(self, e, connection, cursor):
        return isinstance(e, OperationalError) and e.disconnect


dialect = TursoDialect
