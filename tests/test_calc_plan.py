"""The Calculator's plans (src/core/calc_plan.py): the LLM designs the calculation, Python validates and executes it.
Unit tests drive calc_plan directly with hand-written plans; the graph tests script the LLM's plans and check the guards,
the repair round, the rendered answer and Wolfram|Alpha's part in solve steps (mocked, nothing reaches the API)."""
import copy
import json

import pytest
from langchain_core.messages import AIMessage

from src.core import calc_plan as P
from src.core import llm as llm_module
from src.core import wolfram as W
from src.workflow import calc as CALC
from src.workflow import calc_pipeline as CP
from src.workflow.graph import run_chat

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate", "horizon_years": 10}


def inp(value, unit="number", src="user", means=None):
    return {"value": value, "from": src, "unit": unit, "means": means or unit}


SPLIT_Q = ("You have $10,000 to invest. You put 50% of it into a broad market index fund, 30% into a technology stock, "
           "and the remaining 20% into a crypto fund. How much money goes into each asset?")
SPLIT = {"label": "how the $10,000 is split",
         "inputs": {"T": inp(10000, "money"), "a": inp(0.5, "rate"), "b": inp(0.3, "rate"), "c": inp(0.2, "rate")},
         "steps": [{"name": "index", "label": "index fund", "expr": "T*a", "unit": "money"},
                   {"name": "tech", "label": "technology stock", "expr": "T*b", "unit": "money"},
                   {"name": "crypto", "label": "crypto fund", "expr": "T*c", "unit": "money"}]}

FV_Q = ("Imagine you invest $10,000 in a retirement fund at an average annual interest rate of 8%, compounded annually. "
        "If you do not add any more money, how much will you have in the account after 10 years?")
FV = {"label": "balance after 10 years",
      "inputs": {"P": inp(10000, "money", means="starting amount"), "r": inp(0.08, "rate", means="yearly rate"),
                 "n": inp(1, means="compounding periods a year"), "t": inp(10, "years", means="years")},
      "steps": [{"name": "A", "label": "balance", "expr": "P*(1+r/n)^(n*t)", "unit": "money"},
                {"name": "by_year", "label": "year by year", "vary": {"input": "t", "from": 1, "to": 10}, "of": ["A"]}],
      "checks": [{"when": {"r": 0}, "of": "A", "expect": "P"}, {"when": {"t": 1}, "of": "A", "expect": "P*(1+r/n)^n"}],
      "assumptions": ["the rate is the same every year"]}

RETIRE_Q = ("What is Retirement Income Sustainability? You retire with a $1,000,000 portfolio. You want to withdraw "
            "$45,000 (4.5%) in your first year, adjusting that dollar amount upward every year to match a 3% annual "
            "inflation rate.")
RETIRE = {"label": "how long the savings last",
          "inputs": {"B": inp(1000000, "money", means="savings"), "W": inp(45000, "money", means="first withdrawal"),
                     "g": inp(0.03, "rate", means="inflation"), "r": inp(0.05, "rate", "sample", "yearly return")},
          "steps": [{"name": "years", "label": "years of full withdrawals", "unit": "years", "result": "periods",
                     "simulate": {"start": {"balance": "B", "withdrawal": "W"},
                                  "each": {"balance": "(balance - withdrawal)*(1 + r)", "withdrawal": "withdrawal*(1 + g)"},
                                  "until": "balance < withdrawal", "max": 100}},
                    {"name": "by_return", "label": "depending on the return",
                     "vary": {"input": "r", "values": [0.03, 0.05, 0.08]}, "of": ["years"]}],
          "checks": [{"when": {"r": 0, "g": 0}, "of": "years", "expect": "floor(B/W)"}],
          "assumptions": ["withdrawals are taken at the start of each year"],
          "ignored": [{"number": 4.5, "why": "the same as 45,000 of 1,000,000"}]}

RATE_Q = "If I invest $10,000 and want $15,000 in 5 years, what yearly return do I need?"
RATE = {"label": "yearly return needed",
        "inputs": {"P": inp(10000, "money"), "F": inp(15000, "money"), "t": inp(5, "years")},
        "steps": [{"name": "rate", "label": "yearly return needed", "solve": "P*(1+x)^t = F", "for": "x", "unit": "rate"}],
        "checks": [{"when": {"F": 10000}, "of": "rate", "expect": "0"}]}


