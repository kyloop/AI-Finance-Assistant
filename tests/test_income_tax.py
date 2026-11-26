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
        T.estimate(T.TaxInputs(filing_status="qualifying_widow", wages=1))


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
    assert r.inputs.filing_status == "single" and len(r.assumed) == 3 and [a[0] for a in r.alternatives] == ["status", "job", "stock"]


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


def test_tax_agent_answers_kevins_case_step_by_step_from_the_rules():
    llm_module.set_llm(SortingLLM(KEVIN_SORTED))
    s = {"question": KEVIN, "history": [], "profile": {}, "entities": {"wiki_query": KEVIN}}
    out = N.tax_node(s, {})["agent_outputs"]["tax"]
    text = out["content"]
    assert out["status"] == "answered" and out["verbatim"] and out["explains_itself"] and out["origin"] == "tax_tools"
    assert "**Estimated 2026 federal taxes** (single), step by step" in text
    assert "| Stock earning 30000 | $30,000 | long-term capital gains (assumed) |" in text        # the user's own inputs
    assert "- $200,000 + $5,000 + $30,000 = **$235,000**" in text
    assert "- Itemized: property tax $10,000" in text and "Your property tax doesn't lower your income tax here" in text
    assert "- $235,000 − $16,100 = **$218,900**" in text
    assert "- 24% on ($188,900 − $105,700) = $83,200: 24% × $83,200 = $19,968" in text
    assert "15% × $30,000 = $4,500" in text and "3.8% × $30,000 = **$1,140**" in text
    assert "- $37,934 + $4,500 + $1,140 = **$43,574**" in text
    assert "6.2% × $184,500 = $11,439 (only the first $184,500 of your $205,000)" in text
    assert "- Federal: $43,574 + $14,457 = **$58,031**" in text and "**$68,031** in all" in text
    assert [line for line in text.splitlines() if line.startswith("**Step ")][-1] == "**Step 9. Total**"
    assert "short-term gains): federal taxes would be **$62,101**" in text
    assert "freelance (1099) work: federal taxes would be **$58,0" in text      # SE tax instead of FICA: about the same


def test_calculator_falls_back_when_the_sort_is_unusable():
    llm_module.set_llm(SortingLLM({"items": []}))
    text, note = TC.answer(KEVIN)
    assert text is None and "no amounts sorted" in note


def test_tsx_typed_for_tax_may_be_proofread():
    typed = "Stock earning 30000\nHow much tsx i need to pay"
    assert N._proofread_ok(typed, "Stock earnings are $30,000. How much tax do I need to pay?")
    assert not N._proofread_ok("How is the TSX doing today?", "How is the tax doing today?")       # the index, in capitals


def test_income_tax_question_goes_to_the_tax_agent_alone():
    s = {"question": KEVIN.replace("i need", "do I need")}
    assert N._with_income_tax(["tax", "calc"], s) == ["tax"]
    assert N._with_income_tax(["qa"], s) == ["tax"]
    assert N._with_income_tax(["goal", "calc"], s) == ["tax"]                    # not about the saved plan
    assert N._with_income_tax(["calc"], {"question": "How much will $10,000 grow to at 6% a year over 10 years?"}) == ["calc"]


def test_tax_pages_search_only_the_tax_categories():
    from src.workflow import tax_tools, tools
    hits = [{"score": 0.9, "doc_id": "bond", "category": "bonds"}, {"score": 0.8, "doc_id": "tax-bracket", "category": "taxes-and-accounts"},
            {"score": 0.7, "doc_id": "roth-ira", "category": "retirement"}]
    tools.set_kb_searcher(lambda q, k=None: hits)
    assert [h["doc_id"] for h in tax_tools.search_tax_pages("brackets")] == ["tax-bracket", "roth-ira"]


def test_step_by_step_tax_is_not_rewritten_and_links_the_tax_pages():
    calls = []

    class LLM:
        model = "scripted"

        def invoke(self, messages):
            calls.append(messages[0][1][:40])
            return type("R", (), {"content": "Total income is $235,000."})()
    llm_module.set_llm(LLM())
    s = {"question": KEVIN, "entities": {}, "profile": {}, "trace": [], "agent_outputs": {
        "tax": {"agent": "tax", "status": "answered", "content": "**Step 1. Add up your income**", "verbatim": True,
                "explains_itself": True, "sources": [
            {"id": "kb:tax-bracket#(lead)", "title": "Tax bracket (Wikipedia)", "url": "https://en.wikipedia.org/wiki/Tax_bracket"}]}}}
    out = N.synthesizer_node(s, {})["final_response"]
    assert out.startswith("**Step 1. Add up your income**") and "$235,000" not in out
    assert "**Read more:** [Tax bracket](https://en.wikipedia.org/wiki/Tax_bracket)" in out and calls == []


# ---------------------------------------------------------------- step 2: the figures carried, one question asked
def kevin_estimate():
    r, _ = TC.read(KEVIN, KEVIN_SORTED)
    return TC.estimate(r)


def test_the_open_point_that_changes_the_tax_most_is_asked_with_answer_buttons():
    est = kevin_estimate()
    single = est.profile["total_federal"]
    joint = T.estimate(T.TaxInputs(filing_status="married_joint", wages=205_000, long_term_gains=30_000, property_tax=10_000))
    assert est.choices == TC.QUESTIONS["status"][1]                      # filing status moves the total most
    assert f"**One question:** Do you file as single, or married filing jointly? It changes your federal taxes by about " \
           f"{TC.money(single - joint['total_federal'])}" in est.text
    assert est.text.index("**One question:**") < est.text.index("_Not included:")


def test_a_small_open_point_is_assumed_not_asked():
    items = [{"text": "I earn 90000", "amount": 90000, "kind": "wages", "loss": False},
             {"text": "side job 1000", "amount": 1000, "kind": "job_unspecified", "loss": False}]
    r, _ = TC.reading_from(items, "single")
    est = TC.estimate(r)
    assert est.choices == [] and "**One question:**" not in est.text and "freelance (1099) work: federal taxes would be" in est.text


def test_the_profile_keeps_the_users_figures_and_what_they_said():
    p = kevin_estimate().profile
    assert p["filing_status"] is None and p["year"] == 2026 and p["total_federal"] == pytest.approx(58030.5)
    assert [(i["amount"], i["kind"]) for i in p["items"]] == [(200000, "wages"), (10000, "property_tax"),
                                                             (5000, "job_unspecified"), (30000, "stock_unspecified")]


def update_llm(items, status=None, change=""):
    return SortingLLM({"items": items, "filing_status": status, "change": change})


