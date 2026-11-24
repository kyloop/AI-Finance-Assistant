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
from src.workflow import nodes as NODES
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
    assert NEWS.tickers_in("Is the US stock market up or down today?", {"tickers": []}) == []     # a country, not a ticker
    assert NEWS.tickers_in("is NVDA stock up?", {"tickers": []}) == ["NVDA"]


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


def test_summarize_the_news_reads_as_market_headlines_and_offers_other_readings(db, monkeypatch):
    calls = fake_feed(monkeypatch, {"MARKET": [story(1, "Stocks rally on Fed hopes")]})
    set_news_searcher(lambda *a: pytest.fail("'summarize' is phrasing, not a topic to search for"))
    s = ask("summarize the news today. or the latest?", db)
    assert calls == ["MARKET"] and "Stocks rally on Fed hopes" in s["final_response"]
    assert "I took this as the latest market-wide headlines" in s["final_response"] and s["final_response"].endswith(DISCLAIMER)
    assert s["choices"] == NODES.NEWS_MARKET_ALTERNATIVES and s["answered"] is True


def test_named_ticker_is_answered_without_a_reading_note(db, monkeypatch):
    fake_feed(monkeypatch, {"NVDA": [story(1, "Nvidia earnings beat")]})
    s = ask("What's the latest news on NVDA?", db)
    assert "I took this as" not in s["final_response"] and s["choices"] == []


def test_selected_stock_is_not_assumed_from_it_or_that(db, monkeypatch):
    calls = fake_feed(monkeypatch, {"MARKET": [story(1, "Stocks rally")], "NVDA": [story(2, "Nvidia earnings beat")]})
    view = {"tab": "Live Market", "selected": "NVDA"}
    for q in ("What's the latest on that?", "Any news about it today?"):
        ask(q, db, view=view)
    assert "NVDA" not in calls and "MARKET" in calls
    ask("Any news on this one?", db, view=view)
    assert calls[-1] == "NVDA"


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
    assert set(got) == {"s1", "s2"} and got["s1"]["tickers"] == ["NVDA", "market:us_indices"] and got["s2"]["tickers"] == ["market:us_indices"]


def test_ingest_keeps_the_thumbnail_and_fills_it_in_on_a_story_stored_without_one(index):
    news_index.ingest("NVDA", [story(1, "Nvidia chip export curbs widen"), {**story(2, "Fed holds rates"), "thumbnail": "https://img/2"}],
                      client=index)
    news_index.ingest("AAPL", [{**story(1, "Nvidia chip export curbs widen"), "thumbnail": "https://img/1"}], client=index)
    got = {h["story_id"]: h for h in news_index.search(index, "nvidia fed", days=7, k=5)}
    assert got["s1"]["thumbnail"] == "https://img/1" and got["s1"]["tickers"] == ["AAPL", "NVDA"]
    assert got["s2"]["thumbnail"] == "https://img/2"


def test_market_stories_are_tagged_with_their_term_and_group(index):
    assert news_index.ingest("JPY=X", [story(1, "Yen slides as BOJ holds")], client=index) == 1
    assert news_index.ingest("DXY", [story(1, "Yen slides as BOJ holds")], client=index) == 0
    got = news_index.search(index, "yen", tickers=["market:forex"], days=7, k=5)
    assert [h["story_id"] for h in got] == ["s1"] and got[0]["tickers"] == ["DXY", "JPY=X", "market:forex"]


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
    for sym, ep, age in (("AAPL", "quote", 1), ("TSLA", "news", 2), ("OLD", "quote", 30), ("^GSPC", "quote", 0), ("MSFT", "history", 0),
                         ("DX-Y.NYB", "quote", 3), ("EURGBP=X", "quote", 3), ("^TNX", "quote", 4)):
        db.add(MarketCache(key=f"{sym}{ep}", provider="yfinance", symbol=sym, endpoint=ep, payload={}, fetched_at=now - timedelta(days=age),
                           expires_at=now))
    db.commit()
    assert news_index.tracked_symbols(db) == ["MARKET", "VTI", "AAPL", "TSLA", "DXY", "^TNX"]      # markets by news term; EUR/GBP has none


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
    assert "name a company, ticker or market" in s["final_response"] and s["answered"] is False
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


