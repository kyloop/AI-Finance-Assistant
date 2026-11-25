"""The Tax agent's step-3 tools (src/workflow/tax_whatif.py, maths in src/core/income_tax.py): what an extra amount does,
Roth vs traditional, a sale's gain; and the model picking the tool (nodes._pick_tax_tool). Figures worked by hand from
the 2026 tables."""
import pytest

from src.core import income_tax as T
from src.core import llm as llm_module
from src.workflow import nodes as N
from src.workflow import tax_whatif as TW
from tests.test_income_tax import kevin_estimate

KEVIN_INPUTS = T.TaxInputs(wages=205_000, long_term_gains=30_000, property_tax=10_000)


# ---------------------------------------------------------------- maths
def test_a_raise_is_taxed_at_the_top_bracket_plus_medicare():
    m = T.marginal_effect(KEVIN_INPUTS, {"wages": 10_000})
    # 24% income tax (still in the 24% bracket; NIIT unchanged: investment income is already below the excess) + 1.45% + 0.9%
    assert m["diff"]["income_tax"] == pytest.approx(2_400) and m["diff"]["payroll"] == pytest.approx(145 + 90)
    assert m["diff"]["total_federal"] == pytest.approx(2_635) and m["share"] == pytest.approx(0.2635)


def test_a_traditional_contribution_saves_todays_rate_and_roth_gets_the_after_tax_pay():
    c = T.compare_accounts(KEVIN_INPUTS, 10_000, 20, 0.06)
    # 24% on the slice, plus the NIIT it removes: AGI 225,000 is 25,000 over 200,000, below the 30,000 of gains → 3.8% of 5,000
    assert c["tax_saved_now"] == pytest.approx(2_400 + 190) and c["take_home_cost"] == pytest.approx(7_410)
    assert c["traditional_balance"] == pytest.approx(10_000 * 1.06 ** 20) and c["roth_balance"] == pytest.approx(7_410 * 1.06 ** 20)
    at_today = next(r for r in [*c["rows"], {"rate": c["rate_now"], "traditional": c["traditional_balance"] * (1 - c["rate_now"])}]
                    if r["rate"] == c["rate_now"])
    assert at_today["traditional"] == pytest.approx(c["roth_balance"])        # same rate then and now: same result


def test_a_short_term_gain_is_taxed_like_pay_and_a_wash_sale_loss_is_not_deducted():
    g = T.capital_gain(8_000, 5_000, held_more_than_a_year=False, inp=KEVIN_INPUTS)
    assert g["gain"] == 3_000 and g["effect"]["diff"]["total_federal"] == pytest.approx(0.24 * 3_000 + 0.038 * 3_000)
    w = T.capital_gain(2_000, 5_000, held_more_than_a_year=True, rebought_within_30_days=True, inp=KEVIN_INPUTS)
    assert w["wash_sale"] and w["effect"] is None


# ---------------------------------------------------------------- tools as the user sees them
def test_what_a_raise_does_measured_against_the_last_estimate():
    text, note = TW.marginal_effect({"amount": 10000, "kind": "wages"}, "What if I get a $10,000 raise?", kevin_estimate().profile)
    assert "Measured against your last estimate (single, assumed)." in text
    assert "Federal taxes go from $58,031 to **$60,666** (+$2,635)" in text
    assert "Of the extra $10,000, **$2,635** (26.4%) goes to federal tax and you keep $7,365." in text


def test_a_gift_only_helps_if_it_makes_itemizing_worth_it():
    text, _ = TW.marginal_effect({"amount": 3000, "kind": "charity"}, "What if I give $3,000 to charity?", kevin_estimate().profile)
    assert "the standard deduction is still larger, so it changes nothing" in text      # 10,000 + 3,000 < 16,100


def test_a_what_if_amount_must_be_the_users():
    with pytest.raises(TW.Refused, match="not an amount you gave"):
        TW.marginal_effect({"amount": 15000, "kind": "wages"}, "What if I get a $10,000 raise?", kevin_estimate().profile)
    with pytest.raises(TW.Refused, match="no income"):
        TW.marginal_effect({"amount": 10000, "kind": "wages"}, "What if I get a $10,000 raise?", None)


