import asyncio

import pytest

from src.core.live_stream import LiveHub, normalize_symbol, normalize_tick


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeSocket:
    """Stands in for yfinance.AsyncWebSocket: records subscriptions, emits scripted messages from listen()."""
    instances: list = []

    def __init__(self):
        self.subs: set = set()
        self.inbox: asyncio.Queue = asyncio.Queue()
        FakeSocket.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def subscribe(self, symbols):
        self.subs |= set(symbols)

    async def unsubscribe(self, symbols):
        self.subs -= set(symbols)

    async def listen(self, handler):
        while True:
            msg = await self.inbox.get()
            if msg is None:
                raise ConnectionError("dropped")
            handler(msg)


def tick(sym, price, **kw):
    return {"id": sym, "price": price, "time": "1790866662000", **kw}


@pytest.fixture
def hub():
    FakeSocket.instances = []
    return LiveHub(FakeSocket)


def test_normalize_tick_units_and_partials():
    t = normalize_tick(tick("AAPL", 330.1, change=-2.9, change_percent=-0.88, day_volume="8727420", market_hours=1))
    assert t["symbol"] == "AAPL" and t["change_pct"] == pytest.approx(-0.0088) and t["volume"] == 8727420
    assert t["ts"].startswith("2026-10-01")
    assert normalize_tick({"id": "AAPL"}) is None


def test_normalize_symbol():
    assert normalize_symbol(" aapl ") == "AAPL" and normalize_symbol("^GSPC") == "^GSPC" and normalize_symbol("BTC-USD") == "BTC-USD"
    assert normalize_symbol("a b") is None and normalize_symbol("") is None and normalize_symbol("x" * 30) is None


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.anyio
async def test_fanout_refcount_and_merge(hub):
    a, b = hub.register(), hub.register()
    await hub.subscribe(a, ["AAPL", "MSFT"])
    await hub.subscribe(b, ["AAPL"])
    await _settle()
    sock = FakeSocket.instances[0]
    assert sock.subs == {"AAPL", "MSFT"} and hub.state == "connected"

    sock.inbox.put_nowait(tick("AAPL", 330.0, change=-2.9, change_percent=-0.88))
    sock.inbox.put_nowait(tick("AAPL", 330.1))              # partial update keeps change fields from the previous tick
    sock.inbox.put_nowait(tick("TSLA", 1.0))                # nobody subscribed -> ignored
    await _settle()
    got_a = [a.get_nowait() for _ in range(a.qsize())]
    ticks_a = [m for m in got_a if m["type"] == "tick"]
    assert [t["price"] for t in ticks_a] == [330.0, 330.1] and ticks_a[1]["change"] == -2.9
    assert sum(m["type"] == "tick" for m in [b.get_nowait() for _ in range(b.qsize())]) == 2

    await hub.unsubscribe(a, ["AAPL"])                      # b still holds AAPL -> stays upstream
    assert "AAPL" in sock.subs
    await hub.unsubscribe(b, ["AAPL"])
    assert "AAPL" not in sock.subs
    await hub.unregister(a)
    await hub.unregister(b)
    assert hub.state == "idle" and not hub._refs


@pytest.mark.anyio
async def test_late_subscriber_gets_last_tick(hub):
    a = hub.register()
    await hub.subscribe(a, ["AAPL"])
    await _settle()
    FakeSocket.instances[0].inbox.put_nowait(tick("AAPL", 330.0))
    await _settle()
    b = hub.register()
    await hub.subscribe(b, ["AAPL"])
    assert b.get_nowait()["price"] == 330.0
    await hub.stop()


@pytest.mark.anyio
async def test_reconnects_and_resubscribes(hub, monkeypatch):
    monkeypatch.setattr("src.core.live_stream.BACKOFF_START", 0.01)
    a = hub.register()
    await hub.subscribe(a, ["AAPL"])
    await _settle()
    FakeSocket.instances[0].inbox.put_nowait(None)          # upstream drops
    await asyncio.sleep(0.1)
    assert len(FakeSocket.instances) == 2 and FakeSocket.instances[1].subs == {"AAPL"} and hub.state == "connected"
    await hub.stop()