def test_news_asks_yahoo_search_first_and_skips_the_ticker_feed_when_it_answers(monkeypatch):
    import yfinance

    class Ticker:
        def get_news(self, count): pytest.fail("the ticker feed is only a fallback")

    class FakeSearch:
        def __init__(self, query, **kw):
            self.news = [{"uuid": f"{query}-1", "title": f"{query} story", "link": f"https://x.test/{query}", "providerPublishTime": 1_790_000_000}]
    monkeypatch.setattr(ms, "_yf_ticker", lambda sym: Ticker())
    monkeypatch.setattr(yfinance, "Search", FakeSearch)
    assert [i["title"] for i in ms._yf_news("EURUSD=X")["items"]] == ["EURUSD=X story"]


def test_news_drops_the_same_headline_listed_under_another_id(monkeypatch):
    import yfinance

    class FakeSearch:
        def __init__(self, query, **kw):
            self.news = [{"uuid": "a", "title": "Brands pull ahead", "link": "https://x.test/a", "providerPublishTime": 1_790_000_000},
                         {"uuid": "b", "title": "Brands  pull ahead ", "link": "https://x.test/b", "providerPublishTime": 1_790_000_000},
                         {"uuid": "c", "title": "Another story", "link": "https://x.test/c", "providerPublishTime": 1_790_000_100}]
    monkeypatch.setattr(yfinance, "Search", FakeSearch)
    assert [i["id"] for i in ms._yf_news("NVDA")["items"]] == ["c", "a"]


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


def test_time_words_are_not_companies():
    assert SYM.keyword_mentions("summary for earlier news of the day.") == []         # "day" once resolved to DHSB
    assert SYM.keyword_mentions("latest news of the morning") == []


def test_a_company_the_user_rules_out_is_not_looked_up():
    assert SYM.excluded("I am not looking for DHSB news. I just want earlier news of today") == {"dhsb"}
    assert SYM.excluded("I don't want Tesla, other than Apple") == {"tesla", "apple"}
    assert SYM.excluded("Is there no Apple news?") == set()                           # asks for it
    seen = resolver({"dhsb": {"symbol": "DHSB", "name": "Day Hagan Smart Buffer ETF"}})
    assert SYM.resolve("I am not looking for DHSB news. I just want earlier news of today") == [] and seen == []


def test_ruled_out_ticker_gives_the_market_headlines(db, monkeypatch):
    calls = fake_feed(monkeypatch, {"MARKET": [story(1, "Stocks rally")], "DHSB": []})
    set_news_searcher(lambda *a: pytest.fail("'earlier news of today' is not a topic"))
    s = ask("I am not looking for DHSB news. I just want earlier news of today", db)
    assert calls == ["MARKET"] and "Stocks rally" in s["final_response"]


def test_each_headline_bullet_ends_with_its_source_link():
    # The synthesizer's bullets for two of three stories (from a real trace): title + byline, summary on the next line.
    text = ("Here are some examples:\n\n"
            "- **How AI Factory Expansion Will Impact NVIDIA (NVDA) Investors** (Simply Wall St., Oct 30, 03:15 UTC)  \n"
            "  Discusses how the growth of AI factories could influence NVIDIA's stock.\n\n"
            "- **Nvidia's web of AI bets: smart strategy or bubble risk?** (AFP, Oct 30, 01:17 UTC): Examines NVIDIA's investments.\n\n"
            "That's the overview.")
    sources = [{"id": "news:a", "title": "How AI Factory Expansion Will Impact NVIDIA (NVDA) Investors (Simply Wall St.)", "url": "https://x.test/a"},
               {"id": "news:b", "title": "Nvidia's web of AI bets: smart strategy or bubble risk? (AFP)", "url": "https://x.test/b"},
               {"id": "news:c", "title": "A story the answer left out (Reuters)", "url": "https://x.test/c"}]
    lines = NODES.link_sources(text, sources).split("\n")
    assert lines[3] == "  Discusses how the growth of AI factories could influence NVIDIA's stock. [Source](https://x.test/a)"
    assert lines[5].endswith("Examines NVIDIA's investments. [Source](https://x.test/b)")
    assert "x.test/c" not in "\n".join(lines) and lines[2].endswith("UTC)  ")      # unnamed source stays below; title line untouched
    assert NODES.link_sources("\n".join(lines), sources) == "\n".join(lines)         # already linked: not added twice