def test_roth_vs_traditional_from_the_users_income_with_stated_assumptions():
    text, note = TW.compare_accounts({"contribution": 10000, "base_income": 120000},
                                     "How do Roth and traditional compare for $10,000 if I earn $120,000?", None)
    assert "Measured against $120,000 of wages, single (assumed)." in text
    assert "your income tax drops by **$2,200**" in text and "take-home pay falls by only $7,800" in text     # 22% bracket
    assert "| 22% | $25,016 | $25,016 | about the same |" in text                                           # 20 years at 6%
    assert "**Assumed:** 20 years until you withdraw; a steady 6% yearly return (moderate risk profile)." in text


def test_years_and_return_are_used_only_when_the_user_gives_them():
    q = "Roth or traditional for $10,000 over 30 years at 7% if I earn $120,000?"
    text, note = TW.compare_accounts({"contribution": 10000, "base_income": 120000, "years": 30, "annual_return_pct": 7}, q, None)
    assert "Growth over 30 years at 7% a year" in text and "**Assumed:**" not in text
    text, _ = TW.compare_accounts({"contribution": 10000, "base_income": 120000, "years": 25}, q.replace(" over 30 years", ""), None)
    assert "Growth over 20 years" in text                                                 # 25 isn't in the message


def test_a_sale_from_shares_and_prices_with_the_users_income():
    q = "I bought 100 shares at $50 and sold them at $80 after 8 months. I earn $90,000. How much tax do I owe on that?"
    text, note = TW.capital_gain({"shares": 100, "buy_price": 50, "sell_price": 80, "held_more_than_a_year": False,
                                  "base_income": 90000}, q, None)
    assert "100 × $80 − 100 × $50 = $8,000 − $5,000 = **$3,000** gain" in text and "- Short-term" in text
    assert "(+$660): 22.0% of the gain." in text                                             # 90,000 − 16,100 is in the 22% bracket
    with pytest.raises(TW.Refused, match="not a price you gave"):
        TW.capital_gain({"shares": 100, "buy_price": 55, "sell_price": 80}, q, None)


def test_a_loss_bought_back_within_30_days_is_a_wash_sale():
    q = "I paid $5,000 and sold for $2,000, then bought the same shares back a week later."
    text, _ = TW.capital_gain({"cost_basis": 5000, "proceeds": 2000, "rebought_within_30_days": True}, q, None)
    assert "**$-3,000** loss" in text or "**-$3,000** loss" in text
    assert "**Step 3. Wash sale**" in text and "$3,000 lowers the gain when you sell them" in text


# ---------------------------------------------------------------- the model picks the tool
class ToolLLM:
    """Replies to bind_tools(...).invoke with one tool call; ignores other calls."""
    model = "scripted"

    def __init__(self, name, args):
        self.call = {"name": name, "args": args, "id": "c1"}

    def bind_tools(self, specs):
        assert {s["function"]["name"] for s in specs} >= {"marginal_effect", "compare_accounts", "capital_gain"}
        return self

    def invoke(self, messages):
        return type("R", (), {"tool_calls": [self.call], "content": ""})()


def tax_state(q, **kw):
    return {"question": q, "original_question": q, "history": [], "profile": {}, "entities": {"wiki_query": q}, **kw}


def test_the_tax_agent_runs_the_tool_the_model_picks():
    llm_module.set_llm(ToolLLM("compare_accounts", {"contribution": 10000, "base_income": 120000}))
    res = N.tax_node(tax_state("How do Roth and traditional compare for $10,000 if I earn $120,000?"), {})
    out = res["agent_outputs"]["tax"]
    assert out["verbatim"] and out["explains_itself"] and out["origin"] == "tax_tools"
    assert out["content"].startswith("**Traditional vs Roth for $10,000 of your pay**")
    assert res["trace"][0] == "tax: model picked compare_accounts(contribution=10000, base_income=120000)"


