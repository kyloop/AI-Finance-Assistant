"""Wolfram|Alpha as the Calculator's fallback (src/core/wolfram.py): the HTTP client against a mocked transport, response
parsing, and the Calculator agent's use of it (Wolfram supplies the formula, Python computes). Nothing here reaches the
real API."""
import httpx
import pytest
from langchain_core.messages import AIMessage

from src.core import llm as llm_module
from src.core import wolfram as W
from src.workflow.graph import run_chat

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate", "horizon_years": 10, "goals": []}

IRR_RESPONSE = """Query:
"IRR {-10000, 3000, 4000, 5000}"

Input interpretation:
internal rate of return | cash flows | {-10000, 3000, 4000, 5000}

Result:
8.896%

Wolfram|Alpha website result for "IRR {-10000, 3000, 4000, 5000}":
https://www.wolframalpha.com/input?i=IRR+%7B-10000%2C+3000%2C+4000%2C+5000%7D
"""


# ---------------------------------------------------------------- client
def test_parse_reads_the_result_interpretation_and_link():
    p = W.parse(IRR_RESPONSE)
    assert p["result"] == "8.896%" and p["interpretation"].startswith("internal rate of return")
    assert p["url"] == "https://www.wolframalpha.com/input?i=IRR+%7B-10000%2C+3000%2C+4000%2C+5000%7D"


def test_parse_falls_back_to_the_first_answer_section_without_a_result_heading():
    p = W.parse('Query:\n"solve x^2=4"\n\nInput:\nx^2 = 4\n\nSolutions:\nx = -2\nx = 2\n')
    assert p["result"] == "x = -2\nx = 2" and p["interpretation"] == "x^2 = 4"
    assert W.parse("Query:\n\"x\"\n\nPlot:\n(image)\n")["result"] == "(image)"


def transport(status: int, body: str = "", seen: list | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, text=body)
    return httpx.MockTransport(handle)


def test_ask_wolfram_sends_only_the_query_and_the_appid(monkeypatch):
    monkeypatch.setenv("WOLFRAM_APP_ID", "TEST-APPID")
    seen = []
    out = W.ask_wolfram("IRR {-10000, 3000, 4000, 5000}", transport=transport(200, IRR_RESPONSE, seen))
    assert out["result"] == "8.896%"
    params = dict(seen[0].url.params)
    assert seen[0].url.host == "www.wolframalpha.com" and seen[0].url.path == "/api/v1/llm-api"
    assert params == {"input": "IRR {-10000, 3000, 4000, 5000}", "appid": "TEST-APPID", "maxchars": "2000"}


@pytest.mark.parametrize("status,error", [(501, W.WolframNoResult), (403, W.WolframUnavailable), (500, W.WolframUnavailable)])
def test_ask_wolfram_maps_http_errors(monkeypatch, status, error):
    monkeypatch.setenv("WOLFRAM_APP_ID", "TEST-APPID")
    with pytest.raises(error):
        W.ask_wolfram("IRR {1}", transport=transport(status, "Wolfram|Alpha did not understand your input"))


def test_ask_wolfram_reports_a_network_failure_as_unavailable(monkeypatch):
    monkeypatch.setenv("WOLFRAM_APP_ID", "TEST-APPID")
    def down(request):
        raise httpx.ConnectError("no route", request=request)
    with pytest.raises(W.WolframUnavailable, match="ConnectError"):
        W.ask_wolfram("IRR {1}", transport=httpx.MockTransport(down))


def test_a_reply_without_any_answer_counts_as_no_result():
    W.set_wolfram_client(lambda q: 'Query:\n"x"\n')
    with pytest.raises(W.WolframNoResult):
        W.ask_wolfram("x")


def test_wolfram_is_off_without_an_appid_or_a_client(monkeypatch):
    assert not W.wolfram_enabled()                                   # conftest removes WOLFRAM_APP_ID
    monkeypatch.setenv("WOLFRAM_APP_ID", "TEST-APPID")
    assert W.wolfram_enabled()


def test_the_appid_can_also_be_named_wolfram_alpha_app_id(monkeypatch):
    monkeypatch.setenv("WOLFRAM_ALPHA_APP_ID", "TEST-APPID")
    assert W.wolfram_enabled() and W._app_id() == "TEST-APPID"


