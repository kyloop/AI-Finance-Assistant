from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session as DBSession

from src.core import market_boards as B
from src.core.market_service import INSTRUMENTS, MARKET_NEWS, NotAFund, SymbolNotFound, get_market_data, sparkline
from src.db.session import get_db

router = APIRouter(tags=["market"], prefix="/market")
INDICES = ["^GSPC", "^IXIC", "^DJI"]


def _get(db, endpoint, symbol, **params):
    try:
        return get_market_data(db, endpoint, symbol, **params)
    except NotAFund as e:
        if endpoint == "stock":
            raise HTTPException(404, f"{symbol.upper()} is {e.kind}, so it has no company data to research. Enter a stock ticker, e.g. AAPL.")
        raise HTTPException(404, f"{symbol.upper()} is {e.kind}, not a fund. Enter an ETF or mutual fund, e.g. VOO or VFIAX.")
    except SymbolNotFound:
        raise HTTPException(404, f"We couldn't find “{symbol}”. Check the ticker and try again.")


@router.get("/quote/{symbol}")
def quote(symbol: str, refresh: bool = False, db: DBSession = Depends(get_db)):
    return _get(db, "quote", symbol, refresh=refresh)


@router.get("/quotes")
def quotes(symbols: str = Query(..., max_length=200), refresh: bool = True, db: DBSession = Depends(get_db)):
    """Batch quotes + sparklines for the Live Market tab. Unknown symbols go in `errors` instead of failing the batch."""
    wanted = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))[:20]
    items, errors = [], []
    for sym in wanted:
        try:
            env = get_market_data(db, "quote", sym, refresh=refresh)
        except SymbolNotFound:
            errors.append(sym)
            continue
        try:   # mutual funds (VFIAX) and some listings have no 1-minute bars: keep the quote, just without a sparkline
            spark = sparkline(get_market_data(db, "intraday", sym, refresh=refresh)["data"]["points"])
        except SymbolNotFound:
            spark = []
        items.append(env | {"spark": spark})
    return {"items": items, "errors": errors}


@router.get("/symbols")
def symbols():
    """Tickers available from the current provider (the sample provider is a small fixed set)."""
    return [{"symbol": k, "name": v["name"]} for k, v in INSTRUMENTS.items() if v["asset_type"] != "index"]


@router.get("/intraday/{symbol}")
def intraday(symbol: str, db: DBSession = Depends(get_db)):
    return _get(db, "intraday", symbol, refresh=True)


@router.get("/history/{symbol}")
def history(symbol: str, db: DBSession = Depends(get_db)):
    return _get(db, "history", symbol)


@router.get("/indices")
def indices(db: DBSession = Depends(get_db)):
    return [_get(db, "quote", s) for s in INDICES]


@router.get("/news")
def news(symbol: str | None = Query(None, max_length=15), sector: str | None = Query(None, max_length=30), refresh: bool = False,
         db: DBSession = Depends(get_db)):
    """Headlines for one stock, a sector (its fund symbol, e.g. XLK, or Yahoo key: its fund's feed and its largest companies'),
    or general market news when neither is given. Polled, not pushed (Yahoo has no news stream)."""
    if sector and sector.strip():
        try:
            return B.sector_news(db, sector.strip())
        except SymbolNotFound:
            raise HTTPException(404, f"“{sector}” isn't one of the 11 sectors. Use a sector fund symbol, e.g. XLK.")
    return _get(db, "news", symbol.strip() if symbol and symbol.strip() else MARKET_NEWS, refresh=refresh)


@router.get("/fund/{symbol}")
def fund(symbol: str = Path(..., max_length=15), refresh: bool = False, db: DBSession = Depends(get_db)):
    """ETF / mutual fund profile for the Research tab (yfinance `funds_data`): overview, fees vs category, asset classes,
    top holdings, sector weights, equity valuation, bond duration and credit ratings. Cached for a day."""
    return _get(db, "fund", symbol.strip(), refresh=refresh)


@router.get("/stock/{symbol}")
def stock(symbol: str = Path(..., max_length=15), refresh: bool = False, db: DBSession = Depends(get_db)):
    """Company research for the Research tab: corporate actions (dividends, splits, capital gains, shares outstanding),
    the key lines of the financial statements (annual / quarterly / TTM) and earnings dates, estimates and revisions.
    A fund gets its dividends and capital gains only. Cached for 6 hours."""
    return _get(db, "stock", symbol.strip(), refresh=refresh)


# ---- boards: the Live Market tab's sector, industry, largest-company, region and most-active charts (src/core/market_boards.py)
def _board(fn, *args):
    try:
        return fn(*args)
    except B.UnknownRange as e:
        raise HTTPException(422, str(e))
    except SymbolNotFound:
        raise HTTPException(503, "This chart needs live data from Yahoo Finance, which isn't available right now.")


@router.get("/boards/sectors")
def sector_board(range: str = "1M", db: DBSession = Depends(get_db)):
    """The 11 sectors (each measured by its SPDR fund), best to worst over the range: 1D, 1M, 3M, YTD or 1Y."""
    return _board(B.sector_board, db, range)


@router.get("/boards/industries")
def industry_board(sector: str = Query(..., max_length=30), range: str = "1M", db: DBSession = Depends(get_db)):
    """One sector's industries (Yahoo's industry indices), best to worst. `sector` is its fund symbol (XLK) or Yahoo key."""
    return _board(B.industry_board, db, sector, range)


@router.get("/boards/largest")
def largest_board(range: str = "1M", db: DBSession = Depends(get_db)):
    """The 10 largest US-listed companies by market value and their return over the range."""
    return _board(B.largest_board, db, range)


@router.get("/boards/regions")
def region_board(range: str = "1M", db: DBSession = Depends(get_db)):
    """Each country's or area's main stock index, best to worst (in local currency)."""
    return _board(B.region_board, db, range)


@router.get("/boards/most-active")
def most_active(db: DBSession = Depends(get_db)):
    """Today's 20 most traded stocks by volume."""
    return _board(B.most_active, db)
