"""Ticker directory (src/rag/tickers.py) and how resolve_symbol uses it. A small listing stands in for the downloaded one."""
import pytest

from src.core import market_service as ms
from src.rag import tickers as T

LISTING = [
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ", "asset_type": "stock", "rank": 0},
    {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "asset_type": "stock", "rank": 1},
    {"symbol": "PLTR", "name": "Palantir Technologies Inc.", "exchange": "NASDAQ", "asset_type": "stock", "rank": 21},
    {"symbol": "BRK-B", "name": "Berkshire Hathaway Inc.", "exchange": "NYSE", "asset_type": "stock", "rank": 9},
    {"symbol": "NU", "name": "Nu Holdings Ltd.", "exchange": "NYSE", "asset_type": "stock", "rank": 80},
    {"symbol": "NUE", "name": "Nucor Corporation", "exchange": "NYSE", "asset_type": "stock", "rank": 300},
    {"symbol": "NUV", "name": "Nuveen Municipal Value Fund, Inc.", "exchange": "NYSE", "asset_type": "stock", "rank": T.NO_RANK},
    {"symbol": "APLE", "name": "Apple Hospitality REIT, Inc.", "exchange": "NYSE", "asset_type": "stock", "rank": 900},
    {"symbol": "SPY", "name": "State Street SPDR S&P 500 ETF Trust", "exchange": "NYSE Arca", "asset_type": "etf", "rank": T.NO_RANK},
]


@pytest.fixture(autouse=True)
def listing():
    T.set_directory(LISTING)
    T.set_name_searcher(lambda q, k: [])              # the name index is empty unless a test supplies one (never the real Qdrant store)
    ms._resolved.clear()
    yield
    T.set_directory(None)
    T.set_name_searcher(None)
    ms.set_symbol_resolver(lambda name: None)         # back to the conftest default
    ms._resolved.clear()


def real_resolution():
    """Use the directory and Yahoo path as in production (tests then replace `_yf_resolve`)."""
    ms.set_symbol_resolver(None)


@pytest.fixture
def no_yahoo(monkeypatch):
    real_resolution()
    monkeypatch.setattr(ms, "_yf_resolve", lambda name: None)


def test_exact_ticker_in_any_case_and_spelling(no_yahoo):
    assert ms.resolve_symbol("nu")["symbol"] == "NU"
    assert ms.resolve_symbol("NVDA")["match"] == "ticker"
    assert ms.resolve_symbol("brk.b")["symbol"] == "BRK-B"
    assert ms.resolve_symbol("BRK B")["symbol"] == "BRK-B"


def test_company_name_prefix_picks_the_biggest_company(no_yahoo):
    assert ms.resolve_symbol("Palantir")["symbol"] == "PLTR"
    hit = ms.resolve_symbol("apple")
    assert (hit["symbol"], hit["match"]) == ("AAPL", "name")
    assert [a["symbol"] for a in hit["alternatives"]] == ["APLE"]
    assert ms.resolve_symbol("Nu Holdings Ltd")["symbol"] == "NU"
    assert ms.resolve_symbol("the berkshire hathaway")["symbol"] == "BRK-B"


def test_mistyped_ticker_is_a_ranked_guess(no_yahoo):
    hit = ms.resolve_symbol("NUU")
    assert (hit["symbol"], hit["match"]) == ("NU", "fuzzy")
    assert [a["symbol"] for a in hit["alternatives"]] == ["NUE", "NUV"]       # the bigger company first
    assert ms.resolve_symbol("nvad")["symbol"] == "NVDA"                      # two letters swapped
    assert ms.resolve_symbol("aapl")["match"] == "ticker"                     # a real ticker is never "corrected"


def test_short_and_long_words_are_not_ticker_typos(no_yahoo):
    assert ms.resolve_symbol("nx") is None                                    # one or two letters are one edit from half the market
    assert T.get_directory().close_tickers("nvidiaa") == []                   # a longer word is a name, not a ticker


def test_misspelt_name_is_matched_by_spelling_and_the_bigger_company_wins(no_yahoo):
    hit = ms.resolve_symbol("nvdia")
    assert (hit["symbol"], hit["match"]) == ("NVDA", "fuzzy")
    assert ms.resolve_symbol("palantr")["symbol"] == "PLTR"
    hit = ms.resolve_symbol("applle")                                         # equally close to Apple Inc. and Apple Hospitality
    assert hit["symbol"] == "AAPL" and [a["symbol"] for a in hit["alternatives"]] == ["APLE"]
    assert ms.resolve_symbol("foobarbaz") is None


def test_unranked_listings_need_a_near_perfect_spelling():
    d = T.get_directory()
    assert [r["symbol"] for r in d.close_names("nuveen municipal vale fund")] == ["NUV"]        # 0.85+: any listing
    assert d.close_names("nuveen municipl") == []                                               # looser: only ranked companies


def test_same_meaning_uses_the_vector_search(no_yahoo):
    seen = []
    spy = LISTING[-1]
    T.set_name_searcher(lambda q, k: seen.append(q) or [{**spy, "score": 0.93}, {**LISTING[0], "score": 0.55}])
    hit = ms.resolve_symbol("s&p index etf")
    assert (hit["symbol"], hit["match"]) == ("SPY", "fuzzy") and seen == ["s&p index etf"]
    T.set_name_searcher(lambda q, k: [{**spy, "score": 0.5}])
    assert ms.resolve_symbol("foobarbaz") is None                             # nothing close enough: no guess
    T.set_name_searcher(lambda q, k: [{**LISTING[4], "score": 0.90}, {**LISTING[0], "score": 0.89}])
    assert ms.resolve_symbol("something vague")["symbol"] == "NVDA"           # a near-tie goes to the bigger company


