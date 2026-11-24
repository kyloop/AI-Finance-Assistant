"""Market boards: how sectors, a sector's industries, the largest companies, regions and the most active stocks did over a range.

Shared by the Live Market tab (`GET /api/market/boards/...`) and the market agent's tools, so a chart and a chat answer show the
same figures. Every figure is computed here in Python from market_service data (cached, with its sample fallback where one
exists); nothing comes from an LLM.

  sectors      the 11 sector SPDR funds (XLK, XLF...), named by sector          price history / quote
  industries   one sector's industries, as Yahoo's industry indices (^YH...)   yf.Sector + price history / quote
  largest      the 10 largest US-listed companies by market value             yf.screen + price history
  regions      each country's or area's main stock index (markets.yaml)        price history / quote, in local currency
  most_active  today's 20 most traded stocks                                   yf.screen
  sector_news  a sector's headlines: its fund's feed and its 3 largest companies' (not a board; the tab's news section)

A range is "1D" (today's change against the previous close) or a look-back: "1M", "3M", "YTD", "1Y".

The poller (`run_poller`, started with the API) keeps every board's data in the market cache: the first pass fetches whatever is
missing, then every `market.boards_refresh_seconds` it asks Yahoo again for the quotes and the most-active list, and every
`market.boards_industry_refresh_seconds` for the ~145 industry indices. Charts and chat then read the cache."""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.core.config import get_config
from src.core.market_service import LARGEST_US, SymbolNotFound, get_market_data
from src.rag import markets as MK

log = logging.getLogger(__name__)

RANGES = {"1D": "today", "1M": "last month", "3M": "last 3 months", "YTD": "year to date", "1Y": "last year"}
HISTORY_DAYS = 400                       # one history request covers every range (and shares the market agent's cache key)
LARGEST_COUNT, ACTIVE_COUNT = 10, 20
_WORKERS = 8                             # history fetches run in parallel; the cache serialises its own reads and writes


class UnknownRange(ValueError):
    pass


def range_start(rng: str, today: date | None = None) -> date | None:
    """The first day a range looks back to; None for "1D" (today's change)."""
    today = today or datetime.now(timezone.utc).date()
    if rng not in RANGES:
        raise UnknownRange(f"unknown range {rng!r}; use one of {', '.join(RANGES)}")
    return {"1D": None, "1M": today - timedelta(days=30), "3M": today - timedelta(days=91), "YTD": date(today.year, 1, 1),
            "1Y": today - timedelta(days=365)}[rng]


def _change(db: Session, symbol: str, start: date | None, refresh: bool = False) -> dict | None:
    """{return, start_date, end_date, as_of, freshness, provider} for one symbol: today's change for 1D, else the change since the
    first daily close on or after `start`, up to the live price when Yahoo has one (the poller refreshes it every minute) or the last
    close. `refresh` asks Yahoo for a new quote whatever the cache holds. None when there is no data."""
    try:
        quote = get_market_data(db, "quote", symbol, refresh=refresh)
    except SymbolNotFound:
        quote = None
    q = quote["data"] if quote else {}
    if start is None:
        if q.get("change_pct") is None:
            return None
        return {"return": q["change_pct"], "start_date": None, "end_date": quote["fetched_at"][:10], "as_of": quote["fetched_at"],
                "freshness": quote["freshness"], "provider": quote["provider"]}
    try:
        env = get_market_data(db, "history", symbol, days=HISTORY_DAYS)
    except SymbolNotFound:
        return None
    pts = [p for p in env["data"]["points"] if p["date"] >= start.isoformat() and p.get("close")]
    if not pts:
        return None
    end = {"close": pts[-1]["close"], "date": pts[-1]["date"], "env": env}
    if q.get("price") and quote["provider"] != "sample" and quote["fetched_at"][:10] >= end["date"]:
        end = {"close": q["price"], "date": quote["fetched_at"][:10], "env": quote}       # sample quotes and history don't line up
    if end["date"] == pts[0]["date"] and end["env"] is env:
        return None
    return {"return": round(end["close"] / pts[0]["close"] - 1, 4), "start_date": pts[0]["date"], "end_date": end["date"],
            "as_of": end["env"]["fetched_at"], "freshness": end["env"]["freshness"], "provider": end["env"]["provider"]}