class ReplyLLM:
    """Answers every prompt with one scripted reply and records the prompts."""
    model = "scripted"

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def invoke(self, messages):
        from langchain_core.messages import AIMessage
        self.prompts.append(messages[-1][1] if isinstance(messages[-1], tuple) else messages[-1].content)
        return AIMessage(content=self.reply)


def test_headlines_copied_from_earlier_answers_are_dropped_and_this_answers_stories_linked():
    # From real traces: the model repeats the last answer's headlines, and shortens long titles.
    from src.core import llm as llm_module
    llm = ReplyLLM("NVDA returned **-6.5%** last month.\n\n"
                   "- **The tech ‘death spiral’ that could destroy the AI boom** (The Telegraph, Oct 24, 07:00 UTC)  \n"
                   "  Explores concerns about the AI growth trend.\n"
                   "- **Jensen Huang Says AI Agents Have Sent GPU Demand Through the Roof** (Benzinga): demand surged.\n"
                   "- **Apple Inc.** (AAPL): +4.8%")
    llm_module.set_llm(llm)
    news = {"agent": "news", "status": "answered",
            "content": "Stories with an excerpt of each story:\n- **Jensen Huang Says AI Agents Have Sent GPU Demand Through the Roof: "
                       "Munster Sees Billions** (Benzinga, Oct 25, 01:30 UTC): demand surged.",
            "sources": [{"id": "news:b", "title": "Jensen Huang Says AI Agents Have Sent GPU Demand Through the Roof: Munster Sees "
                                                  "Billions (Benzinga)", "url": "https://x.test/b"}]}
    market = {"agent": "market", "status": "answered", "content": "- NVDA last month: total return **-6.5%**", "sources": []}
    out = NODES.synthesizer_node({"question": "How has AI affected NVIDIA?", "agent_outputs": {"news": news, "market": market},
                                  "entities": {}, "profile": {}, "history": []}, {})
    assert "[market]" in llm.prompts[-1] and "demand surged." in llm.prompts[-1]
    assert out["final_response"] == ("NVDA returned **-6.5%** last month.\n\n"
                                     "- **Jensen Huang Says AI Agents Have Sent GPU Demand Through the Roof** (Benzinga): demand surged. "
                                     "[Source](https://x.test/b)\n- **Apple Inc.** (AAPL): +4.8%")


def test_news_alone_is_still_written_by_the_model():
    from src.core import llm as llm_module
    llm = ReplyLLM("- **Nvidia's AI bets** (AFP, Oct 30, 01:17 UTC)")
    llm_module.set_llm(llm)
    news = {"agent": "news", "status": "answered", "content": "- **Nvidia's AI bets** (AFP, Oct 30, 01:17 UTC)",
            "sources": [{"id": "news:b", "title": "Nvidia's AI bets (AFP)", "url": "https://x.test/b"}]}
    out = NODES.synthesizer_node({"question": "news on NVIDIA?", "agent_outputs": {"news": news}, "entities": {}, "profile": {},
                                  "history": []}, {})
    assert "[news]" in llm.prompts[-1] and out["final_response"] == "- **Nvidia's AI bets** (AFP, Oct 30, 01:17 UTC) [Source](https://x.test/b)"


# ---- story pages ----------------------------------------------------------------------------------------------
from src.core import articles as A  # noqa: E402
from src.workflow.tools import set_article_reader  # noqa: E402

