"""Tavily web search as Research's last resort (src/core/tavily.py): the HTTP client against a mocked transport, result
filtering, and where it runs in the graph (after Wikipedia, checked by the verifier). Nothing here reaches the real API."""
import json

import httpx
import pytest
from langchain_core.messages import AIMessage

from src.core import llm as llm_module
from src.core import tavily as T
from src.workflow.graph import run_chat

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate", "horizon_years": 10, "goals": []}

RESULTS = [
    {"title": "What Is a Flibbertigibbet Fund?", "url": "https://www.investopedia.com/terms/f/flibbertigibbet-fund.asp",
     "content": "A flibbertigibbet fund is an imaginary fund used in examples. It changes strategy often.", "score": 0.91},
    {"title": "Flibbertigibbet funds explained", "url": "https://www.morningstar.com/articles/flibbertigibbet",
     "content": "Morningstar explains why frequent strategy changes raise costs.", "score": 0.74},
    {"title": "r/investing: anyone own a flibbertigibbet fund?", "url": "https://old.reddit.com/r/investing/abc",
     "content": "lol no", "score": 0.88},
    {"title": "Unrelated page", "url": "https://example.com/x", "content": "Something else entirely.", "score": 0.1},
    {"title": "No text", "url": "https://example.org/empty", "content": "", "score": 0.9},
]


# ---------------------------------------------------------------- client
def transport(status: int, payload=None, seen: list | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload if payload is not None else {})
    return httpx.MockTransport(handle)


