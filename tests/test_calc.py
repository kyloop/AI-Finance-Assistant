"""Calculator agent and follow-up suggestions."""
import pytest

from src.core import calculators as C
from src.core import llm as llm_module
from src.workflow import calc as CALC
from src.workflow import router as R
from src.workflow.graph import run_chat

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate"}
GROWTH_Q = "If I invest $10,000 at 6% a year for 10 years, how much will I have?"


def ask(q):
    return run_chat(q, history=[], profile=PROFILE, holdings=[], db=None)


class RoleLLM:
    """Replies by role (recognised from the system prompt) and records the roles used."""
    model = "role"

    def __init__(self, **replies):
        self.replies = {"router": '{"intents": ["calc"], "confidence": 0.9}',
                        "calc": '{"function": "loan_payment", "args": {"principal": 300000, "annual_rate": 6.5, "years": 30}}',
                        "followups": '{"calculation": "How much would $5,000 grow to at 5% over 20 years?", '
                                     '"example": "What would a $250,000 mortgage at 7% cost each month?", '
                                     '"related": "What is the difference between APR and APY?"}',
                        "example": '{"function": null}', "check": '{"answers": true}', "synth": "Prose answer.", **replies}
        self.calls, self.prompts = [], {}

    def invoke(self, messages):
        system = messages[0][1]
        if "You are the proofreader" in system:                  # the proofread node: message unchanged, not counted as a call
            return type("R", (), {"content": messages[1][1].removeprefix("Message: ")})()
        role = ("router" if "You are the router" in system else "calc" if "finance calculator" in system else
                "example" if "conceptual answer" in system else "followups" if "could ask next" in system else
                "check" if "retrieved SOURCES" in system else "synth")
        self.calls.append(role)
        self.prompts.setdefault(role, messages[1][1])
        return type("R", (), {"content": self.replies[role]})()


# ------------------------------------------------------------------ maths (known values)
def test_calculators_match_known_values():
    assert C.future_value(6, 10, principal=10_000)["future_value"] == 17_908.48               # 10,000 × 1.06^10
    assert C.present_value(10_000, 5, 10)["present_value"] == 6_139.13                         # 10,000 ÷ 1.05^10
    assert C.loan_payment(300_000, 6.5, 30)["monthly_payment"] == 1_896.20                     # standard amortisation
    assert C.doubling_time(6) == {"rule_of_72": 12.0, "exact": 11.9}
    assert C.apy_from_apr(4.65, 12)["apy"] == 4.75                                             # Wikipedia's APY example
    assert C.real_return(7, 3)["real_rate"] == 3.883
    assert C.bond_current_yield(50, 950)["current_yield"] == 5.263
    assert C.purchasing_power(1_000, 3, 10) == {"real_value": 744.09, "future_cost": 1343.92, "lost_pct": 25.6}   # 1,000 ÷ 1.03^10
    fv = C.future_value(6, 10, principal=10_000, monthly_contribution=200)
    assert fv["contributed"] == 34_000 and fv["compounds_per_year"] == 12


@pytest.mark.parametrize("call", [lambda: C.future_value(600, 10, principal=1), lambda: C.loan_payment(-5, 5, 10),
                                  lambda: C.future_value(5, 10), lambda: C.doubling_time(0)])
def test_calculators_reject_nonsense_inputs(call):
    with pytest.raises(ValueError):
        call()


def test_keyword_extraction_separates_lump_sums_from_monthly_amounts():
    assert CALC.keyword_request("I add $200 a month at 7% for 30 years") == \
        ("future_value", {"annual_rate": 7.0, "years": 30.0, "principal": 0.0, "monthly_contribution": 200.0})
    assert CALC.keyword_request("How long to double my money at 8%?") == ("doubling_time", {"annual_rate": 8.0})
    assert CALC.keyword_request("Tell me about bonds") == (None, {})


# ------------------------------------------------------------------ through the graph
def test_growth_question_goes_to_the_calculator_not_goal_planning():
    assert R.classify(GROWTH_Q) == ["calc"]
    s = ask(GROWTH_Q)                                                            # no LLM: keyword extraction
    assert s["agents"] == ["Calculator"] and "**Result: about $17,908.48**" in s["final_response"]
    assert "calc (keywords): future_value(annual_rate=6, years=10, principal=10000)" in s["trace"]