def test_what_if_im_married_redoes_the_estimate_from_the_carried_figures():
    profile = kevin_estimate().profile
    kept = [{**i, "from": n} for n, i in enumerate(profile["items"])]
    llm_module.set_llm(update_llm(kept, "married_joint", "filing status: married filing jointly"))
    est, note = TC.follow_up("What if I'm married filing jointly?", profile)
    joint = T.estimate(T.TaxInputs(filing_status="married_joint", wages=205_000, long_term_gains=30_000, property_tax=10_000))
    assert est.profile["filing_status"] == "married_joint" and est.profile["total_federal"] == pytest.approx(joint["total_federal"], abs=0.01)
    assert est.text.startswith("**Updated:** filing status is now married filing jointly. Federal taxes go from $58,031 to")
    assert "(married filing jointly), step by step" in est.text and "you file as **single**" not in est.text
    assert est.choices == TC.QUESTIONS["stock"][1]                       # next biggest open point
    assert note.startswith("follow-up (filing status is now married filing jointly)")


def test_an_answer_button_reclassifies_one_figure():
    profile = kevin_estimate().profile
    kept = [{**i, "from": n} for n, i in enumerate(profile["items"])]
    kept[3] = {**kept[3], "kind": "short_term_gains"}
    llm_module.set_llm(update_llm(kept, None, "the stocks were held a year or less"))
    est, _ = TC.follow_up("I held the shares a year or less", profile)
    assert "| Stock earning 30000 | $30,000 | short-term capital gains |" in est.text
    assert est.text.startswith("**Updated:** “Stock earning 30000” is now short-term capital gains. Federal taxes go from "
                               "$58,031 to **$62,101** (+$4,070)")


def test_a_follow_up_may_add_a_figure_only_from_the_message():
    profile = kevin_estimate().profile
    kept = [{**i, "from": n} for n, i in enumerate(profile["items"])]
    llm_module.set_llm(update_llm([*kept, {"from": None, "amount": 12000, "kind": "charity", "text": "gave 12000"}], None, "added charity"))
    assert TC.follow_up("And I gave $12,000 to charity?", profile)[0].text.startswith("**Updated:** added $12,000 of charitable gift.")
    assert "not an amount you gave" in TC.follow_up("And I gave to charity?", profile)[1]          # 12,000 isn't in this message


def test_a_follow_up_that_changes_nothing_falls_back_to_explaining():
    profile = kevin_estimate().profile
    kept = [{**i, "from": n} for n, i in enumerate(profile["items"])]
    llm_module.set_llm(update_llm(kept, None, ""))
    assert TC.follow_up("What is a tax bracket?", profile) == (None, "tax follow-up: nothing changed")


def test_the_tax_agent_answers_a_follow_up_and_carries_the_new_figures():
    profile = kevin_estimate().profile
    kept = [{**i, "from": n} for n, i in enumerate(profile["items"])]
    llm_module.set_llm(update_llm(kept, "married_joint", "filing status: married filing jointly"))
    q = "What if I'm married filing jointly?"
    s = {"question": q, "history": [], "profile": {}, "entities": {"wiki_query": q}, "follow_up": True,
         "context_in": {"question": "How much tax?", "tax": profile}}
    res = N.tax_node(s, {})
    out = res["agent_outputs"]["tax"]
    assert out["asks_user"] and out["choices"] == TC.QUESTIONS["stock"][1]
    assert res["turn_context"]["tax"]["filing_status"] == "married_joint"
    assert N._with_income_tax(["qa"], s) == ["tax"]                      # a follow-up to an estimate goes to the tax agent


def test_the_estimate_is_carried_in_the_context_and_described_for_the_proofreader():
    from src.workflow import context as CTX
    profile = kevin_estimate().profile
    ctx = CTX.build({"question": "How much tax?", "intent": ["tax"], "turn_context": {"tax": profile}})
    assert ctx["tax"] == profile
    later = CTX.build({"question": "What is a bracket?", "intent": ["tax"], "follow_up": True, "context_in": ctx})
    assert later["tax"] == profile                                          # kept through a follow-up that doesn't change it
    assert "Stock earning 30000 (30000, stock_unspecified)" in CTX.describe(ctx) and "federal total 58030" in CTX.describe(ctx)


def test_the_tax_agents_question_becomes_the_reply_buttons():
    s = {"question": KEVIN, "entities": {}, "profile": {}, "trace": [], "agent_outputs": {
        "tax": {"agent": "tax", "status": "answered", "content": "Steps.", "verbatim": True, "explains_itself": True,
                "sources": [], "choices": ["I file as single", "We're married filing jointly"], "asks_user": True}}}
    assert N.synthesizer_node(s, {})["choices"] == ["I file as single", "We're married filing jointly"]


def test_an_answer_button_reaches_the_estimate_even_when_not_marked_a_follow_up():
    profile = {**kevin_estimate().profile, "choices": TC.QUESTIONS["stock"][1]}
    s = {"question": "I held the shares for a year or less.", "original_question": "I held the shares a year or less",
         "context_in": {"tax": profile}, "follow_up": False}
    assert N._last_estimate(s) == profile and N._with_income_tax(["qa"], s) == ["tax"]
    other = {"question": "What is an ETF?", "original_question": "What is an ETF?", "context_in": {"tax": profile}, "follow_up": False}
    assert N._last_estimate(other) is None and N._with_income_tax(["qa"], other) == ["qa"]


def test_the_estimate_stays_in_the_context_through_another_question():
    from src.workflow import context as CTX
    profile = kevin_estimate().profile
    later = CTX.build({"question": "What is a wash sale?", "intent": ["qa"], "follow_up": False, "context_in": {"tax": profile}})
    assert later["tax"] == profile


def test_more_on_top_of_a_carried_figure_is_the_users_amount():
    profile = kevin_estimate().profile
    kept = [{**i, "from": n} for n, i in enumerate(profile["items"])]
    kept[0] = {**kept[0], "amount": 210000}                           # the $10,000 bonus added to the salary
    llm_module.set_llm(update_llm(kept, None))
    est, _ = TC.follow_up("How much do I earn if I also earn $10,000 more from a bonus?", profile,
                          typed="what if I also earn 10000 more from a bonus?")
    assert est.text.startswith("**Updated:** “I earn 200000 a year” $200,000 → $210,000.")
    kept[0] = {**kept[0], "amount": 225000}
    llm_module.set_llm(update_llm(kept, None))
    assert "not an amount you gave" in TC.follow_up("what if I also earn 10000 more?", profile)[1]


def test_an_empty_placeholder_item_is_skipped_and_a_figure_copied_by_number_is_kept():
    profile = kevin_estimate().profile
    kept = [{"from": n} for n in range(len(profile["items"]))]
    llm_module.set_llm(update_llm([*kept, {"from": None, "amount": None, "kind": None, "loss": None, "text": None}], "married_joint"))
    est, note = TC.follow_up("We're married filing jointly", profile)
    assert est is not None and est.profile["items"] == profile["items"] and est.profile["filing_status"] == "married_joint"


def test_a_total_the_proofreader_adds_is_not_required():
    profile = kevin_estimate().profile
    kept = [{**i, "from": n} for n, i in enumerate(profile["items"])]
    llm_module.set_llm(update_llm(kept, "married_joint"))
    est, _ = TC.follow_up("What is our tax as married filing jointly with a total income of $235,000?", profile,
                          typed="We're married filing jointly")
    assert est is not None and est.profile["filing_status"] == "married_joint"