PAGE = """<html><head><meta name="description" content="Teaser: Nvidia bets on AI."></head><body>
<nav><p>Home News Finance Sports More News US Politics World Tech Science Originals Weather</p></nav>
<div class="body-wrap">
<p>Benzinga and Yahoo Finance LLC may earn commission or revenue on some items through the links below.</p>
<p>Nvidia CEO Jensen Huang said GPU demand has gone through the roof because of AI agents, at a keynote in Berlin.</p>
<p><a href="/x">A single bad hire can set a startup back years. Here are the 5 hires founders misjudge</a></p>
<blockquote><p>My take: one of the clearer reasons compute demand should keep ramping for years. pic.twitter.com/x</p></blockquote>
<p>Trending: Avoid the #1 Investing Mistake: How Your 'Safe' Holdings Could Be Costing You Big Time</p>
<p>Munster estimated that agents can consume ten to fifteen times the tokens of a chatbot over a day.</p>
<p>Read Next: Think you're saving enough for your kids? You might be dangerously off, see why</p>
<p>For accredited investors, EquityMultiple provides access to vetted commercial real estate deals.</p>
</div></body></html>"""
YAHOO = "https://finance.yahoo.com/news/a-1.html"
REAL_TIME = time.time


def test_a_story_page_gives_the_article_without_promos_embeds_or_sponsors():
    assert A.extract(PAGE, 1500) == ("Nvidia CEO Jensen Huang said GPU demand has gone through the roof because of AI agents, at a "
                                     "keynote in Berlin. Munster estimated that agents can consume ten to fifteen times the tokens "
                                     "of a chatbot over a day.")
    assert A.extract(PAGE, 120) == "Nvidia CEO Jensen Huang said GPU demand has gone through the roof because of AI agents, at a keynote in Berlin."
    teaser = "<html><head><meta name='description' content='Working with Nvidia, ADI enters a buy zone.'></head><body></body></html>"
    assert A.extract(teaser, 1500) == "Working with Nvidia, ADI enters a buy zone."          # a story Yahoo only links to
    assert A.is_yahoo(YAHOO) and not A.is_yahoo("https://reuters.com/a") and not A.is_yahoo("https://finance.yahoo.com.evil.test/a")


def test_story_pages_are_read_once_and_kept_for_three_days(index, monkeypatch):
    news_index.ingest("NVDA", [story(1, summary="", url=YAHOO), story(2, url="https://finance.yahoo.com/news/b.html"),
                               story(3, summary="", url="https://reuters.com/c")], client=index)
    reads = []
    fetch = lambda url: reads.append(url) or f"text of {url}"                                    # noqa: E731
    stories = [story(1, summary="", url=YAHOO), story(2, url="https://finance.yahoo.com/news/b.html"), story(3, summary="", url="https://reuters.com/c")]
    assert news_index.articles(stories, index, fetch) == {"s1": f"text of {YAHOO}"}             # has a summary / not Yahoo: not read
    assert news_index.articles(stories, index, fetch) == {"s1": f"text of {YAHOO}"} and reads == [YAHOO]   # second time: from the index
    hit_ = news_index.search(index, "chip", days=7, k=5)
    assert news_index.articles([h for h in hit_ if h["story_id"] == "s1"], index, fetch) == {"s1": f"text of {YAHOO}"} and len(reads) == 1

    monkeypatch.setattr(news_index.time, "time", lambda: REAL_TIME() + 3 * 86400 + 1)          # three days on: read again, not reused
    assert news_index.articles(stories, index, fetch) == {"s1": f"text of {YAHOO}"} and len(reads) == 2


