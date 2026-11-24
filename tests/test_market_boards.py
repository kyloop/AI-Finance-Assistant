"""Yahoo's sector, industry, screen and market-hours data (market_service), the Live Market tab's boards (market_boards), their API
endpoints, the market agent's tools over them, and sector news (the API's merged feed and the news agent's sector companies).

A fake Yahoo provider serves the four new endpoints; prices and history come from the sample data, with the sector funds, two
industry indices and the region indices added (the bundled data has none of them)."""
from datetime import date

import pytest
from sqlalchemy.orm import sessionmaker

from src.core import llm as llm_module
from src.core import market_boards as B
from src.core import market_service as ms
from src.rag import markets as MK
from src.workflow import market_tools as MT
from src.workflow.graph import run_chat

TECH = {"key": "technology", "name": "Technology", "symbol": "^YH311",
        "overview": {"companies_count": 867, "market_cap": 2.9e13, "market_weight": 0.328, "industries_count": 2, "description": "Tech."},
        "top_companies": [{"symbol": "NVDA", "name": "NVIDIA Corporation", "rating": "Strong Buy", "weight": 0.17},
                          {"symbol": "AAPL", "name": "Apple Inc.", "rating": "Buy", "weight": 0.16},
                          {"symbol": "MSFT", "name": "Microsoft Corporation", "rating": None, "weight": 0.13},
                          {"symbol": "AVGO", "name": "Broadcom Inc.", "rating": "Strong Buy", "weight": 0.05}],
        "industries": [{"key": "semiconductors", "name": "Semiconductors", "symbol": "^YH31130020", "weight": 0.37},
                       {"key": "software-infrastructure", "name": "Software - Infrastructure", "symbol": "^YH31110030", "weight": 0.22}],
        "top_etfs": [{"symbol": "QQQ", "name": "Invesco QQQ Trust"}, {"symbol": "XLK", "name": "Technology Select Sector SPDR"}]}
SEMIS = {"key": "semiconductors", "name": "Semiconductors", "symbol": "^YH31130020", "sector_key": "technology", "sector_name": "Technology",
         "overview": {"companies_count": 59, "market_cap": 1.07e13, "market_weight": 0.37, "industries_count": None, "description": ""},
         "top_companies": [{"symbol": "NVDA", "name": "NVIDIA Corporation", "rating": "Strong Buy", "weight": 0.44}],
         "top_performing": [{"symbol": "MU", "name": "Micron Technology, Inc.", "ytd_return": 2.27, "last_price": 934.27, "target_price": 1561.9}],
         "top_growth": [{"symbol": "MU", "name": "Micron Technology, Inc.", "ytd_return": 2.27, "growth_estimate": 5.85}]}
QUOTE_ROW = {"price": 10.0, "change_pct": 0.012, "volume": 1e6, "market_cap": 1e12, "exchange": "NasdaqGS", "quote_type": "EQUITY"}
SCREENS = {"largest_us": {"name": "largest_us", "title": "Largest US-listed companies by market value", "total": 5000,
                          "quotes": [{"symbol": s, "name": n, **QUOTE_ROW, "market_cap": c}
                                     for s, n, c in [("NVDA", "NVIDIA Corporation", 5.2e12), ("AAPL", "Apple Inc.", 5.1e12), ("MSFT", "Microsoft Corporation", 3.9e12)]]},
           "most_actives": {"name": "most_actives", "title": "Most active stocks today", "total": 368,
                            "quotes": [{"symbol": "ADT", "name": "ADT Inc.", **QUOTE_ROW, "change_pct": 0.332, "volume": 1.64e8},
                                       {"symbol": "NOK", "name": "Nokia Oyj", **QUOTE_ROW, "change_pct": -0.01, "volume": 9.0e7}]}}
STATUS = {"region": "US", "name": "U.S. markets", "status": "closed", "message": "U.S. markets closed",
          "open": "2026-10-29 13:30:00+00:00", "close": "2026-10-29 20:00:00+00:00", "timezone": "EDT"}