def test_tax_typed_as_tsx_is_still_an_income_tax_question():
    typed = "I earn 200000 a uear\n-Stock earning 30000\n-How much tsx i need to pay"
    assert TC.asks_income_tax(typed)
    assert not TC.asks_income_tax("How is the TSX doing today?")


def test_a_carried_figure_relisted_without_its_number_is_matched_by_amount():
    profile = kevin_estimate().profile
    relisted = [{k: v for k, v in i.items()} for i in profile["items"]]
    relisted[3]["kind"] = "short_term_gains"
    llm_module.set_llm(update_llm([{**i, "from": None, "text": "x"} for i in relisted], None))
    est, note = TC.follow_up("I held the shares a year or less", profile)
    assert note.startswith("follow-up (“Stock earning 30000” is now short-term capital gains)")
    assert [i["text"] for i in est.profile["items"]] == [i["text"] for i in profile["items"]]


# ---------------------------------------------------------------- filing statuses, new deductions, credits (2026, by hand)
def test_head_of_household_with_two_children_gets_child_and_earned_income_credits():
    r = T.estimate(T.TaxInputs(filing_status="head_of_household", wages=50_000, children_under_17=2))
    assert r["standard"] == 24_150 and r["taxable_income"] == 25_850
    assert r["tax_before_credits"] == pytest.approx(1_770 + 0.12 * 8_150)              # 2,748
    cr = r["credits"]
    assert cr["nonrefundable_used"] == pytest.approx(2_748)                              # child credit up to the tax
    refund = {x["name"]: x["amount"] for x in cr["refundable_rows"]}
    assert refund["additional_child_tax_credit"] == pytest.approx(4_400 - 2_748)         # the rest, under $1,700 a child
    assert refund["earned_income_credit"] == pytest.approx(7_316 - 0.2106 * (50_000 - 23_890))
    assert r["income_tax"] == pytest.approx(-(1_652 + 7_316 - 0.2106 * 26_110))          # a refund beyond withholding


def test_married_seniors_get_the_extra_standard_deduction_and_the_senior_deduction():
    r = T.estimate(T.TaxInputs(filing_status="married_joint", wages=140_000, age_65_or_older=2))
    assert r["standard"] == 32_200 + 2 * 1_650
    assert [(d["name"], d["amount"]) for d in r["new_deductions"]] == [("senior", 12_000)]
    assert r["taxable_income"] == 140_000 - 35_500 - 12_000
    assert r["income_tax"] == pytest.approx(2_480 + 0.12 * (92_500 - 24_800))


def test_the_senior_deduction_phases_out_at_6_percent():
    r = T.estimate(T.TaxInputs(wages=100_000, age_65_or_older=1))
    assert r["new_deductions"][0]["amount"] == pytest.approx(6_000 - 0.06 * 25_000)


def test_tips_are_deducted_on_top_of_the_standard_deduction():
    r = T.estimate(T.TaxInputs(wages=60_000, tips=10_000))
    assert r["taxable_income"] == 60_000 - 16_100 - 10_000
    assert r["income_tax"] == pytest.approx(1_240 + 0.12 * (33_900 - 12_400))


def test_car_loan_interest_phases_out_200_per_1000():
    r = T.estimate(T.TaxInputs(wages=105_500, car_loan_interest=4_000))
    assert r["new_deductions"][0]["amount"] == pytest.approx(4_000 - 200 * 6)            # $5,500 over → 6 steps


def test_child_care_credit_rate_and_the_child_tax_credit():
    r = T.estimate(T.TaxInputs(filing_status="married_joint", wages=100_000, children_under_17=1, care_expenses=5_000))
    care = next(c for c in r["credits"]["nonrefundable"] if c["name"] == "child_and_dependent_care")
    assert care["base"] == 3_000 and care["rate"] == pytest.approx(0.35) and care["amount"] == pytest.approx(1_050)
    assert r["income_tax"] == pytest.approx(2_480 + 0.12 * (67_800 - 24_800) - 1_050 - 2_200)


def test_low_income_child_care_gets_the_50_percent_rate():
    care = T.credits(T.TaxInputs(wages=15_000, care_expenses=2_000), 15_000, 5_000, T.rules()[1])["nonrefundable"][0]
    assert care["rate"] == pytest.approx(0.50) and care["amount"] == pytest.approx(1_000)


def test_american_opportunity_credit_is_40_percent_refundable_and_phases_out():
    r = T.estimate(T.TaxInputs(wages=85_000, college_expenses=4_000, students=1))
    ao = next(c for c in r["credits"]["nonrefundable"] if c["name"] == "american_opportunity")
    assert ao["total"] == pytest.approx(2_500 * 0.5) and ao["amount"] == pytest.approx(1_250 * 0.6)     # halfway out
    assert r["credits"]["refundable"] == pytest.approx(500)


def test_married_filing_separately_uses_half_the_joint_lines_and_no_earned_income_credit():
    r = T.estimate(T.TaxInputs(filing_status="married_separate", wages=30_000, children_under_17=1, tips=5_000))
    assert r["standard"] == 16_100 and r["new_deductions"][0]["amount"] == 0           # tips need a joint return
    assert not any(x["name"] == "earned_income_credit" for x in r["credits"]["refundable_rows"])
    assert T.estimate(T.TaxInputs(filing_status="married_separate", wages=400_000))["niit"] == 0


def test_household_counts_need_words_for_them_in_the_message():
    raw = {"children_under_17": 2, "age_65_or_older": 1, "students": 1, "graduate_school": True}
    assert TC.household_of(raw, "I earn $50,000 and have two kids") == {"children_under_17": 2, "graduate_school": True}
    assert TC.household_of(raw, "I'm 67, retired, my daughter is in college") == {       # a college student isn't under 17
        "age_65_or_older": 1, "students": 1, "graduate_school": True}
    assert TC.household_of({"children_under_17": 3}, "I earn $50,000") == {}                      # invented children


def test_tips_count_as_pay_and_come_back_off_as_a_deduction():
    items = [{"text": "I earn 50000", "amount": 50000, "kind": "wages", "loss": False},
             {"text": "plus 8000 in tips", "amount": 8000, "kind": "tips", "loss": False}]
    r, _ = TC.reading_from(items, "single")
    assert r.inputs.wages == 58_000 and r.inputs.tips == 8_000
    included = [{**items[1], "included": True}]
    r2, _ = TC.reading_from([items[0], *included], "single")
    assert r2.inputs.wages == 50_000 and r2.inputs.tips == 8_000
    text = TC.estimate(r).text
    assert "**Step 3. The new deductions (2025–2028)**" in text and "- Tips: $8,000 → **$8,000**" in text
    assert "- $58,000 − $16,100 − $8,000 = **$33,900**" in text