def run(plan, q):
    return P.run(plan, q, q)


def without(plan, path, value=None):
    """A copy of a plan with one nested field replaced (or deleted when value is None)."""
    p = copy.deepcopy(plan)
    *keys, last = path
    node = p
    for k in keys:
        node = node[k]
    if value is None:
        del node[last]
    else:
        node[last] = value
    return p


# ---------------------------------------------------------------- numbers in the question
def test_question_numbers_are_scaled_and_skip_account_and_index_names():
    assert P.question_numbers("$1 million, 50k a year at 4.5% in my 401(k) and a 529 plan, like the S&P 500, for 3 years") \
        == [1_000_000, 50_000, 4.5, 3]
    assert P.question_numbers("$1,000,000 then $45,000, adjusting") == [1_000_000, 45_000]


# ---------------------------------------------------------------- execution
def test_arithmetic_split():
    r = run(SPLIT, SPLIT_Q)
    assert (r["values"]["index"], r["values"]["tech"], r["values"]["crypto"]) == (5000, 3000, 2000)


def test_compound_growth_with_a_year_by_year_table_and_checks():
    r = run(FV, FV_Q)
    assert round(r["values"]["A"], 2) == 21_589.25                         # 10,000 × 1.08^10
    rows = r["details"]["by_year"]["rows"]
    assert [t for t, _ in rows] == list(range(1, 11)) and round(rows[0][1]["A"], 2) == 10_800
    assert [c["when"] for c in r["checks"]] == [{"r": 0}, {"t": 1}]


def test_a_simulation_runs_until_its_condition_and_varies_the_sample():
    r = run(RETIRE, RETIRE_Q)
    assert r["values"]["years"] == 28                                      # 28 full withdrawals at a 5% return
    assert r["details"]["by_return"]["rows"] == [(0.03, {"years": 22}), (0.05, {"years": 28}), (0.08, {"years": None})]
    assert r["details"]["years"]["rows"][0] == (0, {"balance": 1_000_000, "withdrawal": 45_000})


def test_a_simulation_for_a_fixed_number_of_periods_returns_a_state_variable():
    q = "I save $200 a month for 12 months. How much do I have?"
    plan = {"label": "savings", "inputs": {"d": inp(200, "money"), "n": inp(12, "months")},
            "steps": [{"name": "total", "label": "total saved", "unit": "money", "result": "balance",
                       "simulate": {"start": {"balance": "0"}, "each": {"balance": "balance + d"}, "periods": "n",
                                    "period": "month"}}],
            "checks": [{"when": {"n": 0}, "of": "total", "expect": "0"}]}
    assert run(plan, q)["values"]["total"] == 2400


def test_solve_finds_an_unknown_that_cant_be_isolated_numerically():
    assert round(run(RATE, RATE_Q)["values"]["rate"], 6) == 0.084472          # (15000/10000)^(1/5) - 1


DEPOSIT_Q = ("A future homebuyer determines they will need a $40,000 down payment to purchase a house exactly 5 years from "
             "today. If they plan to lock their money into a high-yield savings account earning a fixed 4% annual "
             "interest rate, how much money must they deposit as a single lump sum today to reach their goal?")
DEPOSIT = {"label": "deposit needed today",
           "inputs": {"F": inp(40000, "money", means="down payment"), "r": inp(0.04, "rate", means="yearly rate"),
                      "t": inp(5, "years", means="years")},
           "steps": [{"name": "P", "label": "deposit needed today", "expr": "F/(1+r)^t", "satisfies": "P*(1+r)^t = F",
                      "unit": "money"}],
           "checks": [{"when": {"r": 0}, "of": "P", "expect": "F"}]}


def test_a_formula_rearranged_by_the_llm_is_checked_against_its_equation():
    text = CALC.plan_text(run(DEPOSIT, DEPOSIT_Q))
    assert "- From the equation `P*(1+r)^t = F`, rearranged for `P`" in text
    assert "- Formula: `P = F/(1+r)^t`" in text and "**Result: deposit needed today = $32,877.08**" in text
    assert "- Checked: the result solves `P*(1+r)^t = F` ✓" in text
    with pytest.raises(P.PlanError, match="doesn't satisfy P\\*\\(1\\+r\\)\\^t = F .* so the rearranged formula is wrong"):
        run(without(DEPOSIT, ["steps", 0, "expr"], "F*(1+r)^t"), DEPOSIT_Q)          # rearranged the wrong way
    with pytest.raises(P.PlanError, match="must contain 'P'"):
        run(without(DEPOSIT, ["steps", 0, "satisfies"], "F*(1+r)^t = F"), DEPOSIT_Q)