@pytest.fixture
def db():
    from src.db.base import Base
    from src.db.session import make_engine
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


@pytest.fixture
def instruments(monkeypatch):
    """Sector funds, two industry indices and the region indices as sample instruments."""
    extra = {s["symbol"]: ("stock_etf", s["name"]) for s in MK.sectors()}
    extra |= {"^YH31130020": ("index", "Semiconductors"), "^YH31110030": ("index", "Software - Infrastructure")}
    extra |= {r["symbol"]: ("index", r["name"]) for r in MK.regions()}
    for i, (sym, (kind, name)) in enumerate(extra.items()):
        if sym not in ms.INSTRUMENTS:
            monkeypatch.setitem(ms.INSTRUMENTS, sym, {"name": name, "price": 100.0 + 7 * i, "asset_type": kind})


@pytest.fixture
def yahoo(monkeypatch, instruments):
    """A Yahoo provider for sector, industry, screen, market_status and news; quotes and history fall through to sample data."""
    calls = []

    def sector(key, **_):
        calls.append(("sector", key))
        if key.lower() != "technology":
            raise ms.SymbolNotFound(key)
        return TECH

    def industry(key, **_):
        calls.append(("industry", key))
        if key.lower() != "semiconductors":
            raise ms.SymbolNotFound(key)
        return SEMIS

    def screen(name, count=20, **_):
        calls.append(("screen", name.lower(), count))
        return {**SCREENS[name.lower()], "quotes": SCREENS[name.lower()]["quotes"][:count]}

    def news(symbol, **_):
        calls.append(("news", symbol))
        return {"symbol": symbol, "items": [{"id": f"{symbol}-1", "title": f"{symbol} story", "summary": "", "publisher": "Wire",
                                             "url": f"https://x.test/{symbol}", "published": f"2026-10-2{len(symbol)}T10:00:00Z", "thumbnail": None},
                                            {"id": "same", "title": "Chip stocks rally", "summary": "", "publisher": "Wire",
                                             "url": "https://x.test/same", "published": "2026-10-20T10:00:00Z", "thumbnail": None}]}

    fake = {"sector": sector, "industry": industry, "screen": screen, "market_status": lambda region, **_: STATUS, "news": news}
    monkeypatch.setattr(ms, "PROVIDERS", {"yahoo": fake, "sample": ms.PROVIDERS["sample"]})
    return calls


# ---------------------------------------------------------------- Yahoo payloads (market_service)
def test_yf_screen_keeps_one_line_per_company_and_reads_change_as_a_fraction(monkeypatch):
    import yfinance as yf
    raw = {"total": 9, "quotes": [{"symbol": "GOOGL", "longName": "Alphabet Inc.", "regularMarketPrice": 180.0, "regularMarketChangePercent": -12.64,
                                   "marketCap": 3.47e12, "regularMarketVolume": 5e7, "fullExchangeName": "NasdaqGS", "quoteType": "EQUITY"},
                                  {"symbol": "GOOG", "longName": "Alphabet Inc.", "regularMarketChangePercent": -12.29, "marketCap": 3.45e12},
                                  {"symbol": "AMZN", "shortName": "Amazon.com, Inc. ", "regularMarketChangePercent": 1.5, "marketCap": 2.6e12}]}
    asked = []
    monkeypatch.setattr(yf, "screen", lambda q, **kw: asked.append((q, kw)) or raw)
    out = ms._yf_screen("LARGEST_US", count=2)
    assert [r["symbol"] for r in out["quotes"]] == ["GOOGL", "AMZN"] and out["quotes"][0]["change_pct"] == -0.1264
    assert out["quotes"][1]["name"] == "Amazon.com, Inc." and asked[0][1]["sortField"] == "intradaymarketcap"
    assert ms._yf_screen("most_actives", count=99)["title"] == "Most active stocks today" and asked[-1] == ("most_actives", {"count": ms.SCREEN_MAX})
    with pytest.raises(ms.SymbolNotFound):
        ms._yf_screen("undervalued_large_caps")                       # only the screens offered