# ---------------------------------------------------------------- the Calculator using it
class CalcLLM:
    """Routes to calc and replies to the Calculator's extraction prompt with a scripted JSON."""
    model = "calc"

    def __init__(self, calc_reply: str):
        self.calc_reply = calc_reply

    def invoke(self, messages):
        system, user = messages[0][1], messages[1][1]
        if "You are the router" in system:
            return AIMessage(content='{"intents": ["calc"], "confidence": 0.9}')
        if "You are the proofreader" in system:
            return AIMessage(content=user.removeprefix("Message: "))
        if "finance calculator" in system:
            return AIMessage(content=self.calc_reply)
        return AIMessage(content="{}")


RATE_RESPONSE = """Query:
"solve p*(1+r)^n = f for r"

Input interpretation:
solve p (1 + r)^n = f for r

Result:
r = (f/p)^(1/n) - 1

Wolfram|Alpha website result for "solve p*(1+r)^n = f for r":
https://www.wolframalpha.com/input?i=solve+p%2A%281%2Br%29%5En+%3D+f+for+r
"""


@pytest.fixture
def wolfram_calls():
    """A fake Wolfram|Alpha that records each query and answers with the symbolic formula for r."""
    calls = []
    def fake(query):
        calls.append(query)
        return RATE_RESPONSE
    W.set_wolfram_client(fake)
    return calls


RATE_Q = "If I invest $10,000 and want $15,000 in 5 years, what yearly return do I need?"
RATE_REPLY = ('{"function": null, "equation": "p*(1+r)^n = f", "values": {"p": 10000, "f": 15000, "n": 5}, '
              '"solve_for": "r", "unit": "percent", "label": "yearly return needed"}')
IRR_Q = "What's the IRR if I invest $10,000 and get back $3,000, $4,000 and $5,000 over three years?"
IRR_REPLY = ('{"function": null, "equation": "a + b/(1+r) + c/(1+r)^2 + d/(1+r)^3 = 0", "values": {"a": -10000, '
             '"b": 3000, "c": 4000, "d": 5000}, "solve_for": "r", "unit": "percent", "label": "internal rate of return"}')


def ask(q, calc_reply):
    llm_module.set_llm(CalcLLM(calc_reply))
    return run_chat(q, history=[], profile=PROFILE, holdings=[], db=None)


def test_wolfram_gets_only_the_symbolic_equation_and_python_computes_the_result(wolfram_calls):
    s = ask(RATE_Q, RATE_REPLY)
    assert wolfram_calls == ["solve p*(1+r)^n = f for r"]                   # no numbers, never the user's message
    out = s["agent_outputs"]["calc"]
    assert out["verbatim"] and out["status"] == "answered"
    assert "**Result: r ≈ 8.45%**" in out["content"]                        # (15000/10000)^(1/5) - 1, computed in Python
    assert "Formula (from Wolfram|Alpha): `r = (f/p)^(1/n) - 1`" in out["content"]
    assert "Values: p = 10,000; f = 15,000; n = 5" in out["content"]
    assert s["sources"] == [{"id": "wolfram:solve p*(1+r)^n = f for r", "title": "Wolfram|Alpha",
                             "url": "https://www.wolframalpha.com/input?i=solve+p%2A%281%2Br%29%5En+%3D+f+for+r"}]
    assert any("→ formula: r = 0.0844718" in t for t in s["trace"])


def test_a_wrong_formula_from_wolfram_is_rejected_and_the_equation_solved_numerically():
    W.set_wolfram_client(lambda q: RATE_RESPONSE.replace("r = (f/p)^(1/n) - 1", "r = f/p - 1"))
    s = ask(RATE_Q, RATE_REPLY)
    out = s["agent_outputs"]["calc"]
    assert "**Result: r ≈ 8.45%**" in out["content"] and "found numerically" in out["content"]
    assert s["sources"] == []                                               # Wolfram's answer wasn't used


def test_without_a_closed_form_the_irr_is_solved_numerically(wolfram_calls):
    s = ask(IRR_Q, IRR_REPLY)
    out = s["agent_outputs"]["calc"]
    assert wolfram_calls == ["solve a + b/(1+r) + c/(1+r)^2 + d/(1+r)^3 = 0 for r"]
    assert out["status"] == "answered" and "**Result: r ≈ 8.90%**" in out["content"]


