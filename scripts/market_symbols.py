"""Add the market directory (src/data/markets.yaml) to the `finnie_symbols` Qdrant collection, and check it.

  python -m scripts.market_symbols                       # dry run: list the points, clashes, the collection's counts and the
                                                         # searches as they would come out; writes nothing to Qdrant
  python -m scripts.market_symbols --out points.tsv      # ...and save every point (id, embedded text, payload) for review
  python -m scripts.market_symbols --check-news          # ...and search Yahoo for every news term (read-only)
  python -m scripts.market_symbols --write               # upsert the market points (company points are left alone)
  python -m scripts.market_symbols --verify              # read back from Qdrant: counts, every point's payload, the searches

Market points are upserted by fixed ids, never by rebuilding the collection, so the 15k company points and the running app are
unaffected and a re-run updates in place."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter

from qdrant_client import models

from src.core.config import get_config
from src.rag import markets as M
from src.rag import tickers as T
from src.rag.store import QDRANT_LOCK, get_client, get_embedder

# (query, expected symbol, or "group:<name>"); companies must be unaffected
SEARCHES = [("USD---JPY", "JPY=X"), ("Europe vs USD", "EURUSD=X"), ("japanese yen", "JPY=X"), ("etherium", "ETH-USD"),
            ("forex", "group:forex"), ("gold price", "GC=F"), ("10 year treasury", "^TNX"), ("crude oil", "CL=F"),
            ("bitcoin", "BTC-USD"), ("tech sector", "XLK"), ("Palantir", "PLTR"), ("NVIDIA", "NVDA"), ("s&p 500 etf", "VOO")]


def _cfg() -> dict:
    return get_config()["symbols_index"]


def _key(hit: dict) -> str:
    return f"group:{hit['group']}" if hit.get("asset_type") == M.GROUP else hit["symbol"]


def _counts(client, name: str) -> dict:
    with QDRANT_LOCK:
        total = client.count(name, exact=True).count
        by = {t: client.count(name, count_filter=models.Filter(must=[models.FieldCondition(key="asset_type", match=models.MatchValue(value=t))]),
                              exact=True).count for t in ("stock", "etf", M.MARKET, M.GROUP)}
    return {"total": total, **by}


def _pick(hits: list[dict]) -> tuple[str | None, list[str]]:
    """What the lookup would take: the best hit at or above min_score, and the other symbols within score_margin of it."""
    cfg = _cfg()
    hits = sorted(hits, key=lambda h: -h["score"])
    if not hits or hits[0]["score"] < cfg["min_score"]:
        return None, []
    best = _key(hits[0])
    near = list(dict.fromkeys(_key(h) for h in hits[1:] if hits[0]["score"] - h["score"] <= cfg["score_margin"] and _key(h) != best))
    return best, near


def simulate(client, name: str, pts: list[dict], live: bool = False) -> list[dict]:
    """The searches: `live` reads everything from Qdrant; otherwise as they would come out after --write, market points scored
    locally and companies in Qdrant (read-only)."""
    emb = get_embedder()
    vecs = [] if live else list(emb.embed([p["text"] for p in pts]))
    rows = []
    for q, want in SEARCHES:
        qv = next(iter(emb.embed([q])))
        market = [{**p["payload"], "score": float(qv @ v)} for p, v in zip(pts, vecs)]
        with QDRANT_LOCK:
            company = [{**h.payload, "score": h.score} for h in client.query_points(name, query=qv.tolist(), limit=5, with_payload=True).points]
        hits = sorted(market + company, key=lambda h: -h["score"])[:8]
        best, near = _pick(hits)
        rows.append({"query": q, "want": want, "got": best, "near": near, "score": hits[0]["score"] if hits else 0,
                     "top": [(_key(h), round(h["score"], 3)) for h in hits[:4]]})
    return rows


def ticker_clashes(data: dict) -> list[tuple[str, str]]:
    """Market aliases and codes that are also a listed ticker ("btc", "dax"): the market wins, `$BTC` / "BTC stock" still reach the ticker."""
    d = T.get_directory()
    out = []
    for e in M.entries(data):
        for a in [*e["aliases"], *e["codes"]]:
            r = d.exact(a)
            if r:
                out.append((a, f"{e['symbol']} vs ticker {r['symbol']} ({r['name']})"))
    return out


def check_news(data: dict) -> list[dict]:
    import yfinance as yf
    terms = list(dict.fromkeys([t for g in data.values() for t in g["news"]] + [e["news"] for e in M.entries(data) if e["news"]]))
    now, rows = time.time(), []
    for t in terms:
        try:
            n = yf.Search(t, max_results=1, news_count=20, lists_count=0, timeout=15).news or []
            rows.append({"term": t, "stories": len(n), "last_24h": sum(now - (x.get("providerPublishTime") or 0) < 86400 for x in n),
                         "sample": (n[0].get("title") or "")[:70] if n else ""})
        except Exception as e:  # noqa: BLE001
            rows.append({"term": t, "stories": f"error {type(e).__name__}", "last_24h": 0, "sample": ""})
    return rows


def write(client, name: str, pts: list[dict]) -> int:
    vecs = list(get_embedder().embed([p["text"] for p in pts]))
    with QDRANT_LOCK:
        for field in ("symbol", "group"):
            client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
        for i in range(0, len(pts), 200):
            client.upsert(name, points=[models.PointStruct(id=p["id"], vector=v.tolist(), payload=p["payload"])
                                        for p, v in zip(pts[i:i + 200], vecs[i:i + 200])])
    return len(pts)


def verify(client, name: str, pts: list[dict]) -> list[str]:
    """Every point read back and compared with the YAML; returns the problems."""
    problems = []
    with QDRANT_LOCK:
        stored = {}
        for i in range(0, len(pts), 200):
            stored.update({str(r.id): r.payload for r in client.retrieve(name, ids=[p["id"] for p in pts[i:i + 200]], with_payload=True)})
    for p in pts:
        if p["id"] not in stored:
            problems.append(f"missing: {p['text']!r} ({p['payload'].get('symbol') or p['payload']['group']})")
        elif stored[p["id"]] != p["payload"]:
            problems.append(f"differs: {p['text']!r}: stored {stored[p['id']]} != {p['payload']}")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="save every point as TSV (id, embedded text, payload)")
    ap.add_argument("--check-news", action="store_true", help="search Yahoo for every news term (read-only)")
    ap.add_argument("--write", action="store_true", help="upsert the market points into Qdrant")
    ap.add_argument("--verify", action="store_true", help="read the market points back from Qdrant and check them")
    args = ap.parse_args()

    data, name = M.load(), _cfg()["collection"]
    pts = M.points(data)
    client = get_client(get_config()["rag"])
    kinds = Counter(p["payload"]["group"] for p in pts)
    print(f"{len(M.entries(data))} symbols in {len(data)} groups -> {len(pts)} points: " + ", ".join(f"{g} {n}" for g, n in kinds.items()))
    print(f"exact-match table: {len(M.exact_table(data))} texts")
    if args.out:
        with open(args.out, "w") as f:
            f.write("id\ttext\tpayload\n" + "".join(f"{p['id']}\t{p['text']}\t{json.dumps(p['payload'])}\n" for p in pts))
        print(f"points saved to {args.out}")

    c = M.clashes(data)
    print(f"\nclashes inside markets.yaml: {len(c)}" + "".join(f"\n  {k}: {v}" for k, v in c))
    tc = ticker_clashes(data)
    print(f"aliases that are also a listed ticker (market wins): {len(tc)}" + "".join(f"\n  {a}: {w}" for a, w in tc))

    print(f"\n{name} now: {_counts(client, name)}")
    if args.write:
        print(f"upserted {write(client, name, pts)} points")
        print(f"{name} after: {_counts(client, name)}")
    if args.verify or args.write:
        problems = verify(client, name, pts)
        print(f"read back {len(pts)} points: {len(problems)} problems" + "".join(f"\n  {p}" for p in problems[:30]))

    label = "searches (live)" if args.verify or args.write else "searches as they would come out (market points scored locally)"
    print(f"\n{label}:")
    for r in simulate(client, name, pts, live=args.verify or args.write):
        ok = "ok " if r["got"] == r["want"] and not r["near"] else ("tie" if r["got"] == r["want"] else "BAD")
        print(f"  {ok} {r['query']!r:<20} -> {r['got']} {('(also ' + ', '.join(r['near']) + ')') if r['near'] else ''}  top: {r['top']}")

    if args.check_news:
        rows = check_news(data)
        print(f"\nYahoo news per term ({len(rows)} terms):")
        for r in rows:
            print(f"  {r['term']:<22} stories={r['stories']!s:<3} 24h={r['last_24h']:<3} {r['sample']}")


if __name__ == "__main__":
    main()
