"""The income-tax estimator (src/core/income_tax.py, 2026 rules in src/data/tax_rules.yaml) and the calculator's
income-tax path (src/workflow/tax_calc.py): the LLM only sorts the user's amounts, Python checks and computes."""
import json

import pytest

from src.core import income_tax as T
from src.core import llm as llm_module
from src.workflow import nodes as N
from src.workflow import tax_calc as TC

KEVIN = ("I earn 200000 a year\nProperty tax needs 10000\nPart time job earn 5000\nStock earning 30000\n"
         "How much tax i need to pay")
KEVIN_SORTED = {"items": [{"amount": 200000, "kind": "wages", "text": "I earn 200000 a year"},
                          {"amount": 10000, "kind": "property_tax", "text": "Property tax needs 10000"},
                          {"amount": 5000, "kind": "job_unspecified", "text": "Part time job earn 5000"},
                          {"amount": 30000, "kind": "stock_unspecified", "text": "Stock earning 30000"}],
                "filing_status": None, "year": None}


# ---------------------------------------------------------------- estimator (figures worked by hand from the 2026 tables)
def test_wages_long_term_gains_and_property_tax_single_2026():
    r = T.estimate(T.TaxInputs(wages=205_000, long_term_gains=30_000, property_tax=10_000))
    assert r["agi"] == 235_000 and r["standard"] == 16_100 and r["itemized"] == 10_000 and not r["itemizes"]
    assert r["taxable_income"] == 218_900 and r["ordinary_taxable"] == 188_900 and r["preferential_income"] == 30_000
    # 10% of 12,400 + 12% of 38,000 + 22% of 55,300 + 24% of 83,200
    assert r["ordinary_tax"] == pytest.approx(1_240 + 4_560 + 12_166 + 19_968)
    assert r["preferential_tax"] == pytest.approx(4_500)                 # 15% band
    assert r["niit"] == pytest.approx(0.038 * 30_000)                    # MAGI is 35,000 over $200k; NII 30,000 is less
    assert r["income_tax"] == pytest.approx(43_574)
    p = r["payroll"]
    assert p["social_security"] == pytest.approx(0.062 * 184_500) and p["medicare"] == pytest.approx(0.0145 * 205_000)
    assert p["additional_medicare"] == pytest.approx(0.009 * 5_000)
    assert r["total_federal"] == pytest.approx(43_574 + 11_439 + 2_972.5 + 45)
    assert r["marginal_rate"] == 0.24


def test_short_term_gains_are_ordinary_income():
    r = T.estimate(T.TaxInputs(wages=205_000, short_term_gains=30_000))
    # 218,900 all ordinary: up to 201,775 at 24%, the rest at 32%
    assert r["preferential_tax"] == 0 and r["ordinary_tax"] == pytest.approx(41_024 + 0.32 * (218_900 - 201_775))


def test_itemizing_wins_and_salt_is_capped():
    r = T.estimate(T.TaxInputs(wages=300_000, state_local_taxes=30_000, property_tax=15_000, mortgage_interest=12_000))
    assert r["salt_paid"] == 45_000 and r["salt_deduction"] == 40_400 and r["itemizes"] and r["deduction"] == 52_400


def test_salt_cap_phases_down_to_the_floor():
    r = T.estimate(T.TaxInputs(wages=700_000, property_tax=50_000))
    assert r["salt_cap"] == 10_000 and r["salt_deduction"] == 10_000          # 40,400 - 30% of 195,000 is below the floor
    r = T.estimate(T.TaxInputs(wages=525_000, property_tax=50_000))
    assert r["salt_cap"] == pytest.approx(40_400 - 0.3 * 20_000)


def test_married_joint_uses_wider_brackets():
    single = T.estimate(T.TaxInputs(wages=150_000))
    joint = T.estimate(T.TaxInputs(filing_status="married_joint", wages=150_000))
    assert joint["standard"] == 32_200 and joint["income_tax"] < single["income_tax"]
    assert joint["ordinary_tax"] == pytest.approx(2_480 + 0.12 * 76_000 + 0.22 * (117_800 - 100_800))


def test_capital_loss_offsets_ordinary_income_up_to_3000():
    r = T.estimate(T.TaxInputs(wages=80_000, short_term_gains=-10_000))
    assert r["capital_loss_deducted"] == -3_000 and r["agi"] == 77_000


