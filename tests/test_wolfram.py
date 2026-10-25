"""Wolfram|Alpha client (src/core/wolfram.py) against a mocked transport, and response parsing. Its use by the Calculator
(closed forms for a plan's solve step) is tested in test_calc_plan.py. Nothing here reaches the real API."""
import httpx
import pytest

from src.core import wolfram as W

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


def test_parse_adds_the_decimal_approximation_to_an_exact_result():
    text = ("Query:\n\"(15000/10000)^(1/5) - 1\"\n\nInput:\n(15000/10000)^(1/5) - 1\n\nResult:\n(3/2)^(1/5) - 1\n\n"
            "Decimal approximation:\n0.084471771197698...\n\nWolfram|Alpha website result for \"x\":\n"
            "https://www.wolframalpha.com/input?i=x\n")
    assert W.parse(text)["result"] == "(3/2)^(1/5) - 1 ≈ 0.08447177..."