def _changes(db: Session, symbols: list[str], start: date | None, refresh: bool = False) -> dict[str, dict | None]:
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        return dict(zip(symbols, pool.map(lambda s: _change(db, s, start, refresh), symbols)))


def _board(rng: str, rows: list[dict], changes: dict[str, dict | None], *, sort: bool = True, **extra) -> dict:
    """{range, label, start_date, end_date, as_of, freshness, provider, items, missing}: rows with their return, best first when `sort`."""
    items = [{**r, "return": c["return"]} for r in rows if (c := changes.get(r["symbol"]))]
    if sort:
        items.sort(key=lambda r: -r["return"])
    found = [c for c in changes.values() if c]
    real = [c for c in found if c["freshness"] != "sample"] or found       # labelled sample only when every figure is
    return {"range": rng, "label": RANGES[rng], "start_date": min((c["start_date"] for c in found if c["start_date"]), default=None),
            "end_date": max((c["end_date"] for c in found), default=None), "as_of": real[0]["as_of"] if real else None,
            "freshness": real[0]["freshness"] if real else None, "provider": real[0]["provider"] if real else None,
            "items": items, "missing": [r["symbol"] for r in rows if not changes.get(r["symbol"])], **extra}


def sector_board(db: Session, rng: str = "1M") -> dict:
    """The 11 sectors, each measured by its SPDR fund: [{symbol, name, key (Yahoo sector key), return}], best first."""
    rows = [{"symbol": s["symbol"], "name": s["name"].removesuffix(" sector"), "key": s["yahoo"]} for s in MK.sectors()]
    return _board(rng, rows, _changes(db, [r["symbol"] for r in rows], range_start(rng)))


def sector_profile(db: Session, sector: str) -> dict:
    """yf.Sector data for a sector named by its fund symbol ("XLK") or Yahoo key ("technology"), plus `fund` and `fund_name`.
    Raises SymbolNotFound for anything else, or when Yahoo can't be reached (there is no sample sector data)."""
    s = next((x for x in MK.sectors() if sector.upper() == x["symbol"] or sector.lower() == x["yahoo"]), None)
    if s is None:
        raise SymbolNotFound(sector)
    env = get_market_data(db, "sector", s["yahoo"])
    return {**env, "data": {**env["data"], "fund": s["symbol"], "fund_name": s["name"]}}


def industry_board(db: Session, sector: str, rng: str = "1M") -> dict:
    """One sector's industries, each measured by Yahoo's industry index: [{symbol, name, key, weight (share of the sector), return}]."""
    start = range_start(rng)
    prof = sector_profile(db, sector)["data"]
    rows = [{"symbol": i["symbol"], "name": i["name"], "key": i["key"], "weight": i["weight"]} for i in prof["industries"]]
    return _board(rng, rows, _changes(db, [r["symbol"] for r in rows], start), sector={"symbol": prof["fund"], "name": prof["fund_name"]})


def largest_board(db: Session, rng: str = "1M") -> dict:
    """The 10 largest US-listed companies by market value: [{symbol, name, market_cap, return}], in market-value order."""
    start = range_start(rng)
    quotes = get_market_data(db, "screen", LARGEST_US, count=LARGEST_COUNT)["data"]["quotes"]
    rows = [{"symbol": q["symbol"], "name": q["name"], "market_cap": q["market_cap"]} for q in quotes]
    return _board(rng, rows, _changes(db, [r["symbol"] for r in rows], start), sort=False)


def region_board(db: Session, rng: str = "1M") -> dict:
    """Each country's or area's main stock index: [{symbol (the index), name (the index), region, return}], best first. Returns are in
    each index's own currency."""
    rows = MK.regions()
    return _board(rng, rows, _changes(db, [r["symbol"] for r in rows], range_start(rng)))


def most_active(db: Session) -> dict:
    """Today's 20 most traded stocks by share volume: [{symbol, name, price, change_pct, volume, market_cap}]. Yahoo only."""
    env = get_market_data(db, "screen", "most_actives", count=ACTIVE_COUNT)
    rows = [{k: q.get(k) for k in ("symbol", "name", "price", "change_pct", "volume", "market_cap")} for q in env["data"]["quotes"]]
    rows.sort(key=lambda r: -(r["volume"] or 0))                  # Yahoo's list isn't strictly in volume order
    return {"range": "1D", "label": RANGES["1D"], "title": env["data"]["title"], "start_date": None, "end_date": env["fetched_at"][:10],
            "as_of": env["fetched_at"], "freshness": env["freshness"], "provider": env["provider"], "items": rows, "missing": []}


