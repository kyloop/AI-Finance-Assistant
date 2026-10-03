"""Build the ticker directory (src/rag/tickers.py).

  python -m src.rag.build_tickers             # download the Nasdaq + SEC listings -> src/data/raw/tickers.csv, then rebuild the index
  python -m src.rag.build_tickers --offline   # rebuild the index from the saved CSV only
  python -m src.rag.build_tickers --csv-only  # refresh the CSV, skip the (slower) embedding step

The CSV alone is enough for exact ticker, name-prefix and mistyped-ticker lookups; the Qdrant collection `symbols_index.collection`
adds typo-tolerant company-name search. Run it weekly or whenever the listings change; stop the API first if it uses the local Qdrant store.
"""
from __future__ import annotations

import argparse
import time

from src.core.config import get_config

from . import tickers
from .store import get_client


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use the saved CSV, don't download")
    ap.add_argument("--csv-only", action="store_true", help="skip the Qdrant index")
    args = ap.parse_args()

    if args.offline:
        records = tickers.load_csv()
        if not records:
            raise SystemExit(f"{tickers.csv_path()} does not exist yet; run without --offline")
    else:
        records = tickers.download()
        print(f"downloaded {len(records)} listings -> {tickers.save_csv(records)}")
    etfs = sum(r["asset_type"] == "etf" for r in records)
    print(f"{len(records) - etfs} stocks, {etfs} ETFs, {sum(r['rank'] < tickers.NO_RANK for r in records)} ranked by the SEC")
    if args.csv_only:
        return
    client = get_client(get_config()["rag"])
    t = time.time()
    n = tickers.build_collection(client, records)
    print(f"indexed {n} names in '{get_config()['symbols_index']['collection']}' ({time.time() - t:.0f}s)")
    client.close()


if __name__ == "__main__":
    main()