def test_the_new_endpoints_have_no_sample_data(db):
    for endpoint, key in [("sector", "technology"), ("industry", "semiconductors"), ("screen", "most_actives"), ("market_status", "US")]:
        with pytest.raises(ms.SymbolNotFound):
            ms.get_market_data(db, endpoint, key)


# ---------------------------------------------------------------- boards (market_boards)
def test_range_start():
    today = date(2026, 10, 29)
    assert B.range_start("1D", today) is None and B.range_start("YTD", today) == date(2026, 1, 1)
    assert B.range_start("1M", today) == date(2026, 9, 29) and B.range_start("1Y", today) == date(2025, 10, 29)
    with pytest.raises(B.UnknownRange):
        B.range_start("6M", today)


def test_sector_board_ranks_the_eleven_sector_funds(db, instruments):
    b = B.sector_board(db, "3M")
    returns = [i["return"] for i in b["items"]]
    assert len(b["items"]) == 11 and returns == sorted(returns, reverse=True) and b["missing"] == []
    xlk = next(i for i in b["items"] if i["symbol"] == "XLK")
    assert xlk["name"] == "Technology" and xlk["key"] == "technology" and b["label"] == "last 3 months"
    assert b["freshness"] == "sample" and b["provider"] == "sample" and b["start_date"] < b["end_date"]
    today = B.sector_board(db, "1D")                                            # today's change against the previous close
    assert today["start_date"] is None and xlk["return"] != next(i for i in today["items"] if i["symbol"] == "XLK")["return"]


def test_industry_board_measures_a_sectors_industries_by_their_indices(db, yahoo):
    b = B.industry_board(db, "XLK", "1M")
    assert b["sector"] == {"symbol": "XLK", "name": "Technology sector"}
    assert {i["symbol"] for i in b["items"]} == {"^YH31130020", "^YH31110030"}
    assert next(i for i in b["items"] if i["key"] == "semiconductors")["weight"] == 0.37 and ("sector", "TECHNOLOGY") in yahoo
    assert B.industry_board(db, "technology", "1M")["items"] == b["items"]           # the Yahoo key works too
    with pytest.raises(ms.SymbolNotFound):
        B.industry_board(db, "AAPL", "1M")


def test_largest_board_keeps_market_value_order(db, yahoo):
    b = B.largest_board(db, "YTD")
    assert [i["symbol"] for i in b["items"]] == ["NVDA", "AAPL", "MSFT"] and b["items"][0]["market_cap"] == 5.2e12
    assert ("screen", "largest_us", 10) in yahoo


def test_region_board_lists_each_regions_main_index(db, instruments):
    b = B.region_board(db, "1M")
    regions = {i["region"]: i["name"] for i in b["items"]}
    assert regions["Japan"] == "Nikkei 225" and regions["United States"] == "S&P 500" and regions["Eurozone"] == "Euro Stoxx 50"
    assert len(b["items"]) == len(MK.regions())


def test_most_active_is_todays_list(db, yahoo):
    b = B.most_active(db)
    assert [i["symbol"] for i in b["items"]] == ["ADT", "NOK"] and b["items"][0]["volume"] == 1.64e8 and b["range"] == "1D"


def test_sector_news_merges_the_fund_and_its_largest_companies(db, yahoo):
    env = B.sector_news(db, "XLK")
    d = env["data"]
    assert d["feeds"] == ["XLK", "NVDA", "AAPL", "MSFT"] and d["sector"] == "Technology"
    titles = [i["title"] for i in d["items"]]
    assert titles.count("Chip stocks rally") == 1 and titles[0] == "NVDA story"                 # no repeats; newest first
    with pytest.raises(ms.SymbolNotFound):
        B.sector_news(db, "gold")