def test_llm_extracted_calculation_is_shown_verbatim():
    llm = RoleLLM()
    llm_module.set_llm(llm)
    s = ask("What's the monthly payment on a $300,000 mortgage at 6.5% over 30 years?")
    assert "**Result: about $1,896.20 a month.**" in s["final_response"]
    assert "synth" not in llm.calls                                              # the result is never reworded
    assert s["choices"] == ["How much would $5,000 grow to at 5% over 20 years?",
                            "What would a $250,000 mortgage at 7% cost each month?", "What is the difference between APR and APY?"]


def test_missing_numbers_ask_with_example_choices():
    llm_module.set_llm(RoleLLM(calc='{"function": null, "missing": "the interest rate"}'))
    s = ask("Can you calculate how much my savings will grow?")
    assert s["final_response"].startswith(CALC.ASK) and s["choices"] == CALC.CHOICES
    assert not any(t.startswith("follow-ups") and "suggested" in t for t in s["trace"])   # the ask's own choices are kept


def test_follow_ups_follow_a_prose_answer_and_keep_only_questions_in_the_users_words():
    llm_module.set_llm(RoleLLM(router='{"intents": ["goal"], "confidence": 0.9}',
                               followups='{"calculation": "What would your savings be worth?", '
                                         '"example": "Saving $500 a month adds up to a lot.", '
                                         '"related": "How does compound interest work?"}'))
    s = ask("I want to retire with $1,000,000 in 30 years, saving $500 a month")
    assert s["choices"] == ["How does compound interest work?"]
    assert "follow-ups: 1 suggested" in s["trace"]


def test_user_voice_filter_allows_asking_the_assistant():
    from src.workflow.nodes import _ADDRESSES_USER
    assert not _ADDRESSES_USER.search("Can you give an example of compound interest in a savings account?")
    assert _ADDRESSES_USER.search("What is your savings goal?") and _ADDRESSES_USER.search("How long do you want to save?")


# ------------------------------------------------------------------ worked examples in conceptual answers
def _kb_answer(monkeypatch_target=None):
    from src.core.config import get_config
    from src.workflow.tools import set_kb_searcher
    hit = {"score": get_config()["rag"]["min_score"] + 0.1, "doc_id": "compound-interest", "doc_title": "Compound interest",
           "section": "(lead)", "text": "Compound interest is interest on interest.", "category": "basics",
           "source_url": "https://en.wikipedia.org/wiki/Compound_interest", "piece": 0, "pieces": 1, "tokens": 9, "section_tokens": 9}
    set_kb_searcher(lambda q, k=None: [hit])


def test_conceptual_answer_gets_an_exact_worked_example():
    _kb_answer()
    llm = RoleLLM(router='{"intents": ["qa"], "confidence": 0.9}',
                  example='{"function": "future_value", "args": {"annual_rate": 6, "years": 10, "principal": 10000}}')
    llm_module.set_llm(llm)
    s = ask("What is compound interest?")
    text = s["final_response"]
    assert text.startswith("Prose answer.") and CALC.EXAMPLE_HEADING in text and "**Result: about $17,908.48**" in text
    assert s["agents"] == ["Finance Q&A", "Calculator"]
    assert "worked calculation is shown separately" in llm.prompts["synth"]       # the writer won't claim it's missing
    assert "illustrate: future_value(annual_rate=6, years=10, principal=10000)" in s["trace"]


def test_no_example_when_no_calculation_fits():
    _kb_answer()
    llm_module.set_llm(RoleLLM(router='{"intents": ["qa"], "confidence": 0.9}'))       # example → {"function": null}
    s = ask("What is a green bond?")
    assert CALC.EXAMPLE_HEADING not in s["final_response"] and "illustrate: no calculation fits this topic" in s["trace"]


def test_calculation_questions_are_not_illustrated_twice():
    llm = RoleLLM()
    llm_module.set_llm(llm)
    ask("What's the monthly payment on a $300,000 mortgage at 6.5% over 30 years?")
    assert "example" not in llm.calls


def test_llm_json_is_read_despite_extra_braces_and_text():
    from src.workflow.nodes import _json
    assert _json('{"function": "apy_from_apr", "args": {"apr": 4.65, "compounds_per_year": 12}}}') == \
        {"function": "apy_from_apr", "args": {"apr": 4.65, "compounds_per_year": 12}}
    assert _json('Sure! {"answers": true} Hope that helps.') == {"answers": True}
    assert _json("no json here") is None and _json(None) is None


def test_percent_change_applies_a_rise_or_fall_to_an_amount():
    text = CALC.run("percent_change", {"amount": 94.71, "percent": 2})
    assert "**Result: about $96.60**, up $1.89." in text
    assert "down $9.47" in CALC.run("percent_change", {"amount": 94.71, "percent": -10})
