import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.db.base import Base
from src.db.session import get_db, make_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def client():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    Local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        db = Local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def sid(client):
    return client.post("/api/sessions").json()["id"]


# ---- keep every test offline and LLM-free unless it opts in ------------------------------------------------
from src.core import llm as llm_module  # noqa: E402
from src.workflow import symbols as symbols_module  # noqa: E402
from src.workflow.tools import set_kb_searcher, set_news_indexer, set_news_searcher, set_wiki_client  # noqa: E402
from src.core.market_service import set_symbol_resolver  # noqa: E402


class FakePage:
    def __init__(self, title="Exchange-traded fund"):
        self.title = title
        abbr = {"Exchange-traded fund": " (ETF)"}.get(title, "")        # real Wikipedia leads define the abbreviation
        self.text = (f"{title}{abbr} is a type of investment fund that trades on stock exchanges like a single stock. "
                     "It holds many underlying investments so one purchase spreads your money across them. " * 2
                     + "\n\n## History\n\nA long history section that must not appear in the lead.")
        self.url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
        self.revision_id = 5


class FakeWiki:
    """Stands in for WikiClient; `results` maps a search term to titles, unknown terms find nothing."""
    def __init__(self, results=None, fail=False):
        self.results = results or {"etf": ["Exchange-traded fund"], "roth": ["Roth IRA"], "index fund": ["Index fund"]}
        self.fail = fail
        self.queries: list[str] = []

    def search(self, query, limit=3):
        from src.kb.wiki import WikiUnavailable
        self.queries.append(query)
        if self.fail:
            raise WikiUnavailable("down")
        return next((v for k, v in self.results.items() if k in query.lower()), [])

    def get_page(self, title):
        from src.kb.wiki import PageNotFound
        if title not in {t for ts in self.results.values() for t in ts}:   # like Wikipedia: unknown titles don't exist
            raise PageNotFound(title)
        return FakePage(title)


@pytest.fixture(autouse=True)
def offline_sample_market(monkeypatch):
    """Market tests run on the bundled sample provider only (no Yahoo calls)."""
    import yfinance
    from src.core import market_service

    class OfflineSearch:                           # Yahoo symbol/news search: no hits, no network
        def __init__(self, *a, **k): self.quotes, self.news = [], []
    monkeypatch.setattr(yfinance, "Search", OfflineSearch)
    monkeypatch.setattr(market_service, "PROVIDERS", {"sample": market_service.PROVIDERS["sample"]})


@pytest.fixture(autouse=True)
def offline_no_llm():
    set_wiki_client(FakeWiki())
    set_kb_searcher(lambda query, k=None: [])      # empty knowledge base: agents use the (fake) Wikipedia path
    llm_module.set_llm(None)
    set_symbol_resolver(lambda name: None)         # no Yahoo symbol search
    set_news_indexer(lambda symbol, items: 0)      # no Qdrant writes
    set_news_searcher(lambda *a: [])               # empty news index (no Qdrant reads; tests that need stories set their own)
    symbols_module.clear_cache()
    yield
    set_symbol_resolver(None)
    set_news_indexer(None)
    set_news_searcher(None)
    llm_module.clear_llm_override()
    set_wiki_client(None)
    set_kb_searcher(None)