@pytest.mark.anyio
async def test_slow_client_drops_oldest(hub, monkeypatch):
    monkeypatch.setattr("src.core.live_stream.CLIENT_QUEUE_SIZE", 3)
    a = hub.register()
    await hub.subscribe(a, ["AAPL"])
    await _settle()
    for p in range(10):
        FakeSocket.instances[0].inbox.put_nowait(tick("AAPL", float(p)))
    await _settle()
    prices = [m["price"] for m in [a.get_nowait() for _ in range(a.qsize())] if m["type"] == "tick"]
    assert prices[-1] == 9.0 and len(prices) <= 3
    await hub.stop()


def test_ws_endpoint_validation_and_cap(client, monkeypatch):
    from src.core import live_stream
    monkeypatch.setattr(live_stream, "hub", LiveHub(FakeSocket))
    import src.api.routers.stream as r
    monkeypatch.setattr(r, "hub", live_stream.hub)
    with client.websocket_connect("/api/market/stream") as ws:
        assert ws.receive_json()["type"] == "status"
        ws.send_text("garbage")
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"action": "subscribe", "symbols": ["aapl", "bad sym", "MSFT"]})
        m = ws.receive_json()
        while m["type"] != "subscribed":                     # status frames may interleave
            m = ws.receive_json()
        assert m["symbols"] == ["AAPL", "MSFT"] and m["rejected"] == ["bad sym"]


def test_yfinance_provider_shapes_and_fallback(client, monkeypatch):
    """The yfinance provider (faked) returns history with moving averages; an empty result falls back to sample data."""
    import pandas as pd
    from src.core import market_service as ms

    idx = pd.date_range("2025-01-01", periods=300, freq="B", tz="America/New_York")
    df = pd.DataFrame({"Close": range(100, 400), "Volume": 1000}, index=idx)

    class FakeTicker:
        def __init__(self, empty): self.empty = empty
        def history(self, **_): return df.iloc[0:0] if self.empty else df

    monkeypatch.setattr(ms, "PROVIDERS", {"yfinance": {"history": ms._yf_history}, "sample": ms.PROVIDERS["sample"]})
    monkeypatch.setattr(ms, "_yf_ticker", lambda s: FakeTicker(empty=False))
    r = client.get("/api/market/history/AAPL").json()
    pts = r["data"]["points"]
    assert r["provider"] == "yfinance" and r["freshness"] == "live" and len(pts) == 250
    assert pts[-1]["close"] == 399 and pts[-1]["ma200"] is not None and pts[0]["ma50"] is not None

    monkeypatch.setattr(ms, "_yf_ticker", lambda s: FakeTicker(empty=True))
    r = client.get("/api/market/history/MSFT?refresh=true").json()
    assert r["provider"] == "sample" and r["freshness"] == "sample"          # provider empty/down -> flagged sample fallback
    assert client.get("/api/market/history/ZZZZ").status_code == 404           # unknown everywhere -> 404


def test_news_stock_and_market_merge_dedupe_and_fallback(client, monkeypatch):
    """Stock news is normalised; market news merges the index feeds, dedupes by id, sorts newest first; empty -> sample (no stories)."""
    from src.core import market_service as ms

    def story(id_, title, when):
        return {"id": id_, "content": {"title": title, "pubDate": when, "provider": {"displayName": "Wire"},
                                       "canonicalUrl": {"url": f"https://x.test/{id_}"}, "summary": "s"}}

    feeds = {"^GSPC": [story("a", "Old", "2026-10-01T10:00:00Z"), story("b", "New", "2026-10-01T12:00:00Z")],
             "^IXIC": [story("b", "New", "2026-10-01T12:00:00Z"), {"id": "bad", "content": {}}],
             "^DJI": [], "AAPL": [story("c", "Apple", "2026-10-01T11:00:00Z")]}

    class FakeTicker:
        def __init__(self, s): self.s = s
        def get_news(self, count): return feeds.get(self.s, [])

    monkeypatch.setattr(ms, "PROVIDERS", {"yfinance": {"news": ms._yf_news}, "sample": ms.PROVIDERS["sample"]})
    monkeypatch.setattr(ms, "_yf_ticker", FakeTicker)
    r = client.get("/api/market/news").json()
    assert r["provider"] == "yfinance" and [i["title"] for i in r["data"]["items"]] == ["New", "Old"]
    assert client.get("/api/market/news?symbol=AAPL").json()["data"]["items"][0]["url"] == "https://x.test/c"
    r = client.get("/api/market/news?symbol=NONE").json()                       # nothing from yfinance -> sample, empty list
    assert r["provider"] == "sample" and r["data"]["items"] == []