def test_children_without_a_filing_status_ask_about_head_of_household():
    items = [{"text": "I earn 50000", "amount": 50000, "kind": "wages", "loss": False}]
    r, _ = TC.reading_from(items, None, None, {"children_under_17": 2})
    est = TC.estimate(r)
    assert est.choices == TC.QUESTIONS["status_hoh"][1] and "(head of household)" in est.text
    assert "Child tax credit: 2 × $2,200 (children under 17) = **$4,400**" in est.text


def test_head_of_household_estimate_shows_the_credits_and_the_refund():
    items = [{"text": "I earn 50000", "amount": 50000, "kind": "wages", "loss": False},
             {"text": "daycare 4000", "amount": 4000, "kind": "care_expenses", "loss": False}]
    r, _ = TC.reading_from(items, "head_of_household", None, {"children_under_17": 2})
    text = TC.estimate(r).text
    assert "**Estimated 2026 federal taxes** (head of household)" in text
    assert "Child and dependent care credit: 35% of $4,000 of care costs = **$1,400**" in text
    assert "Refundable part of the child tax credit: **$3,052** (refundable)" in text
    assert "Earned income credit: **$1,817** (refundable)" in text
    assert "= **-$4,869** (negative: the IRS pays you this much beyond what was withheld)" in text


def test_a_follow_up_can_add_a_child():
    profile = kevin_estimate().profile
    kept = [{**i, "from": n} for n, i in enumerate(profile["items"])]
    llm_module.set_llm(SortingLLM({"items": kept, "filing_status": "married_joint", "household": {"children_under_17": 1}}))
    est, note = TC.follow_up("We're married and have a son", profile)
    assert est.profile["household"] == {"children_under_17": 1}
    assert "children under 17: 1" in note and "Child tax credit: 1 × $2,200" in est.text


def test_an_only_job_is_wages_and_tips_included_in_pay_are_not_counted_twice():
    q = "I'm a waiter. I make $38,000 including $12,000 in tips. How much tax do I pay?"
    r, _ = TC.read(q, {"items": [{"amount": 38000, "kind": "job_unspecified", "text": "I make $38,000"},
                                 {"amount": 12000, "kind": "tips", "text": "$12,000 in tips"}]})
    assert r.inputs.wages == 38_000 and r.inputs.tips == 12_000 and not any(k == "job" for k, *_ in r.alternatives)


def test_an_income_tax_question_drops_the_goal_agent_unless_it_is_about_the_plan():
    s = {"question": "My wife and I are 67 and retired, we have $40,000 of pension income. How much tax do we owe?"}
    assert N._with_income_tax(["tax", "goal"], s) == ["tax"]


# ---------------------------------------------------------------- figures given one message at a time
def test_a_stated_figure_is_recognised_but_not_a_loan_or_market_question():
    assert TC.states_tax_figure("i earned $10600 from stock trading")
    assert TC.states_tax_figure("i have fix income from my job $109000")
    assert TC.states_tax_figure("I have $10,000 property tax")
    assert not TC.states_tax_figure("I owe $5,000 and pay $200 a month. How many months?")
    assert not TC.states_tax_figure("I bought 10 AAPL shares at $150, how is it doing?")


def test_a_first_figure_starts_an_estimate_and_goes_to_the_tax_agent():
    llm_module.set_llm(SortingLLM({"items": [{"amount": 10600, "kind": "stock_unspecified", "text": "earned $10600 from stock trading"}]}))
    q = "i earned $10600 from stock trading"
    s = {"question": q, "original_question": q, "history": [], "profile": {}, "entities": {"wiki_query": q}}
    assert N._with_income_tax(["qa"], s) == ["tax"]
    res = N.tax_node(s, {})
    assert res["agent_outputs"]["tax"]["content"].startswith("**Estimated 2026 federal taxes** (single)")
    assert res["turn_context"]["tax"]["items"][0]["amount"] == 10600


def test_a_deduction_with_no_income_yet_is_noted_and_income_asked_for():
    llm_module.set_llm(SortingLLM({"items": [{"amount": 10000, "kind": "property_tax", "text": "$10000 property tax"}]}))
    est, note = TC.answer("i have $10000 property tax")
    assert est.text.startswith("**Noted for your tax estimate:** $10,000 property tax (itemized deduction).")
    assert est.profile["total_federal"] is None and "no income yet" in note


def test_each_later_figure_is_added_and_the_total_recalculated():
    llm_module.set_llm(SortingLLM({"items": [{"amount": 10600, "kind": "stock_unspecified", "text": "stock trading"}]}))
    first, _ = TC.answer("i earned $10600 from stock trading")
    kept = [{**i, "from": n} for n, i in enumerate(first.profile["items"])]
    llm_module.set_llm(update_llm([*kept, {"from": None, "amount": 109000, "kind": "job_unspecified", "text": "my job $109000"}]))
    second, note = TC.follow_up("i have fix income from my job $109000", first.profile)
    assert second.profile["items"][1]["kind"] == "wages"                                  # an only job is wages
    assert second.profile["total_federal"] == pytest.approx(25_078.5)
    assert second.text.startswith("**Updated:** added $109,000 of wages. Federal taxes go from $0 to **$25,079**")
    kept = [{**i, "from": n} for n, i in enumerate(second.profile["items"])]
    llm_module.set_llm(update_llm([*kept, {"from": None, "amount": 10000, "kind": "property_tax", "text": "property tax"}]))
    third, _ = TC.follow_up("i have $10000 property tax", second.profile)
    assert third.profile["total_federal"] == pytest.approx(25_078.5)                       # under the standard deduction
    assert "Your property tax doesn't lower your income tax here" in third.text


def test_a_mortgage_without_an_amount_asks_for_the_interest_and_what_it_would_take():
    items = [{"text": "job", "amount": 109000, "kind": "wages", "loss": False},
             {"text": "stocks", "amount": 10600, "kind": "stock_unspecified", "loss": False},
             {"text": "property tax", "amount": 10000, "kind": "property_tax", "loss": False}]
    profile = {"year": 2026, "filing_status": None, "items": items, "household": {}, "total_federal": 25078.5}
    ask = TC.missing_amount("i have monthly mortgage payment .", profile)
    assert ask.startswith("How much **mortgage interest** do you pay in a year? Only the interest counts")
    assert "you have $10,000 so far (your $10,000 of state, local and property tax), so it would need to be more than $6,100" in ask
    s = {"question": "What is my monthly mortgage payment?", "original_question": "i have monthly mortgage payment .",
         "history": [], "profile": {}, "entities": {"wiki_query": "mortgage"}, "context_in": {"tax": profile}}
    llm_module.set_llm(SortingLLM({}))
    res = N.tax_node(s, {})
    assert res["agent_outputs"]["tax"]["status"] == "need_info" and res["turn_context"]["tax"]["pending"] == "mortgage_interest"
    assert N._with_income_tax(["calc"], s) == ["tax"]