def test_vector_search_failure_is_a_miss_not_an_error(no_yahoo):
    def boom(q, k):
        raise RuntimeError("index not built")
    T.set_name_searcher(boom)
    assert ms.resolve_symbol("foobarbaz") is None


def test_exact_directory_hits_skip_yahoo(monkeypatch):
    real_resolution()
    monkeypatch.setattr(ms, "_yf_resolve", lambda name: pytest.fail("the directory knows this one"))
    assert ms.resolve_symbol("Palantir")["symbol"] == "PLTR"


def test_yahoo_is_tried_before_a_guess(monkeypatch):
    real_resolution()
    monkeypatch.setattr(ms, "_yf_resolve", lambda name: {"symbol": "NUUU", "name": "Nuuu Corp"})
    assert ms.resolve_symbol("NUU")["symbol"] == "NUUU"


def test_guess_is_used_when_yahoo_is_down_but_not_remembered(monkeypatch):
    real_resolution()
    saved = {}
    monkeypatch.setattr(ms, "alias_store", (saved.get, saved.__setitem__))
    monkeypatch.setattr(ms, "_yf_resolve", lambda name: (_ for _ in ()).throw(OSError("offline")))
    assert ms.resolve_symbol("NUU")["symbol"] == "NU"
    assert ms._resolved == {} and saved == {}


def test_guesses_are_not_saved_as_aliases(monkeypatch):
    real_resolution()
    saved = {}
    monkeypatch.setattr(ms, "alias_store", (saved.get, saved.__setitem__))
    monkeypatch.setattr(ms, "_yf_resolve", lambda name: None)
    assert ms.resolve_symbol("NUU")["match"] == "fuzzy"
    assert saved == {}


def test_injected_resolver_bypasses_the_directory():
    ms.set_symbol_resolver(lambda name: None)
    assert ms.resolve_symbol("Palantir") is None


# ---- parsing the downloaded files -------------------------------------------------------------------------------------
NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
PLTR|Palantir Technologies Inc. - Class A Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
ZVZZT|NASDAQ TEST STOCK|G|Y|N|100|N|N
AAAAW|Some Co - Warrant|S|N|N|100|N|N
File Creation Time: 1001202618:01||||||
"""
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. New Common Stock|N|BRK.B|N|100|N|BRK-B
BAC$K|Bank of America Corporation Depositary Shares, 5.875% Non- Cumulative Preferred Stock|N|BACpK|N|100|N|BAC-K
SPY|State Street SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
File Creation Time: 1001202618:01||||||
"""
SEC = '{"0":{"cik_str":1,"ticker":"BRK-B","title":"BERKSHIRE HATHAWAY INC"},"1":{"cik_str":2,"ticker":"PLTR","title":"Palantir Technologies Inc."},' \
      '"2":{"cik_str":3,"ticker":"ADRX","title":"ADR EXAMPLE PLC"}}'


def test_parse_listings_merges_cleans_and_ranks():
    recs = {r["symbol"]: r for r in T.parse_listings(NASDAQ, OTHER, SEC)}
    assert set(recs) == {"PLTR", "QQQ", "BRK-B", "SPY", "ADRX"}                 # test issue, warrant and preferred dropped; SEC-only ADR kept
    assert recs["PLTR"]["name"] == "Palantir Technologies Inc."
    assert recs["BRK-B"]["name"] == "Berkshire Hathaway Inc."
    assert (recs["QQQ"]["asset_type"], recs["QQQ"]["rank"]) == ("etf", T.NO_RANK)
    assert (recs["BRK-B"]["rank"], recs["PLTR"]["rank"]) == (0, 1)
    assert recs["SPY"]["exchange"] == "NYSE Arca" and recs["ADRX"]["name"] == "Adr Example Plc"


def test_one_edit():
    assert T.one_edit("NUU", "NU") and T.one_edit("NU", "NUE") and T.one_edit("NUE", "NEU") and T.one_edit("NUE", "NUS")
    assert not T.one_edit("NUU", "NUU") and not T.one_edit("NUU", "NVDA") and not T.one_edit("AB", "ABCD")


def test_csv_round_trip(tmp_path):
    path = T.save_csv(LISTING, tmp_path / "t.csv")
    assert T.load_csv(path) == LISTING
    assert T.load_csv(tmp_path / "missing.csv") == []


def test_name_index_round_trip_and_ensure_index(monkeypatch):
    """Build the collection in an in-memory Qdrant with a fake embedder: one point per listing, built once, found by name."""
    import numpy as np
    from qdrant_client import QdrantClient

    class FakeEmbedder:                          # a name's vector is a one-hot on its first letter: enough to test the plumbing
        def embed(self, texts):
            for t in texts:
                v = np.zeros(384, dtype=np.float32)
                v[ord(t.lower()[0]) - 97] = 1.0
                yield v
    monkeypatch.setattr(T, "get_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(T, "load_csv", lambda path=None: LISTING)
    client = QdrantClient(":memory:")
    assert T.ensure_index(client) is True and T.ensure_index(client) is False       # built once
    assert client.count("finnie_symbols").count == len(LISTING)
    hits = T.search_names(client, "pal", 2)
    assert hits[0]["symbol"] == "PLTR" and hits[0]["score"] > 0.99 and hits[0]["asset_type"] == "stock"
    assert T.search_names(client, "x", 2, name="missing") == []


def test_ticker_mentions_cues():
    from src.workflow.symbols import ticker_mentions
    assert ticker_mentions("what is the company name witht ticker is aapl?") == ["AAPL"]
    assert ticker_mentions("the ticker symbol of nvda") == ["NVDA"]
    assert ticker_mentions("what is a ticker symbol?") == []                      # "symbol" is followed by a plain word that isn't listed
