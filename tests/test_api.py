import pytest


def test_profile_roundtrip(client, sid):
    assert client.get(f"/api/sessions/{sid}/profile").json()["knowledge_level"] == "beginner"
    r = client.put(f"/api/sessions/{sid}/profile", json={"knowledge_level": "advanced", "risk_tolerance": "aggressive", "horizon_years": 20, "goals": ["retire"]})
    assert r.json()["risk_tolerance"] == "aggressive"


def test_unknown_session_404(client):
    assert client.get("/api/sessions/nope/profile").status_code == 404


def test_chat_persists_routes_and_adds_disclaimer(client, sid):
    r = client.post(f"/api/sessions/{sid}/chat", json={"message": "Is my portfolio too tech-heavy? What is the S&P 500 doing?"}).json()
    assert {"Portfolio Analysis", "Market Analysis"} <= set(r["agents"])
    assert "not financial advice" in r["content"]
    assert len(client.get(f"/api/sessions/{sid}/messages").json()) == 2
    client.delete(f"/api/sessions/{sid}/messages")
    assert client.get(f"/api/sessions/{sid}/messages").json() == []


def test_chat_empty_message_is_graceful(client, sid):
    r = client.post(f"/api/sessions/{sid}/chat", json={"message": "   "})
    assert r.status_code == 200 and r.json()["agents"] == []


def test_portfolio_validation_and_analysis(client, sid):
    assert client.put(f"/api/sessions/{sid}/portfolio", json={"holdings": [{"ticker": "VTI", "shares": 0}]}).status_code == 422
    client.put(f"/api/sessions/{sid}/portfolio", json={"holdings": [{"ticker": "vti", "shares": 10}, {"ticker": "BND", "shares": 20}]})
    a = client.get(f"/api/sessions/{sid}/portfolio/analysis").json()
    price = lambda sym: client.get(f"/api/market/quote/{sym}").json()["data"]["price"]     # the quote the analysis just cached  # noqa: E731
    assert a["total_value"] == pytest.approx(10 * price("VTI") + 20 * price("BND"), abs=0.01)
    assert a["data_info"]["freshness"] == "sample"


def test_portfolio_report_has_performance_cash_and_skips_unknown(client, sid):
    client.put(f"/api/sessions/{sid}/portfolio", json={"holdings": [
        {"ticker": "VTI", "shares": 10, "cost_basis": 240, "purchase_date": "2020-05-01"}, {"ticker": "BND", "shares": 20},
        {"ticker": "CASH", "shares": 1000}, {"ticker": "ZZZZ", "shares": 5}]})
    saved = client.get(f"/api/sessions/{sid}/portfolio").json()
    assert [h["purchase_date"] for h in saved["holdings"]] == ["2020-05-01", None, None, None]
    assert saved["default_purchase_date"] == "2026-01-01"            # what the purchase-date field shows when left empty
    a = client.get(f"/api/sessions/{sid}/portfolio/analysis").json()
    assert a["skipped"] == ["ZZZZ"]
    cash = next(h for h in a["holdings"] if h["ticker"] == "CASH")
    assert cash["value"] == 1000 and cash["asset_class"] == "Cash" and cash["day_change"] == 0
    assert {g["name"] for g in a["geography"]} == {"US stocks", "Bonds", "Cash"}
    assert a["day_change"] is not None and a["total_return_pct"] == pytest.approx(a["total_gain_loss"] / 2400)
    p = a["performance"]
    assert p["days"] == len(p["points"]) >= 250 and p["excluded"] == [] and p["pending"] == []
    assert p["default_start"] == "2026-01-01" and p["assumed"] == ["BND", "CASH"] and p["start"] == "2020-05-01"
    assert p["benchmark"] == {"symbol": "^GSPC", "name": "S&P 500"} and p["points"][0]["benchmark"] == p["points"][0]["value"]
    assert all(p[k] is not None for k in ("period_return", "annualized_return", "volatility", "sharpe", "sortino", "benchmark_return"))
    assert p["max_drawdown"] <= 0
    assert a["dividends"] == {"total": 0, "yield": 0, "by_month": [], "by_holding": []}      # the sample data has no dividend history


def test_market_quote_cache_and_unknown(client):
    first = client.get("/api/market/quote/AAPL").json()
    second = client.get("/api/market/quote/AAPL").json()
    assert first["freshness"] == second["freshness"] == "sample" and first["fetched_at"] == second["fetched_at"]
    assert client.get("/api/market/quote/ZZZZ").status_code == 404
    assert len(client.get("/api/market/indices").json()) == 3
    assert client.get("/api/market/history/AAPL").json()["data"]["points"][-1]["ma200"] is not None


def test_goal_projection_saved(client, sid):
    body = {"goal_type": "retirement", "target_amount": 500000, "horizon_years": 30, "current_savings": 10000, "monthly_contribution": 500, "risk_tolerance": "moderate"}
    r = client.post(f"/api/sessions/{sid}/goals/project", json=body).json()
    assert r["suggested_allocation"]["stocks"] == 60
    assert len(client.get(f"/api/sessions/{sid}/goals").json()) == 1
    assert client.post(f"/api/sessions/{sid}/goals/project", json=body | {"horizon_years": 0}).status_code == 422


