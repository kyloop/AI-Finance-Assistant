from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session as DBSession

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
    """Batch quotes + sparklines for the Live tab. Unknown symbols go in `errors` instead of failing the batch."""
    wanted = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))[:20]
    items, errors = [], []
    for sym in wanted:
        try:
            env = get_market_data(db, "quote", sym, refresh=refresh)
            spark = sparkline(get_market_data(db, "intraday", sym, refresh=refresh)["data"]["points"])
            items.append(env | {"spark": spark})
        except SymbolNotFound:
            errors.append(sym)
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
def news(symbol: str | None = Query(None, max_length=15), refresh: bool = False, db: DBSession = Depends(get_db)):
    """Headlines for one stock, or general market news when no symbol is given. Polled, not pushed (Yahoo has no news stream)."""
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