def test_the_answer_to_the_interest_question_updates_the_estimate():
    items = [{"text": "job", "amount": 109000, "kind": "wages", "loss": False, "included": False},
             {"text": "stocks", "amount": 10600, "kind": "stock_unspecified", "loss": False, "included": False},
             {"text": "property tax", "amount": 10000, "kind": "property_tax", "loss": False, "included": False}]
    profile = {"year": 2026, "filing_status": None, "items": items, "household": {}, "total_federal": 25078.5,
               "pending": "mortgage_interest"}
    assert TC.changes_estimate("about $12,000", profile)
    kept = [{**i, "from": n} for n, i in enumerate(items)]
    llm_module.set_llm(update_llm([*kept, {"from": None, "amount": 12000, "kind": "mortgage_interest", "text": "about $12,000"}]))
    est, _ = TC.follow_up("about $12,000", profile)
    assert est.profile["total_federal"] == pytest.approx(25_078.5 - 0.22 * 5_900)           # itemizing $22,000 beats $16,100
    assert "Federal taxes go from $25,079 to **$23,781**" in est.text


def test_an_answer_to_the_amount_question_skips_the_tool_picker_and_updates_the_estimate():
    items = [{"text": "job", "amount": 109000, "kind": "wages", "loss": False, "included": False},
             {"text": "property tax", "amount": 10000, "kind": "property_tax", "loss": False, "included": False}]
    profile = {"year": 2026, "filing_status": "single", "items": items, "household": {}, "total_federal": 1.0,
               "pending": "mortgage_interest"}
    kept = [{**i, "from": n} for n, i in enumerate(items)]

    class Both(SortingLLM):
        def bind_tools(self, specs):
            raise AssertionError("the tool picker must not run for an answer to the amount question")
    llm_module.set_llm(Both({"items": [*kept, {"from": None, "amount": 12000, "kind": "mortgage_interest", "text": "$12,000"}],
                             "filing_status": "single"}))
    q = "about $12,000 a year"
    res = N.tax_node({"question": q, "original_question": q, "history": [], "profile": {}, "entities": {"wiki_query": q},
                      "context_in": {"tax": profile}}, {})
    assert [i["kind"] for i in res["turn_context"]["tax"]["items"]] == ["wages", "property_tax", "mortgage_interest"]


# ---------------------------------------------------------------- tax year 2025 (Kevin's "Sarah" scenario, by hand)
SARAH = T.TaxInputs(wages=95_000, interest_dividends=1_200, long_term_gains=6_000, pre_tax_retirement=8_000,
                    mortgage_interest=12_000, state_local_taxes=7_500, charity=2_000, student_loan_interest=4_000)


def test_sarah_2025_itemizes_and_gets_part_of_the_student_loan_deduction():
    r = T.estimate(SARAH, 2025)
    assert r["year"] == 2025 and r["standard"] == 15_750
    # MAGI 94,200 is 9,200 into the $85,000-$100,000 phase-out: $2,500 × 5,800/15,000
    assert r["student_loan_deduction"] == pytest.approx(2_500 * 5_800 / 15_000)
    assert r["agi"] == pytest.approx(95_000 + 1_200 + 6_000 - 8_000 - 966.67, abs=0.01)
    assert r["itemized"] == 21_500 and r["itemizes"]                                    # 7,500 + 12,000 + 2,000
    # ordinary 65,733.33: 10% × 11,925 + 12% × 36,550 + 22% × 17,258.33; gains 6,000 at 15%
    assert r["ordinary_tax"] == pytest.approx(1_192.5 + 4_386 + 0.22 * (65_733.33 - 48_475), abs=0.01)
    assert r["preferential_tax"] == pytest.approx(900) and r["niit"] == 0
    assert r["income_tax"] == pytest.approx(10_275.33, abs=0.01)
    assert r["payroll"]["total"] == pytest.approx(0.0765 * 95_000)                      # the 401(k) doesn't lower FICA
    assert r["total_federal"] == pytest.approx(17_542.83, abs=0.01)


def test_the_2025_and_2026_rules_differ_where_the_law_says():
    a, b = T.rules(2025)[1], T.rules(2026)[1]
    assert a["standard_deduction"]["single"] == 15_750 and b["standard_deduction"]["single"] == 16_100
    assert a["salt"]["cap"] == 40_000 and b["salt"]["cap"] == 40_400
    care25 = T.credits(T.TaxInputs(wages=15_000, care_expenses=2_000), 15_000, 5_000, a)["nonrefundable"][0]
    assert care25["rate"] == pytest.approx(0.35)                                        # 50% only from 2026


def test_no_student_loan_deduction_above_the_range_or_on_a_separate_return():
    assert T.estimate(T.TaxInputs(wages=120_000, student_loan_interest=2_000))["student_loan_deduction"] == 0
    assert T.estimate(T.TaxInputs(filing_status="married_separate", wages=40_000, student_loan_interest=2_000))["student_loan_deduction"] == 0
    assert T.estimate(T.TaxInputs(wages=50_000, student_loan_interest=3_000))["student_loan_deduction"] == 2_500


def test_account_and_form_names_are_not_amounts():
    q = "Contributed $8,000 to a traditional 401(k), $2,000 to a 529 plan, and got a 1099-INT and Form W-2 for $95,000"
    assert TC.amounts(q) == [8_000, 2_000, 95_000]
    assert TC.amounts("I put 6k in my 401k") == [6_000]


def test_a_third_person_tax_scenario_is_never_off_topic():
    llm_module.set_llm(type("L", (), {"model": "x", "invoke": lambda self, m: type("R", (), {"content":
        '{"intents": ["off_topic"], "confidence": 0.9}' if "router" in m[0][1] else m[1][1].removeprefix("Message: ")})()})())
    q = ("Sarah is a single taxpayer. In 2025: salary $95,000, interest $1,200, paid $12,000 mortgage interest and "
         "$7,500 in state income taxes.")
    assert N._tax_scenario(q) and not N._tax_scenario("What is the capital of France?")
    assert N._route({"question": q, "original_question": q, "history": []})["intent"] == ["tax"]


def test_an_explanation_after_an_estimate_uses_the_users_own_figures():
    items = [{"text": t, "amount": a, "kind": k, "loss": False, "included": False} for t, a, k in [
        ("salary", 95000, "wages"), ("interest", 1200, "interest_dividends"), ("stock", 6000, "long_term_gains"),
        ("401(k)", 8000, "pre_tax_retirement"), ("mortgage", 12000, "mortgage_interest"), ("CA tax", 7500, "state_local_taxes"),
        ("charity", 2000, "charity"), ("student loan", 4000, "student_loan_interest")]]
    profile = {"year": 2025, "filing_status": "single", "items": items, "household": {}, "total_federal": 17542.83}
    facts = TC.estimate_facts(profile, "How are long-term capital gains taxed differently from salary?")
    assert facts.startswith("**In your estimate (2025 rules, computed by Finnie):**")
    assert "($6,000) sit on top of $65,733 of ordinary taxable income: $6,000 at 15% = $900" in facts
    assert "at your 22% bracket they would have cost about $1,320, so the lower rate saves about $420" in facts
    assert TC.estimate_facts(profile, "What is an HSA?") == "" and TC.estimate_facts(None, "capital gains") == ""