# ---------------------------------------------------------------- guards
@pytest.mark.parametrize("plan,q,why", [
    (without(SPLIT, ["inputs", "a", "value"], 0.55), SPLIT_Q, "input a = 0.55 is marked \"user\" but isn't in the question"),
    (without(SPLIT, ["inputs", "a", "value"], 50), SPLIT_Q, "rates are decimals"),
    (without(SPLIT, ["steps", 0, "expr"], "T*0.5"), SPLIT_Q, "the number 0.5 in a formula must be an input"),
    (without(RETIRE, ["inputs", "g"]), RETIRE_Q, "g not defined"),
    (without(without(without(RETIRE, ["inputs", "g"]), ["steps", 0, "simulate", "each", "withdrawal"], "withdrawal"),
             ["checks", 0, "when"], {"r": 0}), RETIRE_Q, "the question's number 3 isn't used"),
    (without(RETIRE, ["ignored"]), RETIRE_Q, "the question's number 4.5 isn't used"),
    (without(FV, ["checks"]), FV_Q, "add at least one check"),
    (without(FV, ["steps", 0, "expr"], "P*(1+r/n)^(n*t-1)"), FV_Q, "check failed: with t = 1, A = 10000 but P*(1+r/n)^n = 10800"),   # r = 0 alone misses it
    (without(FV, ["steps", 0, "expr"], "P*(1+r)^t"), FV_Q, "input(s) n not used by any step"),
    (without(SPLIT, ["steps", 0, "expr"], "T*a + z"), SPLIT_Q, "z not defined"),
    (without(FV, ["steps", 1, "vary"], {"input": "t", "from": 1, "to": 100}), FV_Q, "1 to 50 values"),
    ("not a plan", FV_Q, "not a JSON plan"),
])
def test_bad_plans_are_rejected_with_a_reason_the_llm_can_act_on(plan, q, why):
    with pytest.raises(P.PlanError) as e:
        run(plan, q)
    assert why in str(e.value)


def test_a_plan_whose_inputs_are_all_samples_needs_the_users_numbers():
    q = "How much will my savings grow?"
    plan = copy.deepcopy(FV)
    for i in plan["inputs"].values():
        i["from"] = "sample"
    with pytest.raises(P.NeedsInput) as e:
        run(plan, q)
    assert e.value.inputs == ["starting amount", "yearly rate", "compounding periods a year", "years"]
    plan["inputs"]["P"].update(value=0, **{"from": "user"})                # a 0 "from the user" changes nothing
    with pytest.raises(P.NeedsInput):
        run(plan, q)


def test_a_simulation_is_capped():
    plan = without(RETIRE, ["steps", 0, "simulate", "max"], 100000)
    r = run(without(plan, ["inputs", "r", "value"], 0.08), RETIRE_Q)
    assert r["values"]["years"] is None and r["details"]["years"]["limit"] == P.MAX_PERIODS


# ---------------------------------------------------------------- the answer
def test_the_answer_shows_inputs_formula_working_checks_and_samples():
    text = CALC.plan_text(run(FV, FV_Q))
    assert "- `r` = 8%: yearly rate" in text and "- Formula: `A = P*(1+r/n)^(n*t)`" in text
    assert "- Working: `10000*(1+0.08/1)^(1*10)`" in text and "**Result: balance = $21,589.25**" in text
    assert "| 10 years | $21,589.25 |" in text and "Checked: with `r = 0`, `A` equals `P` ✓" in text
    assert "Assumes: the rate is the same every year." in text and "(sample)" not in text
    text = CALC.plan_text(run(RETIRE, RETIRE_Q))
    assert "- `r` = 5%: yearly return **(sample)**" in text and "Values marked (sample) are illustrative" in text
    assert "**Step 1: years of full withdrawals**" in text and "**Result: years of full withdrawals = 28 years**" in text
    assert "| 8% | more than 100 years |" in text and "Not used: 4.5 (the same as 45,000 of 1,000,000)." in text
    assert "| 0 | $1,000,000 | $45,000 |" in text