def test_live_endpoints(client):
    q = client.get("/api/market/quotes?symbols=aapl,MSFT,ZZZZ,aapl").json()
    assert [i["data"]["symbol"] for i in q["items"]] == ["AAPL", "MSFT"] and q["errors"] == ["ZZZZ"]
    item = q["items"][0]
    assert len(item["spark"]) >= 20 and item["spark"][-1] == item["data"]["price"]
    assert item["data"]["day_low"] <= item["data"]["price"] <= item["data"]["day_high"]
    intra = client.get("/api/market/intraday/AAPL").json()["data"]
    assert intra["points"][-1]["close"] > 0 and intra["prev_close"] == 228.5
    assert client.get("/api/market/intraday/ZZZZ").status_code == 404
    assert "AAPL" in [s["symbol"] for s in client.get("/api/market/symbols").json()]
    assert "volume" in client.get("/api/market/history/AAPL").json()["data"]["points"][0]


def test_new_chat_and_history_resume(client, sid):
    base = f"/api/sessions/{sid}"
    first = client.post(f"{base}/conversations").json()
    client.post(f"{base}/chat", json={"message": "What is an ETF?", "conversation_id": first["id"]})
    second = client.post(f"{base}/conversations").json()
    assert second["id"] != first["id"]
    assert client.post(f"{base}/conversations").json()["id"] == second["id"]      # empty thread is reused
    client.post(f"{base}/chat", json={"message": "What is a bond?", "conversation_id": second["id"]})

    history = client.get(f"{base}/conversations").json()
    assert [c["title"] for c in history] == ["What is a bond?", "What is an ETF?"]
    msgs = client.get(f"{base}/messages", params={"conversation_id": first["id"]}).json()
    assert len(msgs) == 2 and msgs[0]["content"] == "What is an ETF?"

    client.post(f"{base}/chat", json={"message": "And a stock?", "conversation_id": first["id"]})      # resume old thread
    assert len(client.get(f"{base}/messages", params={"conversation_id": first["id"]}).json()) == 4
    assert client.delete(f"{base}/conversations/{first['id']}").status_code == 204
    assert client.get(f"{base}/messages", params={"conversation_id": first["id"]}).status_code == 404


def test_title_is_renamed_from_the_conversation_after_three_rounds(client, sid, monkeypatch):
    from src.api.routers import chat as chat_router
    prompts = []
    monkeypatch.setattr(chat_router, "ask_llm", lambda system, user: prompts.append(user) or '"ETFs, bonds and stocks."')
    base = f"/api/sessions/{sid}"
    cid = client.post(f"{base}/conversations").json()["id"]
    title = lambda: next(c["title"] for c in client.get(f"{base}/conversations").json() if c["id"] == cid)  # noqa: E731
    for q in ("What is an ETF?", "What is a bond?"):
        client.post(f"{base}/chat", json={"message": q, "conversation_id": cid})
    assert title() == "What is an ETF?" and prompts == []                       # first two rounds keep the first question
    client.post(f"{base}/chat", json={"message": "And a stock?", "conversation_id": cid})
    assert title() == "ETFs, bonds and stocks" and "user: And a stock?" in prompts[0]
    client.post(f"{base}/chat", json={"message": "Thanks", "conversation_id": cid})
    assert len(prompts) == 1                                                    # renamed once only


def test_title_stays_without_an_llm(client, sid):
    base = f"/api/sessions/{sid}"
    for q in ("What is an ETF?", "What is a bond?", "And a stock?"):
        client.post(f"{base}/chat", json={"message": q})
    assert client.get(f"{base}/conversations").json()[0]["title"] == "What is an ETF?"


def test_market_cache_survives_a_concurrent_writer(tmp_path, monkeypatch):
    """Two requests fetching the same symbol at once (parallel agents, the Live tab, the news poll) must not crash on the duplicate
    cache row: the loser uses what the winner stored."""
    from sqlalchemy.orm import sessionmaker

    from src.core import market_service as ms
    from src.db.base import Base
    from src.db.models import MarketCache
    from src.db.session import make_engine
    engine = make_engine(f"sqlite:///{tmp_path / 'race.db'}")
    Base.metadata.create_all(engine)
    Local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def slow_quote(symbol, **_):                    # while we "fetch", another session stores the same cache row
        with Local() as other:
            now = ms._now()
            key = next(k for k in [__import__("hashlib").sha1(f"fake|{symbol}|quote|{{}}".encode()).hexdigest()])
            other.add(MarketCache(key=key, provider="fake", symbol=symbol, endpoint="quote", payload={"price": 1.0},
                                  fetched_at=now, expires_at=now + ms.timedelta(seconds=60)))
            other.commit()
        return {"price": 2.0}
    monkeypatch.setattr(ms, "PROVIDERS", {"fake": {"quote": slow_quote}})
    with Local() as db:
        env = ms.get_market_data(db, "quote", "ZZ")
    assert env["data"] == {"price": 1.0} and env["freshness"] == "cached"
