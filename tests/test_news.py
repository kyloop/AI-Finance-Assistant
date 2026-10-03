"""News agent and news index: routing, live-vs-search choice, the Qdrant story index (in-memory, fake embedder) and the poll's ticker set."""
import hashlib
import re
import time
from datetime import datetime, timedelta, timezone

import pytest
from qdrant_client import QdrantClient
from sqlalchemy.orm import sessionmaker

from src.core import market_service as ms
from src.core.config import DISCLAIMER, get_config
from src.db.base import Base
from src.db.models import Holding, MarketCache, Portfolio, Session as UserSession
from src.db.session import make_engine
from src.rag import news as news_index
from src.workflow import news as NEWS
from src.workflow import router as R
from src.workflow.graph import run_chat
from src.workflow.nodes import route_after_router
from src.workflow.tools import set_news_searcher

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate"}
MIN = get_config()["news_index"]["min_score"]


@pytest.fixture
def db(tmp_path):
    """A file database, like production: agents run in parallel threads, and a shared in-memory connection can't serve two at once."""
    engine = make_engine(f"sqlite:///{tmp_path / 'news.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as s:
        yield s


def ask(q, db=None, **kw):
    return run_chat(q, history=[], profile=PROFILE, holdings=[], db=db, **kw)


def iso(**ago):
    return (datetime.now(timezone.utc) - timedelta(**ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def story(i, title="Chip stocks slide on export curbs", **kw):
    return {"id": f"s{i}", "title": title, "summary": "Shares of chipmakers fell.", "publisher": "Reuters",
            "url": f"https://x.test/{i}", "published": iso(hours=i), "thumbnail": None, **kw}


def hit(i=1, score=MIN + 0.15, **kw):
    s = story(i, **kw)
    return {"score": score, "story_id": s["id"], **{k: s[k] for k in ("title", "summary", "publisher", "url", "published")},
            "ingested_at": time.time(), "tickers": ["NVDA"]}


# ---- routing ------------------------------------------------------------------------------------------------
def test_news_questions_route_to_the_news_agent():
    for q in ("What's the latest news on NVDA?", "What has been said about chip export restrictions this week?",
              "Any headlines about the Fed today?", "what's happening with Apple"):
        assert "news" in R.classify(q), q
    assert R.AGENT_FOR_INTENT["news"] == "News" and "news" in R.INTENTS
    assert route_after_router({"intent": ["news"]}) == ["news_agent"]
    assert "news" not in R.classify("What is an ETF?")


def test_helpers_pick_live_feed_or_search():
    assert NEWS.topic_words("What's the latest news on NVDA?", ["NVDA"]) == []
    assert NEWS.topic_words("Any market news today?", []) == []
    assert NEWS.topic_words("latest on Apple", []) == []
    assert NEWS.topic_words("What's been said about chip export restrictions this week?", []) == ["chip", "export", "restrictions"]
    assert NEWS.time_window("news this week") == 7 and NEWS.time_window("news today") == 1 and NEWS.time_window("news") is None
    assert NEWS.time_window("past 3 days") == 3 and NEWS.time_window("this month", 14) == 14
    assert NEWS.tickers_in("TSLA news please", {"tickers": []}) == ["TSLA"]
    assert NEWS.tickers_in("any news on $PLTR?", {"tickers": ["NVDA"]}) == ["NVDA", "PLTR"]


# ---- the agent ----------------------------------------------------------------------------------------------
def fake_feed(monkeypatch, items_by_symbol):
    calls = []

    def news(symbol, **_):
        calls.append(symbol)
        if not items_by_symbol.get(symbol):
            raise ms.ProviderEmpty(symbol)
        return {"symbol": symbol, "items": items_by_symbol[symbol]}
    monkeypatch.setattr(ms, "PROVIDERS", {"fake": {"news": news}, "sample": ms.PROVIDERS["sample"]})
    return calls


def test_latest_on_a_ticker_uses_the_live_feed(db, monkeypatch):
    calls = fake_feed(monkeypatch, {"NVDA": [story(1, "Nvidia earnings beat"), story(2, "Nvidia unveils chip")]})
    set_news_searcher(lambda *a: pytest.fail("a plain 'latest' question must not hit vector search"))
    s = ask("What's the latest news on NVDA?", db)
    assert calls == ["NVDA"] and s["agents"][-1] == "News"
    assert "Nvidia earnings beat" in s["final_response"] and "Reuters" in s["final_response"] and s["final_response"].endswith(DISCLAIMER)
    assert [x["url"] for x in s["sources"]] == ["https://x.test/1", "https://x.test/2"]
    assert any(t.startswith("news_latest(NVDA) → 2 stories") for t in s["trace"])
    assert s["agent_outputs"]["news"]["data_info"]["freshness"] == "live"


def test_market_news_uses_the_market_feed(db, monkeypatch):
    calls = fake_feed(monkeypatch, {"MARKET": [story(1, "Stocks rally")]})
    s = ask("Any market news today?", db)
    assert calls == ["MARKET"] and "Stocks rally" in s["final_response"] and "headlines for the market" in s["final_response"]


def test_topic_question_searches_the_index_with_filters(db):
    seen = {}

    def searcher(query, tickers, days, k):
        seen.update(query=query, tickers=tickers, days=days, k=k)
        return [hit(1), hit(2, title="Export rules widen", score=MIN + 0.10), hit(3, title="Unrelated oil story", score=MIN + 0.02)]
    set_news_searcher(searcher)
    s = ask("What has been said about NVDA chip export restrictions this week?", db)
    assert seen["tickers"] == ["NVDA"] and seen["days"] == 7 and "export restrictions" in seen["query"]
    assert "Chip stocks slide on export curbs" in s["final_response"] and "last 7 days" in s["final_response"]
    assert [x["id"] for x in s["sources"]] == ["news:s1", "news:s2"] and s["answered"] is True
    assert s["agent_outputs"]["news"]["data_info"]["freshness"] == "cached" and any("news_search(7d, NVDA) → 2 stories" in t for t in s["trace"])


def test_irrelevant_matches_say_nothing_found_and_skip_wikipedia(db):
    set_news_searcher(lambda *a: [hit(1, score=MIN - 0.1)])
    s = ask("What has been said about lunar mining this week?", db)
    assert "found no news matching that" in s["final_response"] and "searched the indexed stories" in s["final_response"]
    assert s["answered"] is False and not s["sources"]
    assert not any("wiki" in t.lower() for t in s["trace"]) and s["agents"] == ["News"] and s["choices"] == []


def test_failing_index_is_reported_not_raised(db):
    def boom(*a):
        raise RuntimeError("qdrant down")
    set_news_searcher(boom)
    s = ask("What has been said about interest rate cuts?", db)
    assert "can't search my news index" in s["final_response"] and s["agents"] == ["News"]


def test_live_feed_empty_falls_back_to_the_index(db, monkeypatch):
    fake_feed(monkeypatch, {})
    set_news_searcher(lambda q, t, d, k: [hit(3)])
    s = ask("latest news on NVDA", db)
    assert "Chip stocks slide" in s["final_response"] and any(t.startswith("news_search") for t in s["trace"])


# ---- the index ----------------------------------------------------------------------------------------------
class FakeEmbedder:
    """Bag-of-words hashing vectors: texts sharing words are close, so search is meaningful without downloading the real model."""
    def embed(self, texts):
        class V(list):
            def tolist(self): return list(self)
        for t in texts:
            v = [0.0] * 384
            for w in re.findall(r"[a-z]+", t.lower().replace("represent this sentence for searching relevant passages", "")):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 384] += 1.0
            yield V(v)


@pytest.fixture
def index(monkeypatch):
    client = QdrantClient(":memory:")
    monkeypatch.setattr(news_index, "get_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(news_index, "_ready", False)
    return client


def test_ingest_dedupes_and_merges_tickers(index):
    a = story(1, "Nvidia chip export curbs widen")
    assert news_index.ingest("MARKET", [a, story(2, "Fed holds rates steady")], client=index) == 2
    assert news_index.ingest("NVDA", [a], client=index) == 0                       # same story: not added again
    got = {h["story_id"]: h for h in news_index.search(index, "export curbs", days=7, k=5)}
    assert set(got) == {"s1", "s2"} and got["s1"]["tickers"] == ["NVDA"] and got["s2"]["tickers"] == []


def test_search_filters_by_ticker_and_date_and_ranks_by_meaning(index):
    news_index.ingest("NVDA", [story(1, "Nvidia chip export curbs widen"), story(2, "Nvidia opens new data center")], client=index)
    news_index.ingest("AAPL", [story(3, "Apple chip export curbs hit suppliers"), story(4, "Apple old story", published=iso(days=10))], client=index)
    top = news_index.search(index, "chip export curbs", days=7, k=3)
    assert {top[0]["story_id"], top[1]["story_id"]} == {"s1", "s3"}
    assert [h["story_id"] for h in news_index.search(index, "chip export curbs", tickers=["AAPL"], days=7, k=5)] == ["s3"]
    assert "s4" not in {h["story_id"] for h in news_index.search(index, "Apple old story", days=7, k=5)}
    assert "s4" in {h["story_id"] for h in news_index.search(index, "Apple old story", days=14, k=5)}


def test_search_before_anything_is_indexed_returns_nothing(index):
    assert news_index.search(index, "anything", days=7, k=5) == []


def test_old_or_undated_stories_are_skipped_and_prune_deletes_expired(index, monkeypatch):
    assert news_index.ingest("NVDA", [story(1, published=iso(days=30)), story(2, published=None)], client=index) == 0
    news_index.ingest("NVDA", [story(3)], client=index)
    monkeypatch.setitem(get_config()["news_index"], "retention_days", 0)       # everything now counts as expired
    news_index.prune(index)
    monkeypatch.undo()
    assert news_index.search(index, "chip", days=14, k=5) == []


# ---- listener + tracked symbols -----------------------------------------------------------------------------
def test_fresh_yahoo_news_notifies_listeners_once(db, monkeypatch):
    fake_feed(monkeypatch, {"NVDA": [story(1)]})
    got = []
    monkeypatch.setattr(ms, "news_listeners", [lambda sym, items: got.append((sym, len(items)))])
    ms.get_market_data(db, "news", "NVDA")
    ms.get_market_data(db, "news", "NVDA")                                         # cached: nothing new to index
    assert got == [("NVDA", 1)]


def test_tracked_symbols_cover_market_holdings_and_recent_views(db):
    now = datetime.now(timezone.utc)
    db.add(UserSession(id="u1"))
    db.add(Portfolio(id=1, session_id="u1"))
    db.add(Holding(portfolio_id=1, ticker="VTI", shares=1))
    for sym, ep, age in (("AAPL", "quote", 1), ("TSLA", "news", 2), ("OLD", "quote", 30), ("^GSPC", "quote", 0), ("MSFT", "history", 0)):
        db.add(MarketCache(key=f"{sym}{ep}", provider="yfinance", symbol=sym, endpoint=ep, payload={}, fetched_at=now - timedelta(days=age),
                           expires_at=now))
    db.commit()
    assert news_index.tracked_symbols(db) == ["MARKET", "VTI", "AAPL", "TSLA"]


# ---- finding companies and tickers with tools ---------------------------------------------------------------
from src.core.market_service import set_symbol_resolver  # noqa: E402
from src.rag import tickers as T  # noqa: E402
from src.workflow import symbols as SYM  # noqa: E402
from src.workflow.tools import set_news_indexer  # noqa: E402

PALANTIR = {"symbol": "PLTR", "name": "Palantir Technologies Inc."}


def resolver(known):
    seen = []

    def fn(name):
        seen.append(name)
        return known.get(name.lower())
    set_symbol_resolver(fn)
    return seen


def test_mentions_found_by_phrasing_cues():
    assert SYM.keyword_mentions("what's the latest on Palantir") == ["Palantir"]
    assert SYM.keyword_mentions("latest news on palantir technologies this week") == ["palantir"]
    assert SYM.keyword_mentions("Meta Platforms stock news") == ["Meta Platforms"]
    assert SYM.keyword_mentions("what has been said about PLTR contracts") == ["PLTR"]
    assert SYM.keyword_mentions("latest news about chips and oil prices") == [] and SYM.keyword_mentions("news about the Fed") == [] and SYM.keyword_mentions("what did Trump say about chips") == []


def test_unknown_company_is_looked_up_then_its_headlines_fetched_live(db, monkeypatch):
    seen = resolver({"palantir": PALANTIR})
    calls = fake_feed(monkeypatch, {"PLTR": [story(1, "Palantir wins new Army contract")]})
    s = ask("what's the latest on Palantir", db)
    assert seen == ["Palantir"] and calls == ["PLTR"]
    assert "Palantir wins new Army contract" in s["final_response"] and "headlines for PLTR" in s["final_response"]
    assert any("resolved “Palantir” → PLTR" in t for t in s["trace"])


def test_topic_question_about_an_unindexed_ticker_fetches_indexes_and_searches_again(db, monkeypatch):
    resolver({"pltr": PALANTIR})
    calls = fake_feed(monkeypatch, {"PLTR": [story(1, "Palantir wins new Army contract")]})
    indexed, searches = [], []
    set_news_indexer(lambda sym, items: indexed.append((sym, [i["id"] for i in items])) or len(items))

    def searcher(q, tickers, days, k):
        searches.append(tickers)
        return [hit(1, title="Palantir wins new Army contract")] if indexed else []        # empty until the stories are indexed
    set_news_searcher(searcher)
    s = ask("what has been said about PLTR contracts this week", db)
    assert calls == ["PLTR"] and indexed == [("PLTR", ["s1"])] and searches == [["PLTR"], ["PLTR"]]
    assert "Palantir wins new Army contract" in s["final_response"] and s["answered"] is True
    assert any("1 newly indexed" in t for t in s["trace"])


def test_no_story_on_the_topic_shows_the_latest_headlines_instead_of_nothing(db, monkeypatch):
    resolver({"pltr": PALANTIR})
    fake_feed(monkeypatch, {"PLTR": [story(1, "Palantir wins new Army contract")]})
    set_news_searcher(lambda *a: [])
    s = ask("what has been said about PLTR lawsuits this week", db)
    assert "found no stories about that specifically" in s["final_response"] and "Palantir wins new Army contract" in s["final_response"]
    assert s["answered"] is True and s["agents"][-1] == "News"


def test_nothing_anywhere_says_what_was_tried(db, monkeypatch):
    resolver({})
    fake_feed(monkeypatch, {})
    set_news_searcher(lambda *a: [])
    s = ask("what has been said about lunar mining this week", db)
    assert "found no news matching that" in s["final_response"] and "searched the indexed stories" in s["final_response"]
    assert "name a company or ticker" in s["final_response"] and s["answered"] is False
    s = ask("latest news on ZZZZ", db)                                           # a ticker with no feed: the fetch is reported too
    assert "Yahoo returned no headlines for ZZZZ" in s["final_response"]


def test_market_agent_looks_up_a_named_company_for_a_quote(db, monkeypatch):
    resolver({"palantir": PALANTIR})
    quote = {"symbol": "PLTR", "name": "Palantir Technologies Inc.", "price": 90.0, "prev_close": 88.0, "change": 2.0, "change_pct": 0.0227,
             "volume": 1, "day_high": 91.0, "day_low": 87.0}
    monkeypatch.setattr(ms, "PROVIDERS", {"fake": {"quote": lambda symbol, **_: quote | {"symbol": symbol}}, "sample": ms.PROVIDERS["sample"]})
    s = ask("what's the price of Palantir", db)
    assert "Palantir Technologies Inc." in s["final_response"] and "$90.00" in s["final_response"]
    assert not any("wiki" in t.lower() for t in s["trace"])


def test_a_listed_ticker_in_a_qa_looking_question_gets_a_quote(db, monkeypatch):
    """"what about the company with ticker SDEV?" is not a knowledge-base question: SDEV is only in the ticker directory, not the bundled list."""
    set_symbol_resolver(None)
    monkeypatch.setattr(ms, "_yf_resolve", lambda name: None)
    T.set_directory([{"symbol": "SDEV", "name": "Stablecoin Development Corporation", "exchange": "NYSE American", "asset_type": "stock", "rank": 4326}])
    quote = {"symbol": "SDEV", "name": "Stablecoin Development Corporation", "price": 4.5, "prev_close": 4.0, "change": 0.5, "change_pct": 0.125,
             "volume": 1, "day_high": 5.0, "day_low": 4.0}
    monkeypatch.setattr(ms, "PROVIDERS", {"fake": {"quote": lambda symbol, **_: quote | {"symbol": symbol}}, "sample": ms.PROVIDERS["sample"]})
    for q in ("what about the company with ticker SDEV?", "tell me about SDEV", "price of ticker sdev"):
        s = ask(q, db)
        assert "Stablecoin Development Corporation" in s["final_response"] and "$4.50" in s["final_response"], q
        assert s["agents"] == ["Market Analysis"], q
    assert "Market Analysis" not in ask("what is a REIT?", db)["agents"]
    T.set_directory(None)


def test_listed_ticker_overrides_a_qa_news_guess():
    from src.workflow.nodes import _with_listed_tickers
    T.set_directory([{"symbol": "SDEV", "name": "Stablecoin Development Corporation", "exchange": "", "asset_type": "stock", "rank": 4326}])
    q = "what about the company witht ticker SDEV?"                       # seen live after a Q&A turn: the router said qa, news
    assert _with_listed_tickers(["qa", "news"], q) == ["news", "market"]
    assert _with_listed_tickers(["qa"], q) == ["market"]
    assert _with_listed_tickers(["market", "news"], q) == ["market", "news"]
    long = "explain how a price to earnings ratio works in general terms and also tell me everything you know about SDEV please"
    assert _with_listed_tickers(["qa"], long) == ["qa", "market"]         # a long question may still have a concept to explain
    assert _with_listed_tickers(["qa"], "what is a REIT?") == ["qa"]
    T.set_directory(None)


def test_symbol_resolution_validates_names_and_survives_a_dead_network(monkeypatch):
    import yfinance

    class FakeSearch:
        def __init__(self, query, **_):
            self.quotes = {"palantir": [{"symbol": "PLTRX", "quoteType": "MUTUALFUND", "shortname": "Palantir Fund"},
                                        {"symbol": "PLTR", "quoteType": "EQUITY", "shortname": "Palantir Technologies Inc."}],
                           "trump": [{"symbol": "DJT", "quoteType": "EQUITY", "shortname": "Trump Media & Technology Group"}],
                           "chips": [{"symbol": "UNIC.PA", "quoteType": "ETF", "shortname": "Amundi Global Memory Chips UCITS ETF"}],
                           "coca-cola": [{"symbol": "KO", "quoteType": "EQUITY", "shortname": "The Coca-Cola Company"}],
                           "meta platforms": [{"symbol": "META", "quoteType": "EQUITY", "shortname": "Meta Platforms, Inc."}]}.get(query.lower(), [])
    monkeypatch.setattr(yfinance, "Search", FakeSearch)
    set_symbol_resolver(None)
    T.set_directory([])                                                          # this test is about Yahoo's answers, not the ticker directory
    assert ms.resolve_symbol("Palantir")["symbol"] == "PLTR"                     # funds skipped, name matched
    assert ms.resolve_symbol("chips") is None                                    # the ETF's name only contains the word
    assert ms.resolve_symbol("Coca-Cola")["symbol"] == "KO" and ms.resolve_symbol("Meta Platforms")["symbol"] == "META"
    class Dead:
        def __init__(self, *a, **k): raise OSError("no network")
    monkeypatch.setattr(yfinance, "Search", Dead)
    set_symbol_resolver(None)
    assert ms.resolve_symbol("Apple")["symbol"] == "AAPL" and ms.resolve_symbol("Nowhere Corp") is None     # bundled list, offline
    T.set_directory(None)


def test_news_falls_back_to_yahoo_search_when_the_ticker_feed_is_empty(monkeypatch):
    import yfinance

    class Ticker:
        def get_news(self, count): return []                                          # the ticker feed is down or empty

    class FakeSearch:
        def __init__(self, query, **kw):
            self.news = [{"uuid": "u1", "title": "Palantir lands Army deal", "publisher": "Reuters", "link": "https://x.test/u1",
                          "providerPublishTime": 1_790_000_000, "thumbnail": {"resolutions": [{"url": "https://img/1"}]}},
                         {"title": "no link, dropped"}]
    monkeypatch.setattr(ms, "_yf_ticker", lambda sym: Ticker())
    monkeypatch.setattr(yfinance, "Search", FakeSearch)
    out = ms._yf_news("PLTR")["items"]
    assert len(out) == 1 and out[0]["title"] == "Palantir lands Army deal" and out[0]["summary"] == "" and out[0]["id"] == "u1"
    assert out[0]["published"].endswith("Z") and out[0]["url"] == "https://x.test/u1" and out[0]["thumbnail"] == "https://img/1"


def test_resolved_names_are_saved_and_reused(monkeypatch):
    store = {}
    monkeypatch.setattr(ms, "alias_store", (store.get, store.__setitem__))
    set_symbol_resolver(None)
    T.set_directory([])                                                             # the ticker directory doesn't know it: Yahoo does
    monkeypatch.setattr(ms, "_yf_resolve", lambda name: {"symbol": "PLTR", "name": "Palantir Technologies Inc."})
    assert ms.resolve_symbol("Palantir")["symbol"] == "PLTR" and store == {"palantir": {"symbol": "PLTR", "name": "Palantir Technologies Inc."}}
    monkeypatch.setattr(ms, "_yf_resolve", lambda name: pytest.fail("a saved name must not be looked up again"))
    ms._resolved.clear()                                                            # a restart: only the saved names remain
    assert ms.resolve_symbol("palantir")["symbol"] == "PLTR"
    T.set_directory(None)
