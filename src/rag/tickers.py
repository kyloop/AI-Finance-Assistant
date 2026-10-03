"""Ticker directory: every US-listed stock and ETF (symbol, company name), so a name or a mistyped ticker can be resolved to the right
symbol without a Yahoo call. Prices are not stored here, they stay live from the market service.

Source files (free, official): Nasdaq Trader `nasdaqlisted.txt` + `otherlisted.txt` (all US exchanges, ~13k rows) and SEC
`company_tickers.json`, whose order is roughly by market cap and so ranks look-alike matches ("NUU" -> NU before NUV).
`python -m src.rag.build_tickers` downloads them into `src/data/raw/tickers.csv` and builds the Qdrant collection `finnie_symbols`.

Lookup order in `lookup(query)`:
  1. exact ticker             "nu", "BRK.B"            plain dictionary
  2. company-name prefix      "Palantir"               dictionary, best-ranked company first
  3. close ticker             "NUU" -> NU              one typo away (3-4 letter inputs only), best-ranked first
  4. misspelt company name    "nvdia", "netflx"        character similarity over the names, best-ranked first (bge embeddings can't do
                                                       this: "netflx" lands on InflaRx, "amazn" on Amaze)
  5. same meaning             "s&p 500 etf", "nu bank" Qdrant vector search over the names
Steps 3-5 are guesses: the hit carries `match: "fuzzy"` and `alternatives` so the caller can say what it assumed."""
from __future__ import annotations

import csv
import difflib
import logging
import os
import re
import threading
import urllib.request
import uuid
import warnings
from pathlib import Path

from qdrant_client import QdrantClient, models

from .store import EMBEDDING_DIM, QDRANT_LOCK, get_embedder