def test_self_employment_tax_and_half_deduction():
    r = T.estimate(T.TaxInputs(self_employment=50_000))
    se = 50_000 * 0.9235 * 0.153
    assert r["payroll"]["self_employment_tax"] == pytest.approx(se) and r["agi"] == pytest.approx(50_000 - se / 2)


def test_unknown_year_or_status_is_refused():
    with pytest.raises(ValueError):
        T.estimate(T.TaxInputs(wages=1), year=1999)
    with pytest.raises(ValueError):
        T.estimate(T.TaxInputs(filing_status="head_of_household", wages=1))


# ---------------------------------------------------------------- reading the question
def test_income_tax_questions_are_recognised():
    assert TC.asks_income_tax(KEVIN)
    assert TC.asks_income_tax("I make $85k and got $2,000 in dividends, what will I owe in taxes?")
    assert not TC.asks_income_tax("How are long-term capital gains taxed?")           # no amounts: the tax agent explains
    assert not TC.asks_income_tax("how is my goal planning cost me on the tax?")


def test_amounts_skip_years_and_small_numbers():
    assert TC.amounts("In 2026 I earn $200k and 1,500 from a job, 3 kids, 7% rate") == [200_000, 1_500]


def test_kevins_case_is_read_with_stated_assumptions_and_alternatives():
    r, why = TC.read(KEVIN, KEVIN_SORTED)
    assert why == "" and r.inputs.wages == 205_000 and r.inputs.long_term_gains == 30_000 and r.inputs.property_tax == 10_000
    assert r.inputs.filing_status == "single" and len(r.assumed) == 3 and len(r.alternatives) == 2


def test_an_invented_or_dropped_amount_is_rejected():
    invented = {**KEVIN_SORTED, "items": [*KEVIN_SORTED["items"], {"amount": 12000, "kind": "charity"}]}
    assert TC.read(KEVIN, invented)[0] is None and "not an amount" in TC.read(KEVIN, invented)[1]
    dropped = {**KEVIN_SORTED, "items": KEVIN_SORTED["items"][:3]}
    assert TC.read(KEVIN, dropped)[0] is None and "left out 30,000" in TC.read(KEVIN, dropped)[1]


class SortingLLM:
    model = "scripted"

    def __init__(self, reply):
        self.reply = reply

    def invoke(self, messages):
        return type("R", (), {"content": json.dumps(self.reply)})()


def test_calculator_answers_kevins_case_from_the_rules():
    llm_module.set_llm(SortingLLM(KEVIN_SORTED))
    out = N.calc_node({"question": KEVIN, "history": [], "profile": {}}, {})["agent_outputs"]["calc"]
    text = out["content"]
    assert out["status"] == "answered" and out["verbatim"]
    assert "**Estimated 2026 federal taxes** (single)" in text
    assert "property tax does **not** lower your income tax" in text
    assert "**Federal income tax** | | **$43,574**" in text
    assert "about $58,031 in federal taxes" in text and "$68,031** in all" in text
    assert "short-term gains): federal taxes would be **$62,101**" in text
    assert "freelance (1099) work: federal taxes would be **$58,0" in text      # SE tax instead of FICA: about the same


def test_calculator_falls_back_when_the_sort_is_unusable():
    llm_module.set_llm(SortingLLM({"items": []}))
    text, note = TC.answer(KEVIN)
    assert text is None and "general calculator" in note


def test_tsx_typed_for_tax_may_be_proofread():
    typed = "Stock earning 30000\nHow much tsx i need to pay"
    assert N._proofread_ok(typed, "Stock earnings are $30,000. How much tax do I need to pay?")
    assert not N._proofread_ok("How is the TSX doing today?", "How is the tax doing today?")       # the index, in capitals


def test_income_tax_question_gets_the_calculator_too():
    s = {"question": KEVIN.replace("i need", "do I need")}
    assert N._with_income_tax_calc(["tax"], s) == ["tax", "calc"]
    assert N._with_income_tax_calc(["qa"], s) == ["tax", "calc"]
    assert N._with_income_tax_calc(["tax"], {"question": "How are capital gains taxed?"}) == ["tax"]
