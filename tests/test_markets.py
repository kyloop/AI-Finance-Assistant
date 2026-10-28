"""Markets that aren't companies (src/data/markets.yaml): lookup, finding them in a question with and without an LLM, the market and
news agents, story tags, the web-news fallback and the proofreader's negation rewrite."""
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from src.core import llm as llm_module
from src.core import market_service as ms
from src.core import tavily
from src.db.base import Base
from src.db.session import make_engine
from src.rag import markets as M
from src.rag import tickers as T
from src.workflow import symbols as SYM
from src.workflow.graph import run_chat
from src.workflow.nodes import _proofread_ok
from src.workflow.tools import set_news_indexer, set_news_searcher

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate"}


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'markets.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as s:
        yield s


def ask(q, db, history=None):
    return run_chat(q, history=history or [], profile=PROFILE, holdings=[], db=db)


def iso(**ago):
    return (datetime.now(timezone.utc) - timedelta(**ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def story(i, title):
    return {"id": f"s{i}", "title": title, "summary": "", "publisher": "Wire", "url": f"https://x.test/{i}", "published": iso(hours=i)}


def fake_feed(monkeypatch, items_by_term):
    calls = []

    def news(symbol, **_):
        calls.append(symbol)
        if not items_by_term.get(symbol):
            raise ms.ProviderEmpty(symbol)
        return {"symbol": symbol, "items": items_by_term[symbol]}

    def quote(symbol, **_):
        calls.append(f"quote:{symbol}")
        return {"symbol": symbol, "name": symbol, "price": 1.1218, "prev_close": 1.1201, "change": 0.0017, "change_pct": 0.0015,
                "volume": 0, "day_high": 1.123, "day_low": 1.118}
    monkeypatch.setattr(ms, "PROVIDERS", {"fake": {"news": news, "quote": quote}, "sample": ms.PROVIDERS["sample"]})
    return calls


class SubjectLLM:
    """Router -> `intents`; proofreader -> `proofread` (or the message unchanged); subject prompt -> `subjects`; else plain text."""
    model = "fake"

    def __init__(self, intents, subjects, proofread=None):
        self.intents, self.subjects, self.proofread, self.calls = intents, subjects, proofread, []

    def invoke(self, messages):
        system, user = messages[0][1], messages[1][1]
        if "You are the proofreader" in system:
            self.calls.append("proofread")
            reply = json.dumps({"question": self.proofread or user.rsplit("Message: ", 1)[-1], "follow_up": False})
        elif "You are the router" in system:
            self.calls.append("router")
            reply = json.dumps({"intents": self.intents, "confidence": 0.9})
        elif "Find what the latest message" in system:
            self.calls.append("subjects")
            reply = json.dumps(self.subjects)
        else:
            reply = "Done."
        return type("R", (), {"content": reply})()


# ---- the market list ------------------------------------------------------------------------------------------
def test_market_list_is_consistent():
    assert M.clashes() == []
    pts = M.points()
    ids = {p["id"] for p in pts}
    assert len(ids) == len(pts)                                                  # one point per distinct text
    assert not ids & {T.point_id(e["symbol"]) for e in M.entries()}              # never a company point (XLK is both)
    assert all(p["payload"]["asset_type"] in (M.MARKET, M.GROUP) for p in pts)
    assert all(e["news"] is None or isinstance(e["news"], str) for e in M.entries())


def test_lookup_exact_spelling_and_meaning():
    assert M.lookup("USD---JPY")["symbol"] == "JPY=X" and M.lookup("usd/jpy")["symbol"] == "JPY=X" and M.lookup("yen")["symbol"] == "JPY=X"
    assert M.lookup("dxy")["name"] == "US Dollar Index" and M.lookup("dxy")["news"] == ["DXY"]          # its symbol has no Yahoo news
    forex = M.lookup("forex")
    assert forex["kind"] == M.GROUP and forex["key"] == "group:forex" and len(forex["quotes"]) == M.GROUP_QUOTES
    assert M.lookup("etherium")["symbol"] == "ETH-USD"                                                # misspelt
    assert M.lookup("EURGBP")["news"] == [] and M.lookup("Shanghai Composite")["news"] == ["FXI"]     # no news / the ETF's
    M.set_market_searcher(lambda q, k: [{"symbol": "EURUSD=X", "group": "forex", "score": 0.92},
                                        {"symbol": "EURUSD=X", "group": "forex", "score": 0.90}])
    assert M.lookup("Europe vs USD")["symbol"] == "EURUSD=X"
    M.set_market_searcher(lambda q, k: [{"symbol": "EURUSD=X", "group": "forex", "score": 0.85},
                                        {"symbol": "DX-Y.NYB", "group": "forex", "score": 0.84}])
    assert M.lookup("dollar vs others") is None                                  # no clear winner: no guess
    M.set_market_searcher(lambda q, k: [{"symbol": "EURUSD=X", "group": "forex", "score": 0.7}])
    assert M.lookup("something vague") is None                                   # below min_score


def test_markets_found_in_text_without_an_llm():
    keys = lambda t: [s["key"] for s in M.in_text(t)]                            # noqa: E731
    assert keys("any news about forex?") == ["group:forex"]
    assert keys("how is gold doing today") == ["GC=F"] and keys("is BTC up?") == ["BTC-USD"]
    assert keys("crude oil and the S&P 500") == ["CL=F", "^GSPC"] and keys("oil stocks news") == ["XLE"]
    assert keys("a stellar quarter for Apple") == [] and keys("sugar stocks") == []            # everyday words
    assert keys("What about Sugar prices?") == ["SB=F"]


def test_story_tags_and_poll_terms():
    assert M.news_tags("JPY=X") == ["market:forex"] and M.news_tags("MARKET") == ["market:us_indices"] and M.news_tags("NVDA") == []
    assert M.search_tags(M.lookup("forex")) == ["market:forex"] and M.search_tags(M.lookup("ethereum")) == ["ETHEREUM"]
    assert M.news_term_for("DX-Y.NYB") == "DXY" and M.news_term_for("EURGBP=X") is None and M.news_term_for("AAPL") == "AAPL"


# ---- what the question is about -------------------------------------------------------------------------------
def test_an_empty_model_answer_is_final():
    llm_module.set_llm(SubjectLLM(["news"], {"companies": [], "markets": ["forex"], "topic": None, "excluded": []}))
    got = SYM.subjects("Any news about forex?")
    assert got["companies"] == [] and [m["key"] for m in got["markets"]] == ["group:forex"] and got["topic"] == ""
    # without the model, the phrasing cues would have made "forex" and "Any" companies; now "forex" is a market
    assert SYM.keyword_mentions("Any news about forex?") == ["forex", "Any"]


def test_market_names_that_are_never_companies_still_count_as_markets():
    llm_module.set_llm(SubjectLLM(["market"], {"companies": [], "markets": ["gold", "crypto"], "topic": None, "excluded": []}))
    assert [m["key"] for m in SYM.subjects("How are gold and crypto doing today?")["markets"]] == ["GC=F", "group:crypto"]


def test_a_market_given_as_a_company_moves_and_excluded_are_dropped():
    llm_module.set_llm(SubjectLLM(["news"], {"companies": ["gold", "DHSB"], "markets": [], "topic": "", "excluded": ["DHSB"]}))
    got = SYM.subjects("not DHSB, gold news")
    assert got["companies"] == [] and [m["key"] for m in got["markets"]] == ["GC=F"] and "dhsb" in got["excluded"]


def test_basic_mode_finds_markets_and_the_topic_is_left_to_the_words():
    got = SYM.subjects("any news about forex?")
    assert got["companies"] == [] and [m["key"] for m in got["markets"]] == ["group:forex"] and got["topic"] is None


# ---- the agents -----------------------------------------------------------------------------------------------
def test_forex_news_fetches_the_forex_feeds(db, monkeypatch):
    calls = fake_feed(monkeypatch, {"JPY=X": [story(1, "Yen retreats ahead of Fed")], "EURUSD=X": [story(2, "Euro steadies")],
                                    "CNY=X": [], "DXY": [story(3, "Dollar index holds")]})
    set_news_searcher(lambda *a: pytest.fail("no topic: the live feeds answer"))
    s = ask("any news about forex?", db)
    assert calls == ["JPY=X", "EURUSD=X", "CNY=X", "DXY"]
    assert "Yen retreats ahead of Fed" in s["final_response"] and "headlines for currencies" in s["final_response"]
    assert any(t.startswith("markets: currencies (all forex)") for t in s["trace"])
    assert not any("SHILY" in t or "ANY" in t for t in s["trace"])


def test_a_market_topic_searches_its_stories_by_tag_with_the_model_topic(db, monkeypatch):
    llm_module.set_llm(SubjectLLM(["news"], {"companies": [], "markets": ["forex"], "topic": "rate cuts", "excluded": []}))
    fake_feed(monkeypatch, {})
    searches = []

    def searcher(q, tags, days, k):
        searches.append((q, tags))
        return [{"score": 0.8, "story_id": "s1", "title": "Dollar falls on rate-cut bets", "summary": "", "publisher": "Wire",
                 "url": "https://x.test/1", "published": iso(hours=1), "ingested_at": time.time(), "tickers": ["market:forex"]}] * 1
    set_news_searcher(searcher)
    monkeypatch.setitem(__import__("src.core.config", fromlist=["get_config"]).get_config()["news_index"], "web_min_stories", 1)
    s = ask("forex news on rate cuts", db)
    assert searches[0] == ("rate cuts", ["market:forex"]) and "Dollar falls on rate-cut bets" in s["agent_outputs"]["news"]["content"]


def test_too_few_stories_adds_web_news_and_indexes_it(db, monkeypatch):
    fake_feed(monkeypatch, {})
    set_news_searcher(lambda *a: [])
    indexed = []
    set_news_indexer(lambda sym, items: indexed.append((sym, [i["url"] for i in items])) or len(items))
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    tavily.set_web_searcher(lambda q: [])                                         # Research's web search: nothing, no network
    asked = []

    def web(q, days):
        asked.append((q, days))
        return [{"title": "Gold slips as Fed looms", "url": "https://news.test/gold", "content": "Gold fell 1%.", "score": 0.8,
                 "published_date": "Mon, 26 Oct 2026 08:00:00 GMT"},
                {"title": "Undated", "url": "https://news.test/old", "content": "No date.", "score": 0.9}]
    tavily.set_web_news_searcher(web)
    s = ask("news about gold and central bank buying this week", db)
    assert asked and asked[0][1] == 7 and "Gold" in asked[0][0]
    assert "Gold slips as Fed looms" in s["final_response"] and "Undated" not in s["final_response"]
    assert indexed == [("GC=F", ["https://news.test/gold"])]
    assert s["agent_outputs"]["news"]["data_info"]["provider"] == "yfinance+tavily"


def test_market_agent_quotes_a_market(db, monkeypatch):
    calls = fake_feed(monkeypatch, {})
    s = ask("how is the yen doing today?", db)
    assert "quote:JPY=X" in calls and "1.1218" in s["final_response"] and "$1.12" not in s["final_response"]


def test_a_market_follow_up_keeps_the_market(db, monkeypatch):
    fake_feed(monkeypatch, {"GC=F": [story(1, "Gold steadies")]})
    first = ask("gold news", db)
    assert first["context"]["markets"] == [{"key": "GC=F", "name": "Gold"}]
    from src.workflow import context as CTX
    state = {"follow_up": True, "context_in": first["context"], "intent": ["news"], "question": "and the latest on it?"}
    from src.workflow.nodes import _with_carried_companies
    res = _with_carried_companies({"intent": ["news"], "entities": {"tickers": [], "indices": [], "companies": [], "markets": []},
                                   "trace": []}, state)
    assert [m["key"] for m in res["entities"]["markets"]] == ["GC=F"] and CTX.describe(first["context"]).count("Markets: Gold") == 1


# ---- Yahoo -----------------------------------------------------------------------------------------------------
def test_currency_quotes_keep_four_decimals(monkeypatch):
    class FI(dict):
        pass

    class Ticker:
        fast_info = FI(lastPrice=1.12184, previousClose=1.12013, lastVolume=0, dayHigh=1.1231, dayLow=1.1187)
        info = {"shortName": "EUR/USD"}
    monkeypatch.setattr(ms, "_yf_ticker", lambda s: Ticker())
    monkeypatch.setattr(ms, "_yf_name", lambda t, s: "EUR/USD")
    q = ms._yf_quote("EURUSD=X")
    assert q["price"] == 1.1218 and q["prev_close"] == 1.1201 and (q["day_low"], q["day_high"]) == (1.1187, 1.1231)


def test_web_news_dates():
    assert tavily._iso("Mon, 26 Oct 2026 08:00:00 GMT") == "2026-10-26T08:00:00Z"
    assert tavily._iso("2026-10-26T08:00:00+02:00") == "2026-10-26T06:00:00Z" and tavily._iso("soon") is None


# ---- the proofreader -----------------------------------------------------------------------------------------
def test_negation_rewrite_may_drop_only_what_was_ruled_out():
    o = "I am not looking for DHSB news. I just want earler news of today"
    assert _proofread_ok(o, "What were the market headlines earlier today?")
    assert not _proofread_ok(o, "What were the DHSB headlines earlier today?")       # ruled out, yet back
    assert not _proofread_ok(o, "What is the latest on Tesla?")                       # a company the user never named
    assert not _proofread_ok("news on NVDA today", "What is the market news today?")  # NVDA wasn't ruled out


def test_negated_question_ends_with_market_headlines(db, monkeypatch):
    llm_module.set_llm(SubjectLLM(["news"], {"companies": [], "markets": [], "topic": None, "excluded": []},
                                  proofread="What were the market headlines earlier today?"))
    calls = fake_feed(monkeypatch, {"MARKET": [story(1, "Stocks rally")]})
    s = ask("I am not looking for DHSB news. I just want earler news of today", db)
    assert calls == ["MARKET"] and "Stocks rally" in s["agent_outputs"]["news"]["content"]
    assert "dhsb" in s["entities"]["excluded"] and s["question"] == "What were the market headlines earlier today?"