def test_with_the_tax_agent_there_qa_is_dropped_for_a_tax_question():
    assert N._tax_to_tax_agent(["tax", "qa"], {"question": "How are long-term capital gains taxed?"}) == ["tax"]


def test_no_worked_example_is_added_to_a_tax_answer():
    s = {"question": "How are long-term capital gains taxed?", "agent_outputs": {
        "tax": {"agent": "tax", "status": "answered", "content": "Gains are taxed at 0/15/20%.", "sources": []}}}
    llm_module.set_llm(SortingLLM({}))
    assert N.illustrate_node(s, {}) == {"trace": []}



def test_a_filing_status_needs_words_for_it_in_the_message():
    assert TC.status_from(None, "I'm single and earn $80,000") == "single"
    assert TC.status_from("head_of_household", "I earn $50,000 and have two kids") is None          # guessed
    assert TC.status_from("head_of_household", "I'm a single mom with two kids") == "head_of_household"
    assert TC.status_from(None, "I'm a single mom with two kids") is None
    assert TC.status_from("married_joint", "My wife and I earn $95,000") == "married_joint"
    assert TC.status_from("married_joint", "I earn $95,000") is None


def test_a_statement_answering_the_open_question_is_not_a_question():
    assert not TC.is_question("The stocks were held less than a year")
    assert TC.is_question("How are short-term gains taxed?")


def test_the_users_numbers_follow_an_explanation_word_for_word():
    from src.workflow import tools
    tools.set_kb_searcher(lambda q, k=None: [{"score": 0.8, "doc_id": "cg", "doc_title": "Capital gains tax", "section": "(lead)",
                                               "text": "Gains are taxed at 0/15/20%.", "source_url": "https://x", "category": "tax-notes",
                                               "piece": 0, "pieces": 1, "tokens": 5, "section_tokens": 5}])
    items = [{"text": "salary", "amount": 95000, "kind": "wages", "loss": False, "included": False},
             {"text": "stock", "amount": 6000, "kind": "long_term_gains", "loss": False, "included": False}]
    prof = {"year": 2025, "filing_status": "single", "items": items, "household": {}, "total_federal": 1.0}
    q = "How are long-term capital gains taxed differently from salary?"
    out = N.tax_node({"question": q, "original_question": q, "history": [], "profile": {}, "entities": {"wiki_query": q},
                      "context_in": {"tax": prof}}, {})["agent_outputs"]["tax"]
    assert out["verbatim_tail"].startswith("**In your estimate (2025 rules, computed by Finnie):**")


def test_a_curly_apostrophe_still_says_single_and_an_ira_withdrawal_is_income():
    assert TC.status_from(None, "I’m single. I made $60,000 freelancing") == "single"
    r, _ = TC.reading_from([{"text": "IRA", "amount": 50000, "kind": "retirement_withdrawal", "loss": False}], "single")
    assert r.inputs.other_income == 50_000 and r.inputs.pre_tax_retirement == 0


def test_what_the_proofreader_dropped_is_read_from_the_typed_message():
    typed = "I'm single. I made $60,000 freelancing as a 1099 contractor. How much federal tax do I owe?"
    reworded = "How much federal tax do I owe on $60,000 from freelancing as a 1099 contractor?"
    llm_module.set_llm(SortingLLM({"items": [{"amount": 60000, "kind": "self_employment", "text": "freelancing"}]}))
    est, _ = TC.answer(reworded, typed=typed)
    assert est.profile["filing_status"] == "single" and est.choices == []


def test_a_son_in_college_is_not_a_child_under_17():
    q = "I'm single, I earn $85,000 and paid $6,000 of tuition for my son's first year of college."
    assert TC.household_of({"children_under_17": 1}, q) == {}
    assert TC.household_of({"children_under_17": 1}, "My 6-year-old son; I paid $6,000 of tuition") == {"children_under_17": 1}


def test_an_age_counts_as_a_child_and_tuition_alone_is_no_dependent():
    assert TC.household_of({"children_under_17": 1}, "I'm a single dad with a 12-year-old") == {"children_under_17": 1}
    assert TC.household_of({"other_dependents": 1}, "I paid $6,000 of tuition for my son's first year of college") == {}
    assert TC.household_of({"other_dependents": 1}, "Yes, my student is my dependent") == {"other_dependents": 1}
    assert TC.states_tax_figure("I paid $2,000 of student loan interest this year")


def test_a_rejected_sort_gets_one_repair_round():
    replies = [{"items": [{"amount": 65000, "kind": "wages", "text": "pay"}]},                       # left out 40,000
               {"items": [{"amount": 65000, "kind": "wages", "text": "pay"}, {"amount": 40000, "kind": "wages", "text": "wife"}],
                "filing_status": "married_joint"}]

    class Seq:
        model = "x"

        def invoke(self, m):
            import json
            return type("R", (), {"content": json.dumps(replies.pop(0))})()
    llm_module.set_llm(Seq())
    est, _ = TC.answer("We file jointly. I earn $65,000 and my wife earns $40,000. How much tax?")
    assert est is not None and est.profile["filing_status"] == "married_joint" and len(est.profile["items"]) == 2


def test_the_yes_dependent_button_adds_the_dependent_and_pay_is_never_ignored():
    items = [{"text": "I earn $85,000", "amount": 85000, "kind": "wages", "loss": False, "included": False},
             {"text": "tuition", "amount": 6000, "kind": "college_expenses", "loss": False, "included": False}]
    profile = {"year": 2026, "filing_status": "single", "items": items, "household": {"students": 1}, "total_federal": 15122.5,
               "choices": TC.QUESTIONS["dependent"][1]}
    kept = [{**i, "from": n} for n, i in enumerate(items)]
    llm_module.set_llm(update_llm(kept, "single"))
    est, _ = TC.follow_up("Yes, my student is my dependent", profile)
    assert est.profile["household"]["other_dependents"] == 1 and est.profile["total_federal"] == pytest.approx(14622.5)
    got, _ = TC._items([{"amount": 70000, "kind": "not_tax_input", "text": "I earn $70,000"}], [70000], [70000])
    assert got[0]["kind"] == "wages"


# ---------------------------------------------------------------- rental property (Schedule E)
DAVID = ("David is a single taxpayer who earns $120,000 annually as a software engineer. In 2025, he also owns a rental house:\n"
         "Rental income received: $30,000\nProperty management fees: $2,500\nRepairs and maintenance: $3,000\n"
         "Property taxes: $4,000\nMortgage interest: $8,000\nDepreciation expense: $7,500\n"
         "Contributed $10,000 to a traditional 401(k)\nReceived $1,500 in bank interest\n"
         "Sold stock for a $12,000 short-term capital gain\nPaid $3,500 in student loan interest\n"
         "Made $1,000 in charitable donations\nWhat is David's net rental income (or loss)?")