# ---------------------------------------------------------------- through the graph
class PlanLLM:
    """Routes to calc and answers the plan prompt with each scripted reply in turn (the second is the repair)."""
    model = "plan"

    def __init__(self, *plans, judge=(), confirm=None):
        self.plans, self.calc_prompts = [p if isinstance(p, str) else json.dumps(p) for p in plans], []
        self.verdicts, self.judge_prompts = list(judge), []
        self.confirm, self.confirm_prompts = confirm, []

    def invoke(self, messages):
        system, user = messages[0][1], messages[1][1]
        if "You are the router" in system:
            return AIMessage(content='{"intents": ["calc"], "confidence": 0.9}')
        if "You are the proofreader" in system:
            return AIMessage(content=user.removeprefix("Message: "))
        if "couldn't complete the user's calculation" in system:
            self.confirm_prompts.append(user)
            return AIMessage(content=json.dumps(self.confirm or {}))
        if "You review a calculation plan" in system:
            self.judge_prompts.append(user)
            return AIMessage(content=json.dumps(self.verdicts[min(len(self.judge_prompts), len(self.verdicts)) - 1]))
        if "finance calculator" in system:
            self.calc_prompts.append(user)
            return AIMessage(content=self.plans[min(len(self.calc_prompts), len(self.plans)) - 1])
        return AIMessage(content="{}")


def ask(q, *plans, judge=(), confirm=None):
    llm = PlanLLM(*plans, judge=judge, confirm=confirm)
    llm_module.set_llm(llm)
    return run_chat(q, history=[], profile=PROFILE, holdings=[], db=None), llm


def test_a_plan_is_executed_and_shown_verbatim():
    s, llm = ask(SPLIT_Q, SPLIT)
    out = s["agent_outputs"]["calc"]
    assert out["status"] == "answered" and out["verbatim"] and len(llm.calc_prompts) == 1
    assert "**Result: index fund = $5,000**" in out["content"] and "**Result: crypto fund = $2,000**" in out["content"]
    assert any(t.startswith("calc (LLM plan): how the $10,000 is split: index = 5000; tech = 3000") for t in s["trace"])


def test_a_rejected_plan_is_repaired_once_with_the_error():
    dropped = without(without(without(RETIRE, ["inputs", "g"]), ["steps", 0, "simulate", "each", "withdrawal"],
                              "withdrawal"), ["checks", 0, "when"], {"r": 0})
    s, llm = ask(RETIRE_Q, dropped, RETIRE)
    assert len(llm.calc_prompts) == 2 and "the question's number 3 isn't used" in llm.calc_prompts[1]
    assert s["agent_outputs"]["calc"]["status"] == "answered"
    assert any("repaired after: the question's number 3 isn't used" in t for t in s["trace"])


def test_a_plan_rejected_twice_asks_the_user_to_confirm_what_they_want():
    reply = {"message": "You want to split $10,000 between an index fund and a crypto fund. What share goes to each?",
             "readings": ["How much goes into each fund if I put half of $10,000 in the index fund?",
                          "How much goes into each fund if I put 70% of $10,000 in the index fund?"]}
    s, llm = ask(SPLIT_Q, without(SPLIT, ["steps", 0, "expr"], "T*0.5"), "no json at all", confirm=reply)
    out = s["agent_outputs"]["calc"]
    assert out["status"] == "need_info" and out["content"] == reply["message"] and len(llm.calc_prompts) == 2
    assert out["choices"] == reply["readings"]                     # kept: the verifier doesn't replace them
    assert SPLIT_Q in llm.confirm_prompts[0] and "not a JSON plan" in llm.confirm_prompts[0]
    assert any("rejected twice" in t and t.endswith("→ confirm with the user") for t in s["trace"])
    assert out["content"] != CALC.ASK


def test_without_a_confirmation_reply_the_user_is_asked_plainly():
    s, _ = ask(SPLIT_Q, "no json at all")
    out = s["agent_outputs"]["calc"]
    assert out["status"] == "need_info" and out["content"].startswith("I couldn't work out which calculation")
    assert "yearly rate" not in out["content"]


def test_the_confirmation_built_without_the_llm_restates_what_was_understood():
    llm_module.set_llm(PlanLLM())
    text, readings = CP.confirm(SPLIT_Q, {"restated": "The user wants to split $10,000 between two funds.",
                                          "given": [{"value": "10,000", "means": "the amount"}]}, ["not a JSON plan"])
    assert text.startswith("I couldn't complete this calculation. I read your question as: you want to split "
                           "$10,000 between two funds, using 10,000 (the amount). Is that right?") and readings == []