def test_our_own_calculators_still_come_first(wolfram_calls):
    s = ask("How much will $10,000 grow to at 6% a year over 10 years?",
            '{"function": "future_value", "args": {"annual_rate": 6, "years": 10, "principal": 10000}}')
    assert wolfram_calls == [] and "**Result: about $17,908.48**" in s["final_response"]


def test_missing_numbers_are_asked_for_not_sent_to_wolfram(wolfram_calls):
    s = ask("What's the IRR of my rental property?", '{"function": null, "missing": "the cash flows"}')
    assert wolfram_calls == [] and s["agent_outputs"]["calc"]["status"] == "need_info"


@pytest.mark.parametrize("reply,why", [
    (IRR_REPLY.replace('"d": 5000', '"d": 6000'), "numbers not in the conversation: 6000"),
    (RATE_REPLY.replace('p*(1+r)^n = f', 'p*(1+r)^n = 16000'), "numbers not in the conversation: 16000"),
    (RATE_REPLY.replace('"solve_for": "r"', '"solve_for": "x"'), "unknown 'x' not in the equation"),
])
def test_an_equation_with_invented_numbers_or_no_unknown_is_rejected(wolfram_calls, reply, why):
    s = ask(IRR_Q if '"a"' in reply else RATE_Q, reply)
    assert wolfram_calls == [] and s["agent_outputs"]["calc"]["status"] == "need_info"
    assert any(f"equation rejected ({why})" in t for t in s["trace"])


def test_an_equation_missing_values_asks_for_exactly_those_before_calling_wolfram(wolfram_calls):
    reply = ('{"function": null, "equation": "p*(1+r)^n = f", "values": {}, "variables": {"p": "starting amount", '
             '"f": "target amount", "n": "number of years"}, "solve_for": "r", "unit": "percent", "label": "yearly return needed"}')
    s = ask("What annual return do I need to reach my target?", reply)
    out = s["agent_outputs"]["calc"]
    assert wolfram_calls == [] and out["status"] == "need_info"
    assert out["content"].startswith("I can work out the yearly return needed: it's `r` in `p*(1+r)^n = f`. I still need:")
    assert "- starting amount (`p`)\n- number of years (`n`)\n- target amount (`f`)" in out["content"]
    assert any("equation 'p*(1+r)^n = f' needs p, n, f → ask" in t for t in s["trace"])


def test_values_already_given_are_kept_and_only_the_rest_asked_for(wolfram_calls):
    s = ask("I have $10,000. What yearly return do I need to reach my target in 5 years?", RATE_REPLY.replace(', "f": 15000', ''))
    out = s["agent_outputs"]["calc"]
    assert wolfram_calls == [] and "- `f`" in out["content"] and "Already have: p = 10,000; n = 5" in out["content"]


@pytest.mark.parametrize("error,note", [(W.WolframNoResult("q"), "no result"), (W.WolframUnavailable("ReadTimeout"), "failed (ReadTimeout)")])
def test_no_result_or_an_outage_still_solves_numerically(error, note):
    def fake(query):
        raise error
    W.set_wolfram_client(fake)
    s = ask(RATE_Q, RATE_REPLY)
    assert "**Result: r ≈ 8.45%**" in s["agent_outputs"]["calc"]["content"]
    assert any(f"→ {note} → solved numerically" in t for t in s["trace"])


def test_without_an_appid_the_equation_is_solved_numerically_and_nothing_is_sent():
    s = ask(RATE_Q, RATE_REPLY)                                             # no client injected, no key
    assert "**Result: r ≈ 8.45%**" in s["agent_outputs"]["calc"]["content"]
    assert any("no Wolfram|Alpha → solved numerically" in t for t in s["trace"])


def test_parse_adds_the_decimal_approximation_to_an_exact_result():
    text = ("Query:\n\"(15000/10000)^(1/5) - 1\"\n\nInput:\n(15000/10000)^(1/5) - 1\n\nResult:\n(3/2)^(1/5) - 1\n\n"
            "Decimal approximation:\n0.084471771197698...\n\nWolfram|Alpha website result for \"x\":\n"
            "https://www.wolframalpha.com/input?i=x\n")
    assert W.parse(text)["result"] == "(3/2)^(1/5) - 1 ≈ 0.08447177..."