log = logging.getLogger(__name__)

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
SEC_URL = "https://www.sec.gov/files/company_tickers.json"
# SEC rejects requests without a contact address in the agent; set SEC_USER_AGENT="Your Name you@example.com" in .env for real use
USER_AGENT = os.getenv("SEC_USER_AGENT", "finnie-finance-assistant educational-project@example.com")
EXCHANGES = {"Q": "NASDAQ", "N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
FIELDS = ["symbol", "name", "exchange", "asset_type", "rank"]
NO_RANK = 1_000_000

_NOT_COMMON = re.compile(r"\b(warrants?|rights?|units?|notes?|preferred|pfd|depositary|debentures?|subordinated|test)\b", re.I)
_SUFFIX = re.compile(r"\s+-\s+(?:class\s+\w+\s+)?(?:common stock|ordinary shares?|american depositary shares?|common shares?|"
                     r"shares of beneficial interest|units?)\b.*$|\s+(?:class\s+\w+\s+)?(?:common stock|ordinary shares?|common shares?)\b.*$", re.I)
_NOT_COMMON_SYMBOL = re.compile(r"-(P[A-Z]{0,2}|W|WS|WT|U|R|RT)$")      # SEC lists preferreds, warrants, units and rights as "WFC-PC", "ABC-WS"
_GENERIC_WORDS = set("""technologies technology holdings international financial industries pharmaceuticals systems capital energy global resources
therapeutics bancorp partners acquisition properties trust fund group company limited corporation services solutions brands""".split())
_CORP = re.compile(r"[,.]|\b(inc|corp|corporation|co|company|ltd|limited|plc|llc|lp|holdings?|group|the)\b", re.I)


def csv_path() -> Path:
    from src.core.config import DATA_DIR
    return DATA_DIR / "raw" / "tickers.csv"


def clean_name(raw: str) -> str:
    """"Palantir Technologies Inc. - Class A Common Stock" -> "Palantir Technologies Inc."."""
    return re.sub(r"\s+New$", "", _SUFFIX.sub("", raw).strip(" -,"))


def norm_name(text: str) -> str:
    """Lower case, no punctuation, no corporate suffixes: "Nu Holdings Ltd." and "nu holdings" compare equal."""
    return " ".join(_CORP.sub(" ", re.sub(r"[^\w&\s\-]", " ", text.lower().replace("&", " and "))).replace("-", " ").split())


def norm_symbol(text: str) -> str:
    """"brk.b" / "BRK B" / "brk-b" -> "BRK-B" (Yahoo's spelling)."""
    return re.sub(r"[.\s/]", "-", text.strip().upper())


# ---- download -----------------------------------------------------------------------------------------------------
def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_listings(nasdaq: str, other: str, sec: str) -> list[dict]:
    """Merge the three source files into records {symbol, name, exchange, asset_type, rank}. Test issues, warrants, rights, units,
    preferreds and notes are dropped: nobody asks for them by name."""
    import json
    rank = {v["ticker"].upper(): i for i, v in enumerate(json.loads(sec).values())}
    sec_names = {v["ticker"].upper(): v["title"] for v in json.loads(sec).values()}
    records: dict[str, dict] = {}

    def add(symbol: str, raw: str, exchange: str, etf: str, test: str, act: str = "") -> None:
        if test == "Y" or "$" in act + symbol or "^" in symbol or _NOT_COMMON.search(raw):
            return
        symbol = symbol.upper().replace(".", "-")
        name = clean_name(raw)
        if symbol not in records and name and not _NOT_COMMON_SYMBOL.search(symbol):
            records[symbol] = {"symbol": symbol, "name": name, "exchange": exchange, "asset_type": "etf" if etf == "Y" else "stock",
                               "rank": rank.get(symbol, NO_RANK)}

    for row in csv.DictReader(nasdaq.splitlines(), delimiter="|"):
        if row.get("Symbol") and not row["Symbol"].startswith("File Creation"):
            add(row["Symbol"], row["Security Name"], "NASDAQ", row["ETF"], row["Test Issue"])
    for row in csv.DictReader(other.splitlines(), delimiter="|"):
        if row.get("ACT Symbol") and not row["ACT Symbol"].startswith("File Creation"):
            add(row["NASDAQ Symbol"] or row["ACT Symbol"], row["Security Name"], EXCHANGES.get(row["Exchange"], row["Exchange"]),
                row["ETF"], row["Test Issue"], row["ACT Symbol"])
    for symbol, title in sec_names.items():                       # SEC-only listings (ADRs, OTC) get the SEC's name
        if symbol not in records and "$" not in symbol and not _NOT_COMMON_SYMBOL.search(symbol):
            records[symbol] = {"symbol": symbol, "name": title.title() if title.isupper() else title, "exchange": "", "asset_type": "stock",
                               "rank": rank[symbol]}
    for symbol in [s for s in records if s.endswith("W") and len(s) >= 5 and (s[:-1] in records or s[:-2] in records)]:
        del records[symbol]                                    # Nasdaq warrants: "DJTWW" next to "DJT"
    return sorted(records.values(), key=lambda r: (r["rank"], r["symbol"]))


def download() -> list[dict]:
    return parse_listings(_get(NASDAQ_URL), _get(OTHER_URL), _get(SEC_URL))


def save_csv(records: list[dict], path: Path | None = None) -> Path:
    path = path or csv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(records)
    return path


def load_csv(path: Path | None = None) -> list[dict]:
    path = path or csv_path()
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return [{**r, "rank": int(r["rank"])} for r in csv.DictReader(f)]


# ---- in-memory directory ------------------------------------------------------------------------------------------
class Directory:
    """Exact-ticker, name-prefix and close-ticker lookups over the records. No network, no Qdrant."""

    def __init__(self, records: list[dict]):
        self.records = records
        self.by_symbol = {r["symbol"]: r for r in records}
        self.names = [(norm_name(r["name"]), r) for r in records]
        self._spellings: list[tuple[str, dict]] | None = None        # built on first use: (name or one word of it, record)
        self.by_length: dict[int, list[dict]] = {}
        for r in records:
            self.by_length.setdefault(len(r["symbol"]), []).append(r)

    def exact(self, query: str) -> dict | None:
        return self.by_symbol.get(norm_symbol(query))

    def by_name(self, query: str) -> list[dict]:
        """Companies whose normalised name starts with the query's words ("palantir" -> Palantir Technologies), best-ranked first."""
        q = norm_name(query)
        if not q:
            return []
        hits = [r for n, r in self.names if n == q or n.startswith(q + " ")]
        return sorted(hits, key=lambda r: (r["asset_type"] == "etf", r["rank"], len(r["symbol"])))

    def close_tickers(self, query: str, n: int = 5) -> list[dict]:
        """Tickers one edit away (a letter added, dropped, changed or two swapped), best-ranked first. Only for 3-4 letter inputs:
        a 1-2 letter ticker is one edit from half the market, and a longer word is more likely a name."""
        q = norm_symbol(query)
        if not (3 <= len(q) <= 4) or not q.isalpha():
            return []
        hits = [r for length in (len(q) - 1, len(q), len(q) + 1) for r in self.by_length.get(length, ()) if one_edit(q, r["symbol"])]
        return sorted(hits, key=lambda r: (r["rank"], r["symbol"]))[:n]

    def spellings(self) -> list[tuple[str, dict]]:
        """Every normalised name, plus each distinctive word (5+ letters, 4+ for the first) of the well-known companies' names, so "disnee" can find Walt Disney."""
        if self._spellings is None:
            keys = []
            for name, r in self.names:
                keys.append((name, r))
                if r["rank"] < NO_RANK:
                    words = name.split()
                    keys += [(w, r) for i, w in enumerate(dict.fromkeys(words)) if len(w) >= (4 if i == 0 else 5) and w not in _GENERIC_WORDS and w != name]
            self._spellings = keys
        return self._spellings

    def close_names(self, query: str, n: int = 5) -> list[dict]:
        """Companies whose name (or a word of it) is spelt almost like the query ("nvdia" -> NVIDIA, "netflx" -> Netflix), best-ranked of
        the best matches first. A near-perfect match (0.85+) may be any listing; a looser one (0.80+) only a company the SEC ranks."""
        q = norm_name(query)
        if len(q) < 4:
            return []
        sm = difflib.SequenceMatcher(autojunk=False)
        sm.set_seq2(q)
        best: dict[str, tuple[float, dict]] = {}
        for key, r in self.spellings():
            sm.set_seq1(key)
            if sm.real_quick_ratio() < LOOSE or sm.quick_ratio() < LOOSE:
                continue
            score = sm.ratio()
            if score >= (CLOSE if r["rank"] == NO_RANK else LOOSE) and score > best.get(r["symbol"], (0, r))[0]:
                best[r["symbol"]] = (score, r)
        if not best:
            return []
        top = max(score for score, _ in best.values())
        near = [r for score, r in best.values() if score >= top - TIE]
        return sorted(near, key=lambda r: (r["rank"], len(r["symbol"]), r["symbol"]))[:n]


CLOSE, LOOSE, TIE = 0.85, 0.80, 0.03       # spelling similarity: any listing / ranked companies only / how close counts as tied


def one_edit(a: str, b: str) -> bool:
    """Damerau-Levenshtein distance of exactly 1 between two strings."""
    if a == b:
        return False
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = [i for i in range(la) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if la < lb else (b, a)
    i = 0
    while i < len(short) and short[i] == long_[i]:
        i += 1
    return short[i:] == long_[i + 1:]


_directory: Directory | None = None
_dir_lock = threading.Lock()


def get_directory() -> Directory:
    global _directory
    with _dir_lock:
        if _directory is None:
            _directory = Directory(load_csv())
        return _directory


def set_directory(records: list[dict] | None) -> None:
    """Tests inject a small listing; None reloads the CSV on next use."""
    global _directory
    with _dir_lock:
        _directory = Directory(records) if records is not None else None


# ---- Qdrant: close company names ------------------------------------------------------------------------------------
def _cfg() -> dict:
    from src.core.config import get_config
    return get_config()["symbols_index"]


def point_id(symbol: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"symbol:{symbol}"))


def build_collection(client: QdrantClient, records: list[dict], name: str | None = None) -> int:
    """(Re)create the collection: one point per listing, the vector is the embedded company name (symbol not included, it embeds badly).
    The Qdrant lock is held per batch, not for the whole build, so the news index and knowledge base keep working meanwhile."""
    name = name or _cfg()["collection"]
    with QDRANT_LOCK:
        if client.collection_exists(name):
            client.delete_collection(name)
        client.create_collection(name, vectors_config=models.VectorParams(size=EMBEDDING_DIM, distance=models.Distance.COSINE))
        with warnings.catch_warnings():                  # local (embedded) Qdrant ignores payload indexes and warns
            warnings.simplefilter("ignore", UserWarning)
            client.create_payload_index(name, "asset_type", models.PayloadSchemaType.KEYWORD)
    for i in range(0, len(records), 500):
        batch = records[i:i + 500]
        vectors = list(get_embedder().embed([r["name"] for r in batch]))
        with QDRANT_LOCK:
            client.upsert(name, points=[models.PointStruct(id=point_id(r["symbol"]), vector=v.tolist(), payload=r)
                                        for r, v in zip(batch, vectors)])
    return len(records)


def ensure_index(client: QdrantClient | None = None) -> bool:
    """Build the name index from the saved CSV if the collection doesn't exist yet (first start after `git pull`). Returns True if it built."""
    records = load_csv()
    if client is None:
        from src.workflow.tools import _kb_client
        client = _kb_client()
    with QDRANT_LOCK:
        if not records or client.collection_exists(_cfg()["collection"]):
            return False
    log.info("building the ticker name index (%d listings)", len(records))
    build_collection(client, records)
    return True


def search_names(client: QdrantClient, query: str, k: int = 5, name: str | None = None) -> list[dict]:
    """Closest company names as record dicts with a `score`. The query is embedded as a plain name, not as a retrieval question."""
    name = name or _cfg()["collection"]
    qvec = next(iter(get_embedder().embed([query]))).tolist()
    with QDRANT_LOCK:
        if not client.collection_exists(name):
            return []
        hits = client.query_points(name, query=qvec, limit=k, with_payload=True).points
    return [{**h.payload, "score": h.score} for h in hits]


def _hit(r: dict, match: str, alternatives: list[dict] | None = None) -> dict:
    out = {"symbol": r["symbol"], "name": r["name"], "match": match}
    if alternatives:
        out["alternatives"] = [{"symbol": a["symbol"], "name": a["name"]} for a in alternatives if a["symbol"] != r["symbol"]][:3]
    return out


def lookup_exact(query: str) -> dict | None:
    """Steps 1-2: an exact ticker or a company name that starts with the query. Safe to trust."""
    d = get_directory()
    r = d.exact(query)
    if r:
        return _hit(r, "ticker")
    named = d.by_name(query)
    return _hit(named[0], "name", named[1:]) if named else None


_name_searcher = None            # tests inject fn(query, k) -> [record + score]; None = the Qdrant collection


def set_name_searcher(fn) -> None:
    global _name_searcher
    _name_searcher = fn


def lookup_fuzzy(query: str) -> dict | None:
    """Steps 3-5: a mistyped ticker or company name, or the same thing said differently. A guess, so the hit says `match: "fuzzy"`."""
    d = get_directory()
    found = d.close_tickers(query) or d.close_names(query)
    if found:
        return _hit(found[0], "fuzzy", found[1:])
    if len(norm_name(query)) < 4:                                  # a short word is too ambiguous to match by meaning
        return None
    try:
        if _name_searcher:
            hits = _name_searcher(query, 3)
        else:
            from src.workflow.tools import _kb_client
            hits = search_names(_kb_client(), query, 3)
    except Exception:  # noqa: BLE001 — the index may not be built yet; a miss is fine
        log.warning("symbol name search unavailable", exc_info=True)
        return None
    cfg = _cfg()
    good = [h for h in hits if h["score"] >= cfg["min_score"]]
    if not good:
        return None
    near = sorted((h for h in good if h["score"] >= good[0]["score"] - cfg["score_margin"]), key=lambda h: (h["rank"], -h["score"]))
    return _hit(near[0], "fuzzy", [h for h in good if h is not near[0]])