def test_wolfram_is_never_called_even_with_a_key():
    calls = []
    W.set_wolfram_client(lambda q: calls.append(q) or "")
    s, _ = ask(DEPOSIT_Q, DEPOSIT)
    assert calls == [] and s["sources"] == []
    assert "**Result: deposit needed today = $32,877.08**" in s["agent_outputs"]["calc"]["content"]


def test_several_parts_with_a_sample_rate():
    q = ("If you decide to save $600 every month and split it equally into 3 different retirement accounts, how much "
         "money goes into each account each month? And how much is the growth with x% interest?")
    plan = {"label": "the split and its growth",
            "inputs": {"S": inp(600, "money"), "k": inp(3), "r": inp(0.06, "rate", "sample", "yearly return"),
                       "t": inp(20, "years", "sample", "years")},
            "steps": [{"name": "each", "label": "each account per month", "expr": "S/k", "unit": "money"},
                      {"name": "grown", "label": "each account after the years", "unit": "money", "result": "balance",
                       "simulate": {"start": {"balance": "0"}, "each": {"balance": "balance*(1 + r/12) + each"},
                                    "periods": "12*t", "period": "month"}}],
            "checks": [{"when": {"r": 0}, "of": "grown", "expect": "each*12*t"}]}
    s, _ = ask(q, plan)
    text = s["agent_outputs"]["calc"]["content"]
    assert "**Result: each account per month = $200**" in text
    assert "**Result: each account after the years = $92,408.18**" in text   # $200 a month at 6% for 20 years
    assert "- `r` = 6%: yearly return **(sample)**" in text


# ---------------------------------------------------------------- fixes from the first live run
def test_a_check_at_zero_rate_is_taken_as_the_limit_for_a_formula_dividing_by_the_rate():
    q = "What's the monthly payment on a $300,000 mortgage at 6.5% for 30 years?"
    plan = {"label": "mortgage payment", "inputs": {"P": inp(300000, "money"), "r": inp(0.065, "rate"), "t": inp(30, "years")},
            "steps": [{"name": "M", "label": "monthly payment", "expr": "P*(r/12)/(1-(1+r/12)^(-12*t))", "unit": "money"}],
            "checks": [{"when": {"r": 0}, "of": "M", "expect": "P/(12*t)"}]}
    r = run(plan, q)
    assert round(r["values"]["M"], 2) == 1896.20 and r["checks"][0]["when"] == {"r": 0}
    with pytest.raises(P.PlanError, match="check failed"):              # the limit still catches a wrong expectation
        run(without(plan, ["checks", 0, "expect"], "P/t"), q)


def test_irr_with_money_paid_out_negative_and_small_exponents():
    q = "What's the IRR if I invest $10,000 and get back $3,000, $4,000 and $5,000 over three years?"
    plan = {"label": "internal rate of return",
            "inputs": [{"name": "a", "value": -10000, "unit": "money"}, {"name": "b", "value": 3000, "unit": "money"},
                       {"name": "c", "value": 4000, "unit": "money"}, {"name": "d", "value": 5000, "unit": "money"}],
            "steps": [{"name": "irr", "label": "IRR", "solve": "a + b/(1+x) + c/(1+x)^2 + d/(1+x)^3 = 0", "for": "x",
                       "unit": "rate"}],
            "checks": [{"when": {"b": 0, "c": 0, "d": 10000}, "of": "irr", "expect": "0"}],
            "ignored": [{"number": 3, "why": "the three years are the three cash flows"}]}
    assert round(run(plan, q)["values"]["irr"], 5) == 0.08896


def test_a_solve_that_divides_by_the_rate_is_checked_at_the_limit_too():
    q = "I owe $5,000 on a credit card at 18% APR and pay $200 a month. How many months until it's paid off?"
    plan = {"label": "months to pay off", "inputs": {"B": inp(5000, "money"), "r": inp(0.18, "rate"),
                                                     "p": inp(-200, "money"), "n": inp(12)},
            "steps": [{"name": "months", "label": "months", "solve": "B*(1 + r/n)^x + p*((1 + r/n)^x - 1)/(r/n) = 0",
                       "for": "x", "unit": "months"}],
            "checks": [{"when": {"r": 0}, "of": "months", "expect": "-B/p"}]}
    assert round(run(plan, q)["values"]["months"], 2) == 31.57


