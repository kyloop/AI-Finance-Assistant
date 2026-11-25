"""The tax eval's cases parse and its check reads a reply the way the report needs (the eval itself needs a real LLM)."""
import yaml

from scripts import eval_tax as E
from src.workflow import tax_calc as TC


def test_every_case_has_one_expectation_per_message():
    cases = yaml.safe_load(open(E.CASES))
    assert len(cases) == 40 and len({c["id"] for c in cases}) == 40
    assert sum(len(c["messages"]) > 1 for c in cases) == 28
    for c in cases:
        assert len(c["expect"]) == len(c["messages"]), c["id"]


def test_the_check_compares_status_figures_totals_and_the_question():
    prof = {"filing_status": "single", "items": [{"amount": 85000, "kind": "wages"}], "household": {},
            "income_tax": 8070.0, "total_federal": 14572.5}
    state = {"agents": ["Tax Education"], "context": {"tax": prof}, "choices": TC.QUESTIONS["dependent"][1],
             "final_response": "Estimated 2026 federal taxes"}
    want = {"tax_only": True, "filing_status": "single", "figures": {85000: "wages"}, "income_tax": [8070, 7570],
            "total_federal": 14572.5, "asks": ["dependent", "none"], "contains": ["Estimated 2026"]}
    assert E.check_turn(state, want) == []
    wrong = {**want, "filing_status": "married_joint", "total_federal": 1.0, "asks": "status"}
    problems = E.check_turn(state, wrong)
    assert len(problems) == 3 and any("filing status" in p for p in problems)