SECTOR_NEWS_COMPANIES = 3                # a sector's headlines: its fund's feed plus its largest companies'


def sector_news(db: Session, sector: str, count: int = 30) -> dict:
    """A sector's headlines: its SPDR fund's feed and its 3 largest companies' (yf.Sector), merged newest first without repeats.
    Shaped like the `news` endpoint's envelope ({data: {symbol, items}, provider, fetched_at, freshness}), plus `data.sector` and
    `data.feeds`. Raises SymbolNotFound for something that isn't a sector."""
    s = next((x for x in MK.sectors() if sector.upper() == x["symbol"] or sector.lower() == x["yahoo"]), None)
    if s is None:
        raise SymbolNotFound(sector)
    feeds = [s["symbol"]]
    try:
        feeds += [c["symbol"] for c in sector_profile(db, s["symbol"])["data"]["top_companies"][:SECTOR_NEWS_COMPANIES]]
    except SymbolNotFound:
        pass                                     # offline: the fund's feed alone
    envs = []
    for f in feeds:
        try:
            envs.append(get_market_data(db, "news", f))
        except SymbolNotFound:
            continue
    by_title: dict[str, dict] = {}
    for env in envs:
        for item in env["data"]["items"]:
            by_title.setdefault(" ".join(item["title"].lower().split()), item)
    items = sorted(by_title.values(), key=lambda i: i.get("published") or "", reverse=True)[:count]
    first = envs[0] if envs else {"provider": "sample", "fetched_at": datetime.now(timezone.utc).isoformat(), "freshness": "sample"}
    return {"data": {"symbol": s["symbol"], "sector": s["name"].removesuffix(" sector"), "feeds": feeds, "items": items},
            "provider": first["provider"], "fetched_at": first["fetched_at"], "freshness": first["freshness"]}


def refresh_once(session_factory=None, industries: bool = True) -> int:
    """One poll: new quotes for the sector funds, region indices, largest companies (and, with `industries`, every sector's industry
    indices) and a new most-active list; histories, sector profiles and the largest-companies list are fetched only when missing or
    past their cache lifetime. Returns how many symbols got a figure. Errors are logged; nothing raises."""
    if session_factory is None:
        from src.db.session import SessionLocal as session_factory
    with session_factory() as db:
        symbols = [s["symbol"] for s in MK.sectors()] + [r["symbol"] for r in MK.regions()]
        for name, count, refresh in ((LARGEST_US, LARGEST_COUNT, False), ("most_actives", ACTIVE_COUNT, True)):
            try:
                env = get_market_data(db, "screen", name, refresh=refresh, count=count)
                if name == LARGEST_US:
                    symbols += [q["symbol"] for q in env["data"]["quotes"]]
            except Exception:  # noqa: BLE001 — offline: Yahoo-only data, nothing to refresh
                log.warning("boards poll: screen %s failed", name)
        if industries:
            for s in MK.sectors():
                try:
                    symbols += [i["symbol"] for i in sector_profile(db, s["symbol"])["data"]["industries"]]
                except Exception:  # noqa: BLE001
                    log.warning("boards poll: sector %s failed", s["yahoo"])
        changes = _changes(db, list(dict.fromkeys(symbols)), range_start("1Y"), refresh=True)   # 1Y: the history every range reads
    return sum(1 for c in changes.values() if c)


async def run_poller() -> None:
    """Poll forever (first pass right away, industries included); cancelled on shutdown. Errors are logged, never fatal."""
    last_industries = 0.0
    while True:
        cfg = get_config()["market"]
        industries = time.monotonic() - last_industries >= cfg["boards_industry_refresh_seconds"]
        started = time.monotonic()
        try:
            n = await asyncio.to_thread(refresh_once, industries=industries)
            log.info("boards poll: %d symbols%s in %.1fs", n, " (with industries)" if industries else "", time.monotonic() - started)
            if industries:
                last_industries = started
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("boards poll failed")
        await asyncio.sleep(max(5.0, cfg["boards_refresh_seconds"] - (time.monotonic() - started)))
