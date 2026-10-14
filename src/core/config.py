import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "src" / "data"

DISCLAIMER = "This is for educational purposes only and is not financial advice."


def load_env() -> None:
    """Load KEY=VALUE pairs from .env into os.environ (real environment variables win)."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            if value.strip().strip("\"'"):
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()


@lru_cache
def get_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def database_url() -> str:
    """Turso when TURSO_DATABASE_URL is set (libsql://<db>-<org>.turso.io, as `turso db show` prints it; http:// for a
    local `turso dev`), else DATABASE_URL, else the local finnie.db. The token is passed separately (db/session.py)."""
    turso = os.getenv("TURSO_DATABASE_URL", "").strip()
    if turso:
        scheme, _, rest = turso.rpartition("://")
        host = rest.split("?", 1)[0].rstrip("/")
        return f"sqlite+turso://{host}" + ("?secure=false" if scheme in ("http", "ws") else "")
    return os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'finnie.db'}")


def cors_origins() -> list[str]:
    return os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
