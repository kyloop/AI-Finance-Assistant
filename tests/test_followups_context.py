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
from src.workflow.nodes import _own_subject, _proofread_ok, _sector_lines, _with_sector_figures, drop_unknown_headlines
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


class CrowdedLLM(MentionLLM):
    """The company prompt finds `mentions` in the message alone, but nothing once the earlier conversation is included."""
    def invoke(self, messages):
        if "publicly traded companies" in messages[0][1] and "Recent conversation:" in messages[1][1]:
            self.prompts.append(messages[1][1])
            return type("R", (), {"content": json.dumps({"companies": []})})()
        return super().invoke(messages)


def test_a_company_the_conversation_crowded_out_is_found_in_the_message_alone():
    """"can you show Google news?" after a run of Apple answers: with the conversation the model named nothing, so the news
    agent showed the market feed; the message read on its own names Google."""
    google = {"symbol": "GOOGL", "name": "Alphabet Inc."}
    set_symbol_resolver(lambda name: google if name.lower() == "google" else None)
    fake = CrowdedLLM(["news"], ["Google"])
    llm_module.set_llm(fake)
    hist = [{"role": "user", "content": "news for appl"}, {"role": "assistant", "content": "Here are the latest headlines for Apple."}]
    assert [r["symbol"] for r in SYM.resolve("can you show Google news?", history=hist)] == ["GOOGL"]
    assert len(fake.prompts) == 2 and "Recent conversation:" not in fake.prompts[1]
    fake.prompts.clear()
    assert SYM.resolve("and what about its earnings?", history=hist) == []           # points back: the empty answer stands
    assert len(fake.prompts) == 1


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


TECH_NEWS = "What's the latest technology sector news?"
EARLIER_ANSWER = [{"role": "user", "content": "what about take two software doing?"},
                  {"role": "assistant", "content": "Take-Two (TTWO): the Communication Services sector fell 9.1% against 1.1% for the S&P 500."}]


class ReadsEarlierAnswer:
    """Takes the subjects from the conversation when it is given one; on the message alone, finds what `alone` says."""
    def __init__(self, alone):
        self.alone = alone

    def invoke(self, messages):
        with_history = "Recent conversation" in messages[1][1]
        reply = json.dumps({"companies": ["Take-Two Interactive Software"] if with_history else [],
                            "markets": ["Communication Services Sector", "S&P 500"] if with_history else self.alone,
                            "topic": "technology sector news", "excluded": []})
        return type("R", (), {"content": reply})()


@pytest.mark.parametrize("alone", [["technology sector"], []])
def test_a_named_sector_is_not_replaced_by_the_subjects_of_the_answer_before(alone):
    """Read again on its own the message gives its sector; if the model misses it even then, the market directory finds it."""
    SYM.clear_cache()
    llm_module.set_llm(ReadsEarlierAnswer(alone))
    got = SYM.subjects(TECH_NEWS, history=EARLIER_ANSWER)
    assert [m["key"] for m in got["markets"]] == ["XLK"] and got["companies"] == [] and got["levels"] == ["sector"]


def test_a_sector_named_in_a_message_that_points_back_is_kept_with_the_earlier_subject():
    SYM.clear_cache()
    llm_module.set_llm(ReadsEarlierAnswer([]))
    got = SYM.subjects("how does it compare to the tech sector?", history=EARLIER_ANSWER)
    assert [m["key"] for m in got["markets"]][0] == "XLK"


def test_a_subject_the_conversation_supplies_is_kept_when_the_message_alone_finds_none():
    SYM.clear_cache()
    set_symbol_resolver(lambda name: {"symbol": "TTWO", "name": name})
    llm_module.set_llm(ReadsEarlierAnswer([]))
    assert [c["symbol"] for c in SYM.subjects("grab the recent news", history=EARLIER_ANSWER)["companies"]] == ["TTWO"]


def test_proofread_cannot_swap_the_sector_a_message_names_for_an_earlier_subject():
    assert not _proofread_ok(TECH_NEWS, "What is the latest news related to the Pentagon?", {}, "user: any news related to Pentagon?")
    assert _proofread_ok(TECH_NEWS, "What is the latest technology sector news?", {}, "")


def test_a_message_naming_its_own_market_is_not_a_follow_up_unless_it_points_back():
    assert _own_subject(TECH_NEWS)
    assert not _own_subject("what about the tech sector?") and not _own_subject("and gold too?")


def test_a_headline_copied_from_an_earlier_answer_is_dropped_however_it_is_written():
    mine = {"title": "Technology Tops Sector Charts Ahead of Earnings (MT Newswires)"}
    reply = ("- **Why Merck Stock Flew Higher on Friday** - Motley Fool (Oct 31): results.\n"
             "- **Technology Tops Sector Charts Ahead of Earnings** - MT Newswires (Oct 27): tech rose.")
    assert drop_unknown_headlines(reply, [mine]).startswith("- **Technology Tops") and "Merck" not in drop_unknown_headlines(reply, [mine])


def test_sector_news_also_runs_the_market_agent():
    e = {"levels": ["sector"]}
    assert _with_sector_figures({"intent": ["news"], "entities": e, "trace": []})["intent"] == ["news", "market"]
    assert _with_sector_figures({"intent": ["news"], "entities": {"levels": ["company"]}, "trace": []})["intent"] == ["news"]
    both = _with_sector_figures({"intent": ["market", "news"], "entities": {"levels": ["sector"]}, "trace": []})
    assert both["intent"] == ["market", "news"] and both["entities"]["sector_figures"]


def test_sector_figures_are_shown_word_for_word_only_for_sector_news():
    sector = {"name": "Technology sector", "fund": "XLK", "label": "last month", "return": -0.092, "start_date": "2026-10-01",
              "end_date": "2026-10-30", "benchmark": {"name": "S&P 500", "return": -0.011}, "top": [], "top_of": "sector"}
    data = {"XLK": {"sector": sector}, "AAPL": {"quote": {}}}
    assert "Technology sector" in _sector_lines({"entities": {"sector_figures": True}, "market_data": data})
    assert _sector_lines({"entities": {}, "market_data": data}) == ""