def test_search_sends_only_the_query_with_the_key_as_bearer_token(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TEST")
    seen = []
    out = T.web_search("What is a flibbertigibbet fund?", transport=transport(200, {"results": RESULTS}, seen))
    req = seen[0]
    body = json.loads(req.content)
    assert req.method == "POST" and str(req.url) == "https://api.tavily.com/search"
    assert req.headers["Authorization"] == "Bearer tvly-TEST"
    assert body["query"] == "What is a flibbertigibbet fund?" and body["include_answer"] is False
    assert body["include_raw_content"] is False and "reddit.com" in body["exclude_domains"]
    assert [r["domain"] for r in out] == ["investopedia.com", "morningstar.com"]


def test_results_are_filtered_and_ranked():
    T.set_web_searcher(lambda q: RESULTS)
    out = T.web_search("flibbertigibbet")
    assert [r["domain"] for r in out] == ["investopedia.com", "morningstar.com"]   # low score, excluded domain, empty text dropped
    assert out[0]["title"] == "What Is a Flibbertigibbet Fund?" and out[0]["score"] == 0.91


def test_a_long_query_is_cut_to_the_api_limit():
    seen = []
    T.set_web_searcher(lambda q: seen.append(q) or [])
    T.web_search("word " * 200)
    assert len(seen[0]) <= T.MAX_QUERY_CHARS


@pytest.mark.parametrize("status,message", [(401, "API key rejected"), (429, "limit"), (432, "limit"), (500, "HTTP 500")])
def test_http_errors_become_unavailable(monkeypatch, status, message):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TEST")
    with pytest.raises(T.WebSearchUnavailable, match=message):
        T.web_search("x", transport=transport(status))


def test_a_network_failure_becomes_unavailable(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TEST")
    def down(request):
        raise httpx.ReadTimeout("slow", request=request)
    with pytest.raises(T.WebSearchUnavailable, match="ReadTimeout"):
        T.web_search("x", transport=httpx.MockTransport(down))


def test_web_search_is_off_without_a_key_or_a_searcher(monkeypatch):
    assert not T.web_search_enabled()                                # conftest removes TAVILY_API_KEY
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TEST")
    assert T.web_search_enabled()


# ---------------------------------------------------------------- in the graph
UNKNOWN = "What is a flibbertigibbet fund?"        # the fake Wikipedia has no article on it


def ask(q):
    return run_chat(q, history=[], profile=PROFILE, holdings=[], db=None)


def test_when_wikipedia_has_nothing_the_web_answers_with_cited_sources():
    queries = []
    T.set_web_searcher(lambda q: queries.append(q) or RESULTS)
    s = ask(UNKNOWN)
    assert queries == [UNKNOWN]                                       # the question only: no history, profile or portfolio
    assert "imaginary fund used in examples" in s["final_response"]
    assert [x["url"] for x in s["sources"]] == ["https://www.investopedia.com/terms/f/flibbertigibbet-fund.asp",
                                                "https://www.morningstar.com/articles/flibbertigibbet"]
    assert s["sources"][0]["title"] == "What Is a Flibbertigibbet Fund? (investopedia.com)"
    trace = " | ".join(s["trace"])
    assert trace.index("wiki_search") < trace.index("web_search → 2 results, using investopedia.com, morningstar.com")


def test_without_a_key_research_stops_at_wikipedia_as_before():
    s = ask(UNKNOWN)
    assert "rather not guess" in s["final_response"] and not any("web_search" in t for t in s["trace"])


def test_no_web_results_still_says_it_wont_guess():
    T.set_web_searcher(lambda q: [])
    s = ask(UNKNOWN)
    assert "rather not guess" in s["final_response"] and "web_search → no relevant results" in s["trace"]


def test_a_web_outage_is_traced_and_the_answer_still_says_it_wont_guess():
    def down(q):
        raise T.WebSearchUnavailable("rate or plan limit reached")
    T.set_web_searcher(down)
    s = ask(UNKNOWN)
    assert "rather not guess" in s["final_response"] and "web_search → failed (rate or plan limit reached)" in s["trace"]


def test_the_web_is_not_searched_when_wikipedia_answers():
    queries = []
    T.set_web_searcher(lambda q: queries.append(q) or RESULTS)
    s = ask("What is an ETF?")                    # the knowledge base is empty, Wikipedia has the article
    assert queries == [] and "Exchange-traded fund" in s["final_response"]


class CheckLLM:
    """Routes to qa, names the Wikipedia article, and gives scripted sufficiency verdicts (in order) for what research found."""
    model = "check"

    def __init__(self, verdicts):
        self.verdicts, self.checked = list(verdicts), []

    def invoke(self, messages):
        system, user = messages[0][1], messages[1][1]
        if "You are the router" in system:
            reply = '{"intents": ["qa"], "confidence": 0.9}'
        elif "You are the proofreader" in system:
            reply = user.removeprefix("Message: ")
        elif "retrieved SOURCES" in system:
            self.checked.append("web" if "investopedia.com" in user else "wikipedia")
            reply = self.verdicts.pop(0)
        elif "Wikipedia articles" in system:
            reply = '{"topics": ["Exchange-traded fund"]}'
        elif "coordinate the specialist agents" in system:
            reply = '{"intents": [], "reason": "none can help"}'
        else:
            reply = "Answer written from the context."
        return AIMessage(content=reply)


def test_the_verifier_checks_web_results_like_wikipedia_ones():
    T.set_web_searcher(lambda q: RESULTS)
    llm = CheckLLM(['{"answers": false, "missing": "what the fund holds"}', '{"answers": true}'])
    llm_module.set_llm(llm)
    s = ask("What does an ETF hold, exactly?")
    assert llm.checked == ["wikipedia", "web"]                        # Wikipedia rejected, so the web is tried and checked
    assert s["sources"][0]["url"].startswith("https://www.investopedia.com/")


def test_a_rejected_web_result_is_dropped_and_the_wikipedia_fallback_kept():
    T.set_web_searcher(lambda q: RESULTS)
    llm_module.set_llm(CheckLLM(['{"answers": false}', '{"answers": false}']))
    s = ask("What does an ETF hold, exactly?")
    assert "verifier: qa web sources don't answer the question either" in s["trace"]
    assert all("wikipedia.org" in x["url"] for x in s["sources"])     # unchecked web pages never become the fallback
