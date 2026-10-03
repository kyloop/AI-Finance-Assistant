"""Company questions that need context: a misspelt name, "them" pointing at the previous company, "the same sector", and a price asked
for something we can't identify (which must ask, not go to Wikipedia)."""
import json

import pytest

from src.core import llm as llm_module
from src.core import market_service as ms
from src.core.market_service import set_peer_finder, set_symbol_resolver
from src.workflow import news as NEWS
from src.workflow import symbols as SYM
from src.workflow.graph import run_chat
from tests.test_news import PROFILE, db, fake_feed, story  # noqa: F401  (db is a fixture)

NVIDIA = {"symbol": "NVDA", "name": "NVIDIA Corporation"}
NU = {"symbol": "NU", "name": "Nu Holdings Ltd."}
PEERS = {"sector": "Technology", "industry": "Semiconductors",
         "peers": [{"symbol": "AVGO", "name": "Broadcom Inc."}, {"symbol": "MU", "name": "Micron Technology"}, {"symbol": "AMD", "name": "AMD"}]}


class MentionLLM:
    """Router -> `intents`; the company-mention prompt -> `mentions`; everything else -> a plain sentence."""
    model = "fake"

    def __init__(self, intents, mentions):
        self.intents, self.mentions, self.prompts = intents, mentions, []

    def invoke(self, messages):
        system, user = messages[0][1], messages[1][1]
        self.prompts.append(user)
        reply = (json.dumps({"intents": self.intents, "confidence": 0.9}) if "You are the router" in system
                 else json.dumps({"mentions": self.mentions}) if "publicly traded companies" in system else "Done.")
        return type("R", (), {"content": reply})()


@pytest.fixture(autouse=True)
def resolver():
    set_symbol_resolver(lambda name: {"nvidia": NVIDIA, "nu": NU}.get(name.lower()))
    set_peer_finder(lambda sym: PEERS if sym == "NVDA" else None)
    yield
    set_peer_finder(None)


def ask(q, db, history=None):
    return run_chat(q, history=history or [], profile=PROFILE, holdings=[], db=db)


# ---- helpers ------------------------------------------------------------------------------------------------
def test_sector_questions_are_recognised():
    for q in ("what about news from the same industry sector?", "how are its competitors doing", "news about NVDA's peers"):
        assert NEWS.asks_about_sector(q), q
    assert not NEWS.asks_about_sector("latest news on NVDA")


def test_a_misspelt_company_is_not_left_over_as_a_news_topic():
    assert NEWS.topic_words("what is nvdia price today? latest news for them?", [], ["NVIDIA", "NVIDIA Corporation"]) == []
    assert NEWS.topic_words("grab the recent news", []) == []
    assert NEWS.topic_words("nvidia export restrictions", [], ["NVIDIA"]) == ["export", "restrictions"]


def test_company_taken_from_history_is_dropped_when_the_message_names_another():
    set_symbol_resolver(lambda name: NVIDIA if name.lower() == "nvidia" else None)
    llm_module.set_llm(MentionLLM(["market"], ["NVIDIA"]))               # the model wrongly reuses the earlier company
    hist = [{"role": "user", "content": "what is nvdia price"}]
    assert SYM.resolve("what is the price of foobarbaz today?", history=hist) == []
    assert [r["symbol"] for r in SYM.resolve("what's the price today?", history=hist)] == ["NVDA"]      # nothing named: history it is
    assert [r["symbol"] for r in SYM.resolve("what is nvdia price?", history=hist)] == ["NVDA"]        # misspelt but named


def test_a_bare_ticker_beats_the_company_from_history():
    """"what about NU?" has no phrasing cue, and the model ignored the two-letter name and reused NVIDIA from the last turn."""
    llm_module.set_llm(MentionLLM(["market", "news"], ["NVIDIA"]))
    hist = [{"role": "user", "content": "latest nvda price and news"}, {"role": "assistant", "content": "NVDA is $230."}]
    assert [r["symbol"] for r in SYM.resolve("what about NU?", history=hist)] == ["NU"]
    assert SYM.resolve("what about ZZZZ?", history=hist) == []                         # an unknown ticker: nothing, not NVIDIA
    assert [r["symbol"] for r in SYM.resolve("and what about its stock price?", history=hist)] == ["NVDA"]   # no ticker written: history
    assert [r["symbol"] for r in SYM.resolve("what about their ETF price?", history=hist)] == ["NVDA"]        # ETF is not a company