def test_a_simulation_helper_is_computed_each_period_before_the_state():
    q = ("A $5,000 credit card balance at 20% APR, paying 3% of the balance each month: how many years to pay it off "
         "and how much interest?")
    plan = {"label": "minimum payments",
            "inputs": {"B": inp(5000, "money"), "a": inp(0.2, "rate"), "m": inp(0.03, "rate"),
                       "s": inp(1, "money", "sample", "stop below this balance")},
            "steps": [{"name": "months", "label": "months", "result": "periods", "unit": "months",
                       "simulate": {"start": {"balance": "B", "paid": "0"}, "period": "month", "max": 1200,
                                    "each": {"interest": "balance*a/12", "payment": "m*(balance + interest)",
                                             "balance": "balance + interest - payment", "paid": "paid + interest"},
                                    "until": "balance < s"}},
                      {"name": "years", "label": "years", "expr": "months/12", "unit": "years"}],
            "checks": [{"when": {"a": 0, "m": 1}, "of": "months", "expect": "1"}]}
    r = run(plan, q)
    assert r["values"]["months"] == 612 and r["values"]["years"] == 51               # checked with a plain loop
    assert set(r["details"]["months"]["rows"][1][1]) == {"balance", "paid"}                # helpers aren't state


def test_the_same_plan_sent_back_is_asked_for_once_more():
    bad = without(SPLIT, ["steps", 0, "expr"], "T*0.5")
    s, llm = ask(SPLIT_Q, bad, bad, SPLIT)
    assert len(llm.calc_prompts) == 3 and llm.calc_prompts[2].startswith("You sent the SAME plan again")
    assert s["agent_outputs"]["calc"]["status"] == "answered"



# ---------------------------------------------------------------- the judge (a check and its plan disagree)
WRONG_CHECK = without(FV, ["checks"], [{"when": {"r": 0}, "of": "A", "expect": "P"},
                                       {"when": {"t": 1}, "of": "A", "expect": "2*P"}])


def test_a_check_the_judge_finds_wrong_is_set_aside_and_shown():
    s, llm = ask(FV_Q, WRONG_CHECK, judge=[{"reasoning": "One year at 8% gives 10,800, not double.", "wrong": "check"}])
    out = s["agent_outputs"]["calc"]
    assert out["status"] == "answered" and len(llm.calc_prompts) == 1 and len(llm.judge_prompts) == 1
    assert "the check expects A = 2*P = 20000; the plan computed A = 10800" in llm.judge_prompts[0]
    assert "**Result: balance = $21,589.25**" in out["content"]
    assert ("Set aside: a self-check with `t = 1` expected `2*P` = 20000, but the plan gives 10800. A separate review "
            "judged the check wrong, not the plan: One year at 8% gives 10,800, not double.") in out["content"]
    assert "Checked: with `r = 0`, `A` equals `P` ✓" in out["content"]               # the other check still ran
    assert any("1 check(s) set aside by the judge" in t for t in s["trace"])


def test_a_plan_the_judge_finds_wrong_is_repaired_with_its_reason():
    wrong_plan = without(FV, ["steps", 0, "expr"], "P*(1+r/n)^(n*t-1)")
    s, llm = ask(FV_Q, wrong_plan, FV, judge=[{"reasoning": "After one year it should be 10,800.", "wrong": "plan"}])
    assert "A reviewer judged the plan: After one year it should be 10,800." in llm.calc_prompts[1]
    assert s["agent_outputs"]["calc"]["status"] == "answered" and "Set aside" not in s["agent_outputs"]["calc"]["content"]


def test_an_unsure_judge_leaves_it_to_the_repair_round_then_asks():
    s, llm = ask(FV_Q, WRONG_CHECK, WRONG_CHECK, WRONG_CHECK, judge=[{"reasoning": "?", "wrong": "unsure"}])
    out = s["agent_outputs"]["calc"]
    assert out["status"] == "need_info" and len(llm.judge_prompts) == 2           # once per plan, then the cap
    assert "A reviewer judged it unclear" in llm.calc_prompts[1]


def test_the_judge_is_called_at_most_twice():
    three = without(FV, ["checks"], [{"when": {"r": 0}, "of": "A", "expect": "2*P"},
                                     {"when": {"t": 1}, "of": "A", "expect": "3*P"},
                                     {"when": {"t": 0}, "of": "A", "expect": "4*P"}])
    s, llm = ask(FV_Q, three, FV, judge=[{"reasoning": "wrong check", "wrong": "check"}])
    assert len(llm.judge_prompts) == 2 and len(llm.calc_prompts) == 2              # third failure → repair
    assert s["agent_outputs"]["calc"]["status"] == "answered"