def test_prune_removes_excerpts_older_than_three_days_but_keeps_the_story(index, monkeypatch):
    news_index.ingest("NVDA", [story(1, summary="", url=YAHOO)], client=index)
    news_index.articles([story(1, summary="", url=YAHOO)], index, lambda url: "what the story says")
    news_index.prune(index)
    assert news_index.search(index, "chip", days=7, k=5)[0]["article"] == "what the story says"   # still fresh: kept
    monkeypatch.setattr(news_index.time, "time", lambda: REAL_TIME() + 3 * 86400 + 1)
    news_index.prune(index)
    (h,) = news_index.search(index, "chip", days=7, k=5)
    assert "article" not in h and "article_fetched_at" not in h and h["title"] == "Chip stocks slide on export curbs"


def test_a_page_without_text_is_not_read_again_and_a_story_not_indexed_yet_is(index):
    news_index.ingest("NVDA", [story(1, summary="", url=YAHOO)], client=index)
    reads = []
    fetch = lambda url: reads.append(url) or ""                                                   # noqa: E731
    new = story(9, summary="", url="https://finance.yahoo.com/news/new.html")
    assert news_index.articles([story(1, summary="", url=YAHOO), new], index, fetch) == {}
    assert news_index.articles([story(1, summary="", url=YAHOO), new], index, fetch) == {}
    assert reads.count(YAHOO) == 1 and reads.count(new["url"]) == 2


def test_the_news_agent_shows_what_the_stories_say(db, monkeypatch):
    fake_feed(monkeypatch, {"NVDA": [story(1, "Nvidia AI bets draw scrutiny", summary="", url=YAHOO)]})
    set_article_reader(lambda stories: {"s1": "Nvidia has invested $3 billion in Meta's share sale."})
    s = ask("latest news on NVDA", db)
    out = s["agent_outputs"]["news"]
    assert "with an excerpt of each story" in out["content"] and "Nvidia has invested $3 billion" in out["content"]
    assert "read 1 of 1 story pages" in " ".join(s["trace"])


def test_failing_story_pages_still_leave_the_headlines(db, monkeypatch):
    fake_feed(monkeypatch, {"NVDA": [story(1, "Nvidia AI bets draw scrutiny", summary="", url=YAHOO)]})
    set_article_reader(lambda stories: (_ for _ in ()).throw(RuntimeError("qdrant down")))
    s = ask("latest news on NVDA", db)
    assert "Nvidia AI bets draw scrutiny" in s["final_response"] and "story pages → failed (RuntimeError)" in " ".join(s["trace"])


def test_each_story_is_summarized_once_and_the_summary_is_kept_with_the_excerpt(index, monkeypatch):
    news_index.ingest("NVDA", [story(1, summary="", url=YAHOO)], client=index)
    reads, briefs = [], []
    fetch = lambda url: reads.append(url) or "The whole article text."                           # noqa: E731
    summarize = lambda title, text: briefs.append((title, text)) or "Two or three sentences."     # noqa: E731
    stories = [story(1, summary="", url=YAHOO)]
    assert news_index.articles(stories, index, fetch, summarize) == {"s1": "Two or three sentences."}
    assert news_index.articles(stories, index, fetch, summarize) == {"s1": "Two or three sentences."}   # from the index
    assert len(reads) == 1 and briefs == [(stories[0]["title"], "The whole article text.")]
    (h,) = news_index.search(index, "chip", days=7, k=5)
    assert h["article"] == "The whole article text." and h["article_summary"] == "Two or three sentences."
    assert news_index.articles(stories, index, fetch) == {"s1": "Two or three sentences."}          # basic mode keeps a stored one

    monkeypatch.setattr(news_index.time, "time", lambda: REAL_TIME() + 3 * 86400 + 1)
    news_index.prune(index)
    (h,) = news_index.search(index, "chip", days=7, k=5)
    assert "article_summary" not in h


