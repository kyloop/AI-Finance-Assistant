import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import cors_origins
from src.core import market_service
from src.core.live_stream import hub
from src.db.session import init_db

from .routers import chat, goals, knowledge, market, portfolio, sessions, stream


def _build_ticker_index() -> None:
    from src.rag import tickers
    try:
        tickers.ensure_index()
    except Exception:  # noqa: BLE001 — without the index only the "same meaning" lookup is lost
        logging.getLogger(__name__).warning("could not build the ticker name index", exc_info=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    from src.rag import news
    from src.db import aliases
    market_service.alias_store = (aliases.get_alias, aliases.put_alias)  # remember company-name lookups across restarts
    market_service.news_listeners.append(news.queue_ingest)            # index every fresh Yahoo news fetch
    poller = asyncio.create_task(news.run_poller())
    names = asyncio.create_task(asyncio.to_thread(_build_ticker_index))        # first start: embed the listed company names (~40 s, in the background)
    yield
    poller.cancel()
    names.cancel()
    market_service.news_listeners.remove(news.queue_ingest)
    await hub.stop()


app = FastAPI(title="Finnie API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_methods=["*"], allow_headers=["*"])

for r in (sessions, chat, portfolio, market, stream, goals, knowledge):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