DAVID_ITEMS = [("earns $120,000", 120000, "wages"), ("Rental income received: $30,000", 30000, "rental_income"),
               ("Property management fees: $2,500", 2500, "rental_expense"), ("Repairs and maintenance: $3,000", 3000, "rental_expense"),
               ("Property taxes: $4,000", 4000, "rental_expense"), ("Mortgage interest: $8,000", 8000, "rental_expense"),
               ("Depreciation expense: $7,500", 7500, "rental_expense"), ("Contributed $10,000 to a traditional 401(k)", 10000, "pre_tax_retirement"),
               ("Received $1,500 in bank interest", 1500, "interest_dividends"),
               ("Sold stock for a $12,000 short-term capital gain", 12000, "short_term_gains"),
               ("Paid $3,500 in student loan interest", 3500, "student_loan_interest"),
               ("Made $1,000 in charitable donations", 1000, "charity")]


def test_rental_profit_is_rent_minus_expenses_and_its_property_tax_isnt_salt():
    # worked by hand: AGI 120,000 + 1,500 + 12,000 + 5,000 - 10,000 = 128,500; student loan interest phased out (over $100k);
    # taxable 128,500 - 15,750 = 112,750 -> 1,192.50 + 4,386 + 12,072.50 + 2,256 = 19,907; payroll 9,180
    est = T.estimate(T.TaxInputs(wages=120000, rental_income=30000, rental_expenses=25000, pre_tax_retirement=10000,
                                 interest_dividends=1500, short_term_gains=12000, student_loan_interest=3500, charity=1000), 2025)
    assert est["rental"]["net"] == 5000 and est["gross_income"] == 138500 and est["agi"] == 128500
    assert est["salt_paid"] == 0 and est["student_loan_deduction"] == 0
    assert est["income_tax"] == pytest.approx(19907) and est["total_federal"] == pytest.approx(29087)


def test_a_rental_loss_is_limited_by_the_passive_loss_allowance():
    loss = T.TaxInputs(wages=120000, rental_income=20000, rental_expenses=50000)       # a $30,000 loss
    r = T.estimate(loss, 2025)["rental"]
    assert r["allowance"] == 15000 and r["allowed"] == -15000 and r["carried_forward"] == 15000   # 25,000 - (120k - 100k)/2
    assert T.estimate(T.TaxInputs(wages=160000, rental_income=10000, rental_expenses=20000), 2025)["rental"]["allowed"] == 0
    small = T.estimate(T.TaxInputs(wages=80000, rental_income=10000, rental_expenses=14000), 2025)
    assert small["rental"]["allowed"] == -4000 and small["gross_income"] == 76000
    mfs = T.TaxInputs(filing_status="married_separate", wages=80000, rental_income=10000, rental_expenses=14000)
    assert T.estimate(mfs, 2025)["rental"]["carried_forward"] == 4000


def test_net_rental_income_counts_for_the_net_investment_income_tax():
    est = T.estimate(T.TaxInputs(wages=250000, rental_income=40000, rental_expenses=10000), 2026)
    assert est["niit"] == pytest.approx(0.038 * 30000)


def test_davids_rental_scenario_goes_to_the_tax_agent_and_is_worked_out():
    assert TC.is_scenario(DAVID)
    assert not TC.is_scenario("I retire with $1,000,000 and withdraw $45,000 a year, rising 3%: how long will it last?")
    assert not TC.is_scenario("Which rental expenses are deductible against rental income?")
    assert N._with_income_tax(["calc"], {"question": DAVID}) == ["tax"]
    items = [{"text": t, "amount": a, "kind": k, "loss": False} for t, a, k in DAVID_ITEMS]
    reading, why = TC.reading_from(items, "single", 2025)
    assert why == "" and reading.inputs.rental_income == 30000 and reading.inputs.rental_expenses == 25000
    assert reading.inputs.property_tax == 0 and reading.inputs.mortgage_interest == 0
    est = TC.estimate(reading)
    assert "**Step 1. Work out the rental property's profit**" in est.text
    assert "$3,000 (repairs and maintenance)" in est.text and "Net rental income: $30,000 − $25,000 = **$5,000**" in est.text
    assert "$120,000 + $1,500 + $12,000 + $5,000 = **$138,500**" in est.text and "none once income is over $100,000" in est.text
    assert est.profile["total_federal"] == pytest.approx(29087) and "How rental income is taxed" in est.topics


def test_explanations_after_davids_estimate_use_his_figures():
    items = [{"text": t, "amount": a, "kind": k, "loss": False, "included": False} for t, a, k in DAVID_ITEMS]
    profile = {"year": 2025, "filing_status": "single", "items": items, "household": {}, "total_federal": 29087}
    rent = TC.estimate_facts(profile, "Which rental expenses are deductible against rental income?")
    assert "net rental income of **$5,000**" in rent and "$7,500 (depreciation expense)" in rent and "SALT cap" in rent
    gain = TC.estimate_facts(profile, "Is the $12,000 stock gain taxed at ordinary income rates or capital gains rates?")
    assert "$12,000 of short-term gains" in gain and "taxed as ordinary income" in gain and "24%" in gain
    from src.workflow import tax_tools
    assert "Rental property (Schedule E)" in tax_tools.current_figures("which rental expenses can I deduct?", 2025)


# ---------------------------------------------------------------- selling a home (Section 121), IRA limit, two earners
HOME = [("purchased their home in 2018 for $450,000", 450000, "home_purchase_price"), ("sold it for $850,000", 850000, "home_sale_price"),
        ("John's salary: $130,000", 130000, "wages"), ("Lisa's salary: $90,000", 90000, "wages"),
        ("Interest income: $2,500", 2500, "interest_dividends"), ("Qualified dividends: $4,000", 4000, "qualified_dividends"),
        ("Capital improvements: $50,000", 50000, "home_improvements"), ("Selling expenses: $45,000", 45000, "home_selling_costs"),
        ("spent $3,000 on office furniture", 3000, "not_tax_input"), ("Lisa contributed $23,000 to her 401(k)", 23000, "pre_tax_retirement"),
        ("John contributed $15,000 to a traditional IRA", 15000, "ira_contribution"),
        ("$11,000 in state income taxes", 11000, "state_local_taxes"), ("$6,000 in property taxes", 6000, "property_tax"),
        ("Charitable contributions totaled $4,500", 4500, "charity")]


def test_home_sale_gain_and_the_section_121_exclusion():
    sale = dict(home_purchase_price=450000, home_improvements=50000, home_sale_price=850000, home_selling_costs=45000)
    h = T.estimate(T.TaxInputs(filing_status="married_joint", wages=100000, **sale), 2025)["home_sale"]
    assert (h["basis"], h["realized"], h["gain"], h["excluded"], h["taxable"]) == (500000, 805000, 305000, 305000, 0)
    single = T.estimate(T.TaxInputs(wages=100000, **sale), 2025)
    assert single["home_sale"]["taxable"] == 55000 and single["long_term_taxed"] == 55000      # over the $250,000 cap
    rented = T.estimate(T.TaxInputs(wages=100000, home_main_residence=0, **sale), 2025)
    assert rented["home_sale"]["taxable"] == 305000
    loss = T.estimate(T.TaxInputs(wages=100000, home_purchase_price=500000, home_sale_price=450000), 2025)
    assert loss["home_sale"]["gain"] == -50000 and loss["capital_loss_deducted"] == 0 and loss["gross_income"] == 100000