def test_its_means_the_company_discussed_last_but_them_means_all():
    llm_module.set_llm(MentionLLM(["market"], ["NVIDIA", "NU"]))                     # the model lists both
    hist = [{"role": "user", "content": "latest nvda price"}, {"role": "assistant", "content": "NVDA is $230."},
            {"role": "user", "content": "what about NU?"}, {"role": "assistant", "content": "Nu Holdings is $13."}]
    assert [r["symbol"] for r in SYM.resolve("what about its stock price?", history=hist)] == ["NU"]
    assert [r["symbol"] for r in SYM.resolve("compare their stock prices", history=hist)] == ["NVDA", "NU"]


def test_without_an_llm_them_means_the_company_in_the_last_question():
    hist = [{"role": "user", "content": "Any news on NVIDIA?"}]
    assert [r["symbol"] for r in SYM.resolve("and what about them?", use_llm=False, history=hist)] == ["NVDA"]
    assert SYM.resolve("and what about them?", use_llm=False, history=[]) == []


# ---- through the graph --------------------------------------------------------------------------------------
def test_misspelt_company_gets_price_and_news(db, monkeypatch):
    fake_feed(monkeypatch, {"NVDA": [story(1, "Nvidia earnings beat")]})
    llm_module.set_llm(MentionLLM(["market", "news"], ["NVIDIA"]))
    s = ask("what is nvdia price today? what is the latest news for them?", db)
    assert "resolved “NVIDIA” → NVDA" in s["trace"]
    assert s["agent_outputs"]["market"]["status"] == "answered" and "NVDA" in s["agent_outputs"]["market"]["content"]
    assert "Nvidia earnings beat" in s["agent_outputs"]["news"]["content"] and "research" not in " ".join(s["trace"])


def test_them_and_recent_news_use_the_company_from_the_conversation(db, monkeypatch):
    calls = fake_feed(monkeypatch, {"NVDA": [story(1, "Nvidia earnings beat")]})
    llm = MentionLLM(["news"], ["NVIDIA"])
    llm_module.set_llm(llm)
    hist = [{"role": "user", "content": "what is nvdia price?"}, {"role": "assistant", "content": "NVDA is $138."}]
    s = ask("can you grab the recent news ?", db, hist)
    assert calls == ["NVDA"] and "Nvidia earnings beat" in s["agent_outputs"]["news"]["content"]
    assert "nvdia price" in next(p for p in llm.prompts if "Latest message" in p)      # the model was shown the conversation


def test_same_sector_news_comes_from_the_industry_peers(db, monkeypatch):
    calls = fake_feed(monkeypatch, {"AVGO": [story(1, "Broadcom wins deal")], "MU": [story(2, "Micron rallies")], "AMD": [story(3, "AMD launches chip")]})
    llm_module.set_llm(MentionLLM(["news"], ["NVIDIA"]))
    s = ask("what about news from the same industry sector?", db, [{"role": "user", "content": "news on nvidia"}])
    assert calls == ["AVGO", "MU", "AMD"] and "NVDA" not in calls                        # the peers, not the company itself
    news = s["agent_outputs"]["news"]["content"]
    assert "NVDA is in Semiconductors, Technology" in news and "Broadcom wins deal" in news and "Micron rallies" in news
    assert any(t.startswith("sector_peers(NVDA) → AVGO, MU, AMD") for t in s["trace"])


def test_sector_news_says_so_when_there_are_no_peers(db, monkeypatch):
    fake_feed(monkeypatch, {})
    set_peer_finder(lambda sym: None)
    llm_module.set_llm(MentionLLM(["news"], ["NVIDIA"]))
    s = ask("news from the same sector", db, [{"role": "user", "content": "news on nvidia"}])
    assert "found no news" in s["final_response"] and "industry" in s["final_response"] and s["agents"] == ["News"]


def test_price_of_an_unknown_name_asks_instead_of_researching(db):
    llm_module.set_llm(MentionLLM(["market"], ["foobarbaz"]))
    s = ask("what is the price of foobarbaz today?", db)
    m = s["agent_outputs"]["market"]
    assert m["status"] == "need_info" and "which company or ticker" in s["final_response"]
    assert not any("research" in t or "wiki" in t for t in s["trace"])


def test_a_concept_question_about_markets_still_goes_to_research(db):
    s = ask("how does the stock market work?", db)
    assert s["agent_outputs"]["market"]["status"] in ("not_found", "answered") and "price" not in s["agent_outputs"]["market"]["content"][:5]


def test_industry_peers_fall_back_to_bundled_sector_when_yahoo_fails(monkeypatch):
    set_peer_finder(None)
    monkeypatch.setattr(ms, "_yf_peers", lambda sym: (_ for _ in ()).throw(RuntimeError("offline")))
    info = ms.industry_peers("NVDA")
    assert info["sector"] == "Technology" and {p["symbol"] for p in info["peers"]} == {"AAPL", "MSFT"}