# ---------------------------------------------------------------- API
def test_board_endpoints(client, yahoo):
    r = client.get("/api/market/boards/sectors?range=YTD")
    assert r.status_code == 200 and len(r.json()["items"]) == 11 and r.json()["label"] == "year to date"
    assert client.get("/api/market/boards/industries?sector=XLK&range=1D").json()["sector"]["symbol"] == "XLK"
    assert [i["symbol"] for i in client.get("/api/market/boards/largest").json()["items"]] == ["NVDA", "AAPL", "MSFT"]
    assert client.get("/api/market/boards/regions?range=1Y").status_code == 200
    assert client.get("/api/market/boards/most-active").json()["items"][0]["symbol"] == "ADT"
    assert client.get("/api/market/boards/sectors?range=6M").status_code == 422
    assert client.get("/api/market/news?sector=XLK").json()["data"]["feeds"][0] == "XLK"
    assert client.get("/api/market/news?sector=gold").status_code == 404


def test_board_endpoints_without_yahoo_say_so(client):
    r = client.get("/api/market/boards/most-active")
    assert r.status_code == 503 and "Yahoo Finance" in r.json()["detail"]
    assert client.get("/api/market/boards/sectors").status_code == 200                       # sector funds: sample data works offline
    assert client.get("/api/market/news?sector=XLK").json()["data"]["feeds"] == ["XLK"]     # offline: the fund's feed alone


# ---------------------------------------------------------------- market agent tools
def test_sector_profile_and_industry_tools(db, yahoo):
    p = MT.get_sector_profile(db, "tech stocks")["SECTOR:XLK"]["sector_profile"]
    assert p["market_weight"] == 0.328 and [i["name"] for i in p["industries"]] == ["Semiconductors", "Software - Infrastructure"]
    i = MT.get_industry(db, "Semiconductors")["INDUSTRY:semiconductors"]["industry"]
    assert i["sector"] == "Technology" and i["top_performing"][0]["symbol"] == "MU"
    assert "no industry called 'chips'" in MT.get_industry(db, "chips")["INDUSTRY:chips"]["error"]["message"]
    text = "\n".join(MT.describe_lines({**MT.get_sector_profile(db, "XLK"), **MT.get_industry(db, "semiconductors")}))
    assert "- **Technology sector** (fund XLK): 867 companies worth $29.0T, 32.8% of the US stock market." in text
    assert "NVIDIA Corporation (NVDA, 17.0%, analysts: Strong Buy)" in text and "Microsoft Corporation (MSFT, 13.0%)" in text
    assert "Best performing this year: Micron Technology, Inc. (MU) +227.0%" in text


def test_board_tools(db, yahoo):
    data = {**MT.get_industry_performance(db, "XLK", "1M"), **MT.get_largest_companies(db, "YTD"),
            **MT.get_region_performance(db, "1D"), **MT.get_most_active(db), **MT.get_market_status(db)}
    assert data["INDUSTRIES:XLK"]["board"]["kind"] == "industries" and data["LARGEST"]["board"]["label"] == "year to date"
    text = "\n".join(MT.describe_lines(data))
    assert "- **Industries in the technology sector**, last month" in text and "of the sector)" in text
    assert "- **Largest US-listed companies**, year to date" in text and "NVIDIA Corporation (NVDA, $5.2T)" in text
    assert "- **Stock markets by region**, today (best to worst, in local currency): " in text and "Japan (Nikkei 225)" in text
    assert "ADT Inc. (ADT): 164.0M shares, +33.2%" in text and "U.S. markets closed. Regular hours today: 13:30–20:00 UTC." in text
    assert "INDUSTRIES:XLK board: **Industries in the technology sector**" in MT.data_block(data)
    with pytest.raises(MT.ToolError):
        MT.get_largest_companies(db, "6 months")                                   # the boards' ranges only


def test_the_tools_say_when_yahoo_is_needed(db, instruments):
    for out in (MT.get_sector_profile(db, "XLK"), MT.get_largest_companies(db), MT.get_most_active(db), MT.get_market_status(db)):
        (key, d), = out.items()
        assert d["error"]["message"] == MT.LIVE_ONLY
    assert "_Largest: this needs live data from Yahoo Finance" in "\n".join(MT.describe_lines(MT.get_largest_companies(db)))