def test_a_small_number_is_allowed_as_an_exponent_but_not_as_a_hidden_assumption():
    q = "A $5,000 credit card balance at 20% APR, paying 3% of the balance each month: how long to pay it off?"
    plan = {"label": "payoff", "inputs": {"B": inp(5000, "money"), "a": inp(0.2, "rate"), "m": inp(0.03, "rate")},
            "steps": [{"name": "months", "label": "months", "result": "periods", "unit": "months",
                       "simulate": {"start": {"balance": "B"}, "period": "month", "max": 1200,
                                    "each": {"payment": "max(m*balance, 10)", "balance": "balance*(1 + a/12) - payment"},
                                    "until": "balance < payment"}}],
            "checks": [{"when": {"B": 0}, "of": "months", "expect": "0"}]}
    with pytest.raises(P.PlanError, match="the number 10 in a formula must be an input, marked \"sample\""):
        run(plan, q)
    assert P._constants("a + b/(1+x)^3 - 2*c") == [(1.0, False), (3.0, True), (2.0, False)]


def test_two_steps_reading_one_simulation_print_its_table_once():
    q = "A $5,000 credit card balance at 20% APR, paying 3% of the balance each month: how long, and how much interest?"
    sim = {"start": {"balance": "B", "paid": "0"}, "period": "month", "max": 1200, "until": "balance < s",
           "each": {"interest": "balance*a/12", "balance": "balance + interest - m*(balance + interest)",
                    "paid": "paid + interest"}}
    plan = {"label": "payoff", "inputs": {"B": inp(5000, "money"), "a": inp(0.2, "rate"), "m": inp(0.03, "rate"),
                                          "s": inp(1, "money", "sample", "stop below this balance")},
            "steps": [{"name": "months", "label": "months", "result": "periods", "unit": "months", "simulate": sim},
                      {"name": "interest", "label": "interest paid", "result": "paid", "unit": "money", "simulate": sim}],
            "checks": [{"when": {"B": 0}, "of": "months", "expect": "0"}]}
    text = CALC.plan_text(run(plan, q))
    assert text.count("| Month | balance | paid |") == 1 and "The same simulation as step 1" in text
    assert "**Result: interest paid = $6,022.90**" in text and "| 612 | $0.99 | $6,022.90 |" in text
    assert len([ln for ln in text.splitlines() if ln.startswith("| ") and ln[2].isdigit()]) <= 12


def test_setting_aside_every_check_is_not_enough_to_answer():
    only_wrong = without(FV, ["checks"], [{"when": {"t": 1}, "of": "A", "expect": "2*P"}])
    s, llm = ask(FV_Q, only_wrong, FV, judge=[{"reasoning": "wrong check", "wrong": "check"}])
    assert "every check was set aside as wrong" in llm.calc_prompts[1]
    assert s["agent_outputs"]["calc"]["status"] == "answered" and "Set aside" not in s["agent_outputs"]["calc"]["content"]


def test_a_number_in_the_question_the_plan_reproduces_counts_as_used():
    q = "My $15,000 loan drops to $10,000 after a $5,000 payment. What is left?"
    plan = {"label": "balance", "inputs": {"B": inp(15000, "money"), "P": inp(5000, "money")},
            "steps": [{"name": "left", "label": "balance left", "expr": "B - P", "unit": "money"}]}
    assert run(plan, q)["values"]["left"] == 10000
    with pytest.raises(P.PlanError, match="the question's number 10000 isn't used"):
        run(without(plan, ["inputs", "P", "value"], 6000), q.replace("$5,000", "$6,000"))   # computes 9,000