def test_an_invented_argument_falls_back_to_the_usual_path():
    llm_module.set_llm(ToolLLM("compare_accounts", {"contribution": 12000}))
    res = N.tax_node(tax_state("How does a Roth IRA compare with a traditional one?"), {})
    assert any("refused (contribution 12,000 is not an amount you gave)" in t for t in res["trace"])
    assert res["agent_outputs"]["tax"].get("origin") != "tax_tools"


def test_tax_figures_route_to_the_tax_agent_alone():
    s = {"question": "How do Roth and traditional 401(k) compare for $10,000 if I earn $120,000?"}
    assert N._with_income_tax(["tax", "qa", "calc"], s) == ["tax"]
    assert N._with_income_tax(["tax", "qa"], {"question": "How does a Roth IRA work?"}) == ["tax", "qa"]   # no figures


# ---------------------------------------------------------------- this year's figures and the pages behind an estimate
def test_current_figures_match_the_question():
    from src.workflow import tax_tools as TT
    text = TT.current_figures("How much can I put in my 401(k) and a Roth IRA?")
    assert text.startswith("**Current 2026 figures (IRS)")
    assert "401(k)/403(b)/457/TSP: $24,500 a year, plus $8,000 catch-up at 50+ ($11,250 at ages 60-63)" in text
    assert "IRA (traditional and Roth combined): $7,500, plus $1,100 at 50+" in text
    assert "between $153,000 and $168,000 single, $242,000 and $252,000 married filing jointly" in text
    assert "SALT deduction cap: $40,400" in TT.current_figures("How does the SALT deduction work?")
    assert "$19,000 per recipient" in TT.current_figures("What is the gift tax limit?")
    assert "up to $250,000 of gain tax-free ($500,000 married filing jointly)" in TT.current_figures("Is selling my home taxable?")
    assert TT.current_figures("What is an ETF?") == ""


def test_the_tax_agent_puts_current_figures_before_the_pages():
    from src.workflow import tools
    tools.set_kb_searcher(lambda q, k=None: [{"score": 0.8, "doc_id": "gift-tax", "doc_title": "Gift tax in the United States",
                                               "section": "(lead)", "text": "The annual exclusion was $15,000 in 2018.",
                                               "source_url": "https://en.wikipedia.org/wiki/Gift_tax", "category": "taxes-and-accounts",
                                               "piece": 0, "pieces": 1, "tokens": 9, "section_tokens": 9}])
    q = "What is the gift tax limit?"
    out = N.tax_node({"question": q, "original_question": q, "history": [], "profile": {}, "entities": {"wiki_query": q}}, {})
    content = out["agent_outputs"]["tax"]["content"]
    assert content.index("$19,000 per recipient") < content.index("was $15,000 in 2018")


def test_an_estimate_links_the_pages_of_what_it_used_and_asks_about_a_student_dependent():
    from src.workflow import tax_calc as TC
    items = [{"text": "I earn $85,000", "amount": 85000, "kind": "wages", "loss": False},
             {"text": "$6,000 of tuition for my son's first year of college", "amount": 6000, "kind": "college_expenses", "loss": False}]
    r, _ = TC.reading_from(items, "single")
    est = TC.estimate(r)
    assert est.topics[0] == "American Opportunity Tax Credit"
    assert "If your student is your dependent ($500 credit for other dependents): federal taxes would be" in est.text
    assert est.choices == TC.QUESTIONS["dependent"][1]                    # filing status was given, so this is the question


def test_a_tax_rule_question_goes_to_the_tax_agent_not_qa():
    s = {"question": "What is the SALT deduction cap?"}
    assert N._tax_to_tax_agent(["qa"], s) == ["tax"]
    assert N._tax_to_tax_agent(["qa", "market"], {"question": "How are AAPL dividends taxed?"}) == ["tax", "market"]
    assert N._tax_to_tax_agent(["qa"], {"question": "What is an ETF?"}) == ["qa"]