def test_subject_keys_never_become_companies_in_the_saved_context(db, yahoo):
    from tests.test_market_tools import ToolLLM
    llm_module.set_llm(ToolLLM([("get_largest_companies", {"period": "1M"}), ("get_market_status", {})]))
    s = run_chat("What are the biggest companies and is the market open?", history=[], profile={"knowledge_level": "beginner"}, holdings=[], db=db)
    assert {"LARGEST", "MARKET_STATUS"} <= set(s["market_data"]) and s["context"]["companies"] == []


def test_sector_news_in_chat_adds_the_sectors_largest_companies(db, yahoo):
    llm_module.set_llm(None)
    s = run_chat("tech stocks news", history=[], profile={"knowledge_level": "beginner"}, holdings=[], db=db)
    assert "sector_companies(XLK) → NVDA, AAPL, MSFT" in " ".join(s["trace"])
    assert {("news", "XLK"), ("news", "NVDA")} <= set(yahoo)


@pytest.mark.parametrize("q,tool", [("what are the most active stocks today?", "get_most_active"),
                                    ("show me the biggest companies", "get_largest_companies"),
                                    ("is the stock market open?", "get_market_status")])
def test_market_wide_questions_work_without_an_llm(db, yahoo, q, tool):
    llm_module.set_llm(None)
    s = run_chat(q, history=[], profile={"knowledge_level": "beginner"}, holdings=[], db=db)
    trace = next(t for t in s["trace"] if t.startswith("market (keywords): "))
    assert "market" in s["intent"] and f"{tool}() → " in trace              # "is the stock market open?" also quotes the indices
    assert s["agent_outputs"]["market"]["status"] == "answered" and s["context"]["companies"] == []


# ---------------------------------------------------------------- poller (keeps the boards' data in the cache)

@pytest.fixture
def sessions():
    """A session factory over one in-memory database, as the poller opens its own sessions."""
    from sqlalchemy.pool import StaticPool
    from src.db.base import Base
    from sqlalchemy import create_engine
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_poll_fetches_every_boards_data_then_charts_read_the_cache(sessions, yahoo):
    n = B.refresh_once(sessions)
    assert ("screen", "most_actives", B.ACTIVE_COUNT) in yahoo and ("screen", "largest_us", B.LARGEST_COUNT) in yahoo
    assert ("sector", "TECHNOLOGY") in yahoo                       # industries asked for every sector
    assert n >= len(MK.sectors()) + len(MK.regions())
    yahoo.clear()
    with sessions() as db:
        B.largest_board(db, "1M"), B.industry_board(db, "XLK", "1M")
    assert yahoo == []                                             # served from what the poll saved


def test_poll_without_industries_and_offline_never_raises(sessions, yahoo, monkeypatch):
    B.refresh_once(sessions, industries=False)
    assert not any(c[0] == "sector" for c in yahoo)
    monkeypatch.setattr(ms, "PROVIDERS", {"sample": ms.PROVIDERS["sample"]})
    B.refresh_once(sessions)                                       # no Yahoo: screens and sectors fail quietly


def test_a_range_ends_at_the_live_price(db, instruments, monkeypatch):
    live = {"quote": lambda symbol, **_: {"symbol": symbol, "price": 200.0, "prev_close": 190.0, "change": 10.0, "change_pct": 0.0526}}
    monkeypatch.setattr(ms, "PROVIDERS", {"yahoo": live, "sample": ms.PROVIDERS["sample"]})
    c = B._change(db, "XLK", B.range_start("1M"))
    first = next(p for p in ms._sample_history("XLK", days=B.HISTORY_DAYS)["points"] if p["date"] >= B.range_start("1M").isoformat())
    assert c["return"] == round(200.0 / first["close"] - 1, 4) and c["provider"] == "yahoo" and c["freshness"] == "live"
