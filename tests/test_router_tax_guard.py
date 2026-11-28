"""The router LLM's "tax" for a question with no tax in it (chain eval, Nov 2026) goes to the calculator or Q&A."""
import pytest

from src.core import llm as llm_module
from src.workflow.nodes import _route
from tests.test_verifier import ScriptedLLM


@pytest.mark.parametrize("q,want", [
    ("I have $12,000 to invest: 60% in stocks, 30% in bonds and 10% in cash. How much goes into each?", ["calc"]),
    ("I earn $60,000 a year and get a 3% raise every year. What will my salary be in 10 years?", ["calc"]),
    ("What does diversification mean?", ["qa"]),
    ("How much tax do I pay on $60,000 of wages?", ["tax"]),
    ("My child starts college in 12 years; tuition is $40,000 a year. What is it worth today at 6%?", ["tax"]),
])
def test_tax_only_for_a_tax_question(q, want):
    llm_module.set_llm(ScriptedLLM(router='{"intents": ["tax"], "confidence": 0.9}'))
    assert _route({"question": q, "original_question": q, "history": []})["intent"] == want


@pytest.mark.parametrize("q,want", [
    ("I need $15,000 for a new roof in 6 years. If my savings earn 3% a year compounded monthly, how much should I save each month?", ["calc"]),
    ("I want to save $50,000 for a house in 5 years. How much should I save each month?", ["goal"]),   # no rate: the goal agent
])
def test_a_savings_goal_with_its_own_rate_goes_to_the_calculator(q, want):
    llm_module.set_llm(ScriptedLLM(router='{"intents": ["goal"], "confidence": 0.9}'))
    assert _route({"question": q, "original_question": q, "history": []})["intent"] == want