def test_ira_contributions_are_limited_and_phased_out_with_a_workplace_plan():
    ira = T.estimate(T.TaxInputs(wages=60000, ira_contribution=15000), 2025)["ira"]
    assert ira["deductible"] == 7000 and ira["excess"] == 8000 and ira["range"] is None
    assert T.estimate(T.TaxInputs(wages=60000, ira_contribution=9000, age_65_or_older=1), 2025)["ira"]["deductible"] == 8000
    covered = T.estimate(T.TaxInputs(wages=94000, pre_tax_retirement=10000, ira_contribution=7000), 2025)["ira"]   # MAGI 84,000
    assert covered["range"] == [79000, 89000] and covered["deductible"] == 3500
    assert T.estimate(T.TaxInputs(wages=110000, pre_tax_retirement=10000, ira_contribution=7000), 2025)["ira"]["deductible"] == 0
    assert T.estimate(T.TaxInputs(wages=60000, ira_contribution=7500), 2026)["ira"]["deductible"] == 7500


def test_social_security_wage_base_is_per_spouse():
    one = T.estimate(T.TaxInputs(filing_status="married_joint", wages=220000), 2025)["payroll"]["social_security"]
    two = T.estimate(T.TaxInputs(filing_status="married_joint", wages=220000, spouse_wages=90000), 2025)["payroll"]["social_security"]
    assert one == pytest.approx(0.062 * 176100) and two == pytest.approx(0.062 * 220000)


def test_john_and_lisas_home_sale_is_read_and_worked_out():
    # worked by hand: AGI 226,500 - 23,000 - 7,000 = 196,500; taxable 165,000 (161,000 ordinary + 4,000 dividends);
    # 2,385 + 8,772 + 14,091 + 600 = 25,848 income tax; payroll 6.2% x 220,000 + 1.45% x 220,000 = 16,830
    items = [{"text": t, "amount": a, "kind": k, "loss": False} for t, a, k in HOME]
    text = "They lived in the home as their primary residence for the entire 7 years they owned it."
    assert TC.main_home(text) == 1 and TC.main_home("we rented it out the whole time") == 0 and TC.main_home("we sold a house") is None
    reading, why = TC.reading_from(items, "married_joint", 2025, {"home_main_residence": 1})
    assert why == "" and reading.inputs.spouse_wages == 90000 and not reading.alternatives
    est = TC.estimate(reading)
    assert est.profile["income_tax"] == pytest.approx(25848) and est.profile["total_federal"] == pytest.approx(42678)
    for phrase in ("Adjusted basis: $450,000 purchase price + $50,000 improvements = **$500,000**",
                   "Amount realized: $850,000 sale price − $45,000 selling costs = **$805,000**",
                   "Gain: $805,000 − $500,000 = **$305,000**", "so $305,000 is excluded and **$0** is taxable",
                   "the other $8,000 is an excess contribution", "each spouse's pay is under it",
                   "Subtract pre-tax retirement contributions and traditional IRA contribution"):
        assert phrase in est.text, phrase
    unsure, _ = TC.reading_from(items, "married_joint", 2025, {})
    assert [k for k, _, _ in unsure.alternatives] == ["home"] and "main home" in unsure.assumed[0]
    facts = TC.estimate_facts(est.profile, "What is their realized gain on the sale?")
    assert "Realized gain: $805,000 − $500,000 = **$305,000**" in facts and "**$305,000** excluded" in facts


def test_section_121_questions_go_to_the_tax_agent():
    s = {"question": "Does the Section 121 home-sale exclusion apply, and how much gain can be excluded?"}
    assert N._tax_to_tax_agent(["qa"], s) == ["tax"]


def test_a_landlords_property_tax_and_mortgage_interest_stay_rental_costs():
    reply = {"items": [{"amount": 120000, "kind": "wages", "text": "earns $120,000"},
                       {"amount": 30000, "kind": "rental_income", "text": "Rental income received: $30,000"},
                       {"amount": 4000, "kind": "property_tax", "text": "Property taxes: $4,000"},
                       {"amount": 8000, "kind": "mortgage_interest", "text": "Mortgage interest: $8,000"}], "filing_status": "single"}
    q = ("David is single and earns $120,000. He owns a rental house. Rental income received: $30,000. "
         "Property taxes: $4,000. Mortgage interest: $8,000. What is his net rental income?")
    reading, _ = TC.read(q, reply)
    assert reading.inputs.rental_expenses == 12000 and reading.inputs.property_tax == 0
    own, _ = TC.read(q + " He also pays property tax on his own home, his main residence.", reply)
    assert own.inputs.property_tax == 4000


def test_follow_up_explanations_after_the_home_sale_use_python_figures():
    items = [{"text": t, "amount": a, "kind": k, "loss": False, "included": False} for t, a, k in HOME]
    p = {"year": 2025, "filing_status": "married_joint", "items": items, "household": {"home_main_residence": 1}, "total_federal": 1}
    gain = TC.estimate_facts(p, "Will any of the gain be subject to federal capital gains tax?")
    assert "none of the gain is taxed" in gain and "qualified dividends" not in gain
    office = TC.estimate_facts(p, "Can John deduct the $3,000 of home office furniture as a W-2 employee?")
    assert "- Spent $3,000 on office furniture: not deducted" in office and "Adjusted basis" not in office
    saved = TC.estimate_facts(p, "How do the 401(k) and traditional IRA contributions affect taxable income?")
    assert "adjusted gross income of **$196,500**" in saved and "taxable income is **$165,000**" in saved
    assert "saves about **$6,600**" in saved and "the other $8,000 is an excess contribution" in saved
    from src.workflow import tax_tools
    assert "Employee expenses" in tax_tools.current_figures("can a W-2 employee deduct a home office?", 2025)
    import re
    tail = "**In your estimate (2025 rules, computed by Finnie):**\n- a\n- b"
    copied = "No.\n\n" + tail + "\n\nMore."
    assert "In your estimate" not in re.sub(r"\*\*In your estimate[^\n]*\*\*:?\n(?:\s*- [^\n]*(?:\n|$))+", "", copied)


def test_the_answer_to_a_pending_amount_question_is_not_a_change_request():
    class Router:
        model = "x"

        def invoke(self, m):
            return type("R", (), {"content": '{"intents": ["read_only"], "confidence": 0.9}'})()
    llm_module.set_llm(Router())
    s = {"question": "about $12,000 a year", "history": [], "profile": {}, "entities": {},
         "context_in": {"tax": {"items": [], "pending": "mortgage_interest"}}}
    assert N._route(s)["intent"] == ["tax"]
    assert N._route({**s, "context_in": {}})["intent"] == ["read_only"]