def test_a_simulation_that_never_stops_has_no_final_state_value():
    q = "I owe $10,000 at 6.5% and pay $170.32 a month. How much interest do I pay in total?"
    plan = {"label": "interest", "inputs": {"B": inp(10000, "money"), "r": inp(0.065, "rate"), "p": inp(170.32, "money")},
            "steps": [{"name": "interest", "label": "total interest", "result": "paid", "unit": "money",
                       "simulate": {"start": {"balance": "B", "paid": "0"}, "period": "month", "max": 1200,
                                    "until": "balance <= 0",
                                    "each": {"i": "balance*r/12", "balance": "balance + i + p", "paid": "paid + i"}}}],
            "checks": [{"when": {"B": 0}, "of": "interest", "expect": "0"}]}                  # + p: the debt grows
    with pytest.raises(P.PlanError, match="ran 1200 months without reaching `balance <= 0`"):
        run(plan, q)
    fixed = without(plan, ["steps", 0, "simulate", "each", "balance"], "balance + i - min(p, balance + i)")
    assert round(run(fixed, q)["values"]["interest"], 2) == 2068.26                          # the hand-computed reference


def test_a_percentage_added_to_one_is_a_unit_error():
    q = "If my investments return 7% and inflation is 3%, what is my real return?"
    plan = {"label": "real return", "inputs": {"i": inp(7, "percent"), "p": inp(3, "percent")},
            "steps": [{"name": "real", "label": "real return", "expr": "(1+i)/(1+p) - 1", "unit": "rate"}]}
    with pytest.raises(P.PlanError, match="i, p is a percentage|p, i is a percentage"):
        run(plan, q)
    rule72 = {"label": "doubling", "inputs": {"r": inp(7, "percent")},
              "steps": [{"name": "t", "label": "years to double", "expr": "72/r", "unit": "years", "sourced": True}]}
    assert round(run(rule72, "How long to double at 7%?")["values"]["t"], 2) == 10.29


def test_the_plan_path_answers_an_example_request_with_samples_only():
    samples = copy.deepcopy(FV)
    for i in samples["inputs"].values():
        i["from"] = "sample"
    s, llm = ask("Show me an example of how compound interest grows", samples)
    out = s["agent_outputs"]["calc"]
    assert out["status"] == "answered" and out["content"].startswith("**Worked example: balance after 10 years**")
    assert "worked example and may give no numbers" in llm.calc_prompts[0]


CAPM_Q = "If a stock has a beta of 1.2, what would its expected return be if the market return is 8%?"


def test_a_percentage_mixed_with_a_decimal_rate_is_rejected():
    plan = {"label": "expected return", "inputs": {"beta": inp(1.2), "rm": inp(8, "percent"),
                                                   "rf": inp(0.03, "rate", "sample")},
            "steps": [{"name": "r", "label": "expected return", "expr": "rf + beta*(rm - rf)", "unit": "rate"}]}
    with pytest.raises(P.PlanError) as e:
        run(plan, CAPM_Q)
    assert "rm is a percentage (unit \"percent\") added to or subtracted from a rate" in str(e.value)
    plan["inputs"]["rm"] = inp(0.08, "rate")
    assert run(plan, CAPM_Q)["values"]["r"] == pytest.approx(0.09)


def test_a_beta_marked_as_a_rate_is_told_to_be_a_number():
    plan = {"label": "expected return", "inputs": {"beta": inp(1.2, "rate"), "rm": inp(0.08, "rate"),
                                                   "rf": inp(0.03, "rate", "sample")},
            "steps": [{"name": "r", "label": "expected return", "expr": "rf + beta*(rm - rf)", "unit": "rate"}]}
    with pytest.raises(P.PlanError) as e:
        run(plan, CAPM_Q)
    assert "keep 1.2 and make its unit \"number\"" in str(e.value)


def test_a_result_whose_unit_doesnt_match_its_inputs_is_rejected():
    def plan(unit, rm, rf, rm_unit, rf_unit):
        return {"label": "x", "inputs": {"beta": inp(1.2), "Rm": inp(rm, rm_unit), "Rf": inp(rf, rf_unit, "sample")},
                "steps": [{"name": "er", "label": "expected return", "expr": "Rf + beta*(Rm - Rf)", "unit": unit}]}
    with pytest.raises(P.PlanError) as e:
        run(plan("rate", 8, 2, "percent", "percent"), CAPM_Q)            # would show 920%
    assert "its unit is \"rate\" (a decimal) but it's computed from percentages" in str(e.value)
    with pytest.raises(P.PlanError) as e:
        run(plan("percent", 0.08, 0.02, "rate", "rate"), CAPM_Q)         # would show 0.09%
    assert "its unit is \"percent\" but it's computed from rates" in str(e.value)
    assert run(plan("percent", 8, 2, "percent", "percent"), CAPM_Q)["values"]["er"] == pytest.approx(9.2)