def test_an_excerpt_kept_without_a_summary_is_read_again_and_summarized(index):
    news_index.ingest("NVDA", [story(1, summary="", url=YAHOO)], client=index)
    reads = []
    fetch = lambda url: reads.append(url) or f"Article text {len(reads)}."                       # noqa: E731
    stories = [story(1, summary="", url=YAHOO)]
    assert news_index.articles(stories, index, fetch) == {"s1": "Article text 1."}                # no LLM: the excerpt
    assert news_index.articles(stories, index, fetch) == {"s1": "Article text 1."} and len(reads) == 1
    # an excerpt from before summaries (shorter then): the page is read again for the summary
    assert news_index.articles(stories, index, fetch, lambda t, x: None) == {"s1": "Article text 2."}   # failed: the excerpt
    assert news_index.articles(stories, index, fetch, lambda t, x: f"Summary of {x}") == {"s1": "Summary of Article text 3."}
    assert news_index.articles(stories, index, fetch, lambda t, x: "unused") == {"s1": "Summary of Article text 3."}
    assert len(reads) == 3


def test_the_summarizer_asks_for_two_or_three_sentences_from_the_article_only():
    from src.core import llm as llm_module
    from src.workflow import news as NEWS

    seen = []

    class Fake:
        def invoke(self, messages):
            seen.append(messages)
            return type("R", (), {"content": "  JPMorgan moved its bond ETF.\n It lists on NYSE Arca from Dec 16. "})()

    llm_module.set_llm(Fake())
    assert NEWS.summarize_story("JBND moves to NYSE Arca", "J.P. Morgan said...") == \
        "JPMorgan moved its bond ETF. It lists on NYSE Arca from Dec 16."
    assert "2-3 plain sentences" in seen[0][0][1] and "ONLY the article text" in seen[0][0][1]
    assert "Headline: JBND moves to NYSE Arca" in seen[0][1][1]


def test_the_question_names_how_many_stories_and_how_many_days():
    assert NEWS.count_asked("can you show the latest 5 news?") == 5
    assert NEWS.count_asked("top three stories on NVDA") == 3
    assert NEWS.count_asked("give me 40 headlines") == 15                       # capped
    assert NEWS.count_asked("latest 10 days news about AAPL") is None           # a window, not a count
    assert NEWS.time_window("latest 10 days news about AAPL") == 10
    assert NEWS.time_window("10 days of AAPL news") == 10
    assert NEWS.topic_words("show the latest 15 news", []) == []                # a count is not a topic


def test_latest_n_news_shows_that_many(db, monkeypatch):
    fake_feed(monkeypatch, {"NVDA": [story(i, f"Nvidia story {i}") for i in range(1, 30)]})
    s = ask("show the latest 5 news on NVDA", db)
    out = s["agent_outputs"]["news"]
    assert out["content"].count("- **") == 5
    assert "Nvidia story 1**" in out["content"] and "Nvidia story 6**" not in out["content"]     # the newest five
    assert "showing 5 of 5 asked" in " ".join(s["trace"])


def test_fewer_stories_than_asked_says_so(db, monkeypatch):
    fake_feed(monkeypatch, {"NVDA": [story(1, "Nvidia story 1"), story(2, "Nvidia story 2")]})
    out = ask("show the latest 5 news on NVDA", db)["agent_outputs"]["news"]
    assert "You asked for 5 stories; only 2 about NVDA were available" in out["content"]


def test_a_day_window_reaches_past_the_feed_into_the_indexed_stories(db, monkeypatch):
    from src.workflow.tools import set_news_lister
    fake_feed(monkeypatch, {"NVDA": [story(1, "Nvidia today"), story(30, "Nvidia yesterday")]})
    asked = []
    older = {**hit(2, title="Nvidia eight days ago"), "published": iso(days=8), "published_ts": time.time() - 8 * 86400}
    too_old = {**hit(3, title="Nvidia twelve days ago"), "published": iso(days=12), "published_ts": time.time() - 12 * 86400}
    set_news_lister(lambda tickers, days: asked.append((tickers, days)) or [older, too_old])
    s = ask("latest 10 days news about NVDA", db)
    out = s["agent_outputs"]["news"]["content"]
    assert asked == [(["NVDA"], 10)]
    assert "Nvidia today" in out and "Nvidia yesterday" in out and "Nvidia eight days ago" in out
    assert "twelve days" not in out                                              # outside the window
    assert out.index("Nvidia today") < out.index("Nvidia yesterday") < out.index("Nvidia eight days ago")   # newest first
    assert "3 stories from the last 10 days about NVDA, spread across the days" in out


def test_off_topic_stories_in_a_company_feed_are_dropped_before_any_page_is_read():
    from src.core import llm as llm_module
    llm = ReplyLLM('{"keep": [1, 3]}')
    llm_module.set_llm(llm)
    stories = [story(1, "JPMorgan moves its bond ETF"), story(2, "How much to save for retirement"),
               story(3, "Trump card-rate cap hits JPM")]
    kept, note = NODES._about(stories, ["JPMorgan Chase & Co."])
    assert [s["title"] for s in kept] == ["JPMorgan moves its bond ETF", "Trump card-rate cap hits JPM"]
    assert "2 of 3 headlines" in note and "2. How much to save for retirement" in llm.prompts[0]
    llm_module.set_llm(ReplyLLM("not json"))
    assert NODES._about(stories, ["JPMorgan"])[0] == stories                    # unusable reply: keep them all


def test_a_window_of_days_shows_each_days_news_not_only_todays(db, monkeypatch):
    from src.workflow.tools import set_news_lister
    today = [story(i, f"Nvidia today {i}") for i in range(1, 20)]                # a busy day: 19 stories within hours
    fake_feed(monkeypatch, {"NVDA": today})
    older = [{**hit(100 + d, title=f"Nvidia {d} days ago"), "published": iso(days=d), "published_ts": time.time() - d * 86400}
             for d in range(2, 9)]
    set_news_lister(lambda tickers, days: older)
    out = ask("latest 10 days news about NVDA", db)["agent_outputs"]["news"]["content"]
    assert out.count("- **") == 10                                               # one a day for a 10-day window
    assert all(f"Nvidia {d} days ago" in out for d in range(2, 9))


def test_the_question_without_its_subjects_time_and_count_is_what_the_topic_check_compares():
    assert NEWS.residual("What is the news related to Johnson & Johnson (JNJ) from the last 10 days?",
                         ["Johnson & Johnson", "JNJ"]) == "What is the news related to ?"
    assert NEWS.residual("Can you show the latest 5 news about AAPL?", ["AAPL"]) == "Can you show the latest news about ?"
    assert NEWS.residual("What is the news related to the housing market?") == "What is the news related to the housing market?"


def _topic_embedder(texts):
    # stands in for bge-small: a question that mentions a subject of its own points elsewhere than a plain request
    subjects = ("housing", "export", "lawsuit")
    return [[1.0, 0.0] if any(w in t.lower() for w in subjects) else [0.0, 1.0] for t in texts]


def test_a_plain_request_gets_the_latest_headlines_whatever_its_wording(db, monkeypatch):
    NEWS.set_news_embedder(_topic_embedder)
    fake_feed(monkeypatch, {"JNJ": [story(1, "Johnson & Johnson raises guidance")]})
    set_news_searcher(lambda *a: pytest.fail("a plain request must not be a topic search"))
    s = ask("What is the latest news related to JNJ?", db)                   # "related" is no topic
    assert "Johnson & Johnson raises guidance" in s["agent_outputs"]["news"]["content"]
    assert "topic check: latest news (similarity to a plain news request 1.00)" in " ".join(s["trace"])


def test_a_question_unlike_a_plain_request_searches_by_meaning(db, monkeypatch):
    NEWS.set_news_embedder(_topic_embedder)
    searched = []
    set_news_searcher(lambda q, tickers, days, k: searched.append((q, tickers)) or [hit(1, title="Home sales fall as mortgage rates climb")])
    s = ask("What is the news related to the housing market?", db)
    assert searched and searched[0][0] == "What is the news related to the housing market?"
    assert "Home sales fall" in s["agent_outputs"]["news"]["content"]
    assert "topic check: 'What is the news related to the housing market?'" in " ".join(s["trace"])
