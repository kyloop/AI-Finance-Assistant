"""The calculator's steps (src/workflow/calc_pipeline.py): understand, define, find the equation in the knowledge base and
on the web and cross-check it, fill the variables; Python computes and quotes the sources. Every LLM step is scripted and
both searches are fakes, so nothing leaves the machine."""
import json

import pytest
from langchain_core.messages import AIMessage

from src.core import calc_plan as PLAN
from src.core import llm as llm_module
from src.core import tavily as T
from src.workflow import tools
from src.workflow.graph import run_chat

PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate", "horizon_years": 10}
Q = ("A future homebuyer determines they will need a $40,000 down payment to purchase a house exactly 5 years from "
     "today. If they plan to lock their money into a high-yield savings account earning a fixed 4% annual interest "
     "rate, how much money must they deposit as a single lump sum today to reach their goal?")

KB_TEXT = ("The most commonly applied model of present valuation uses compound interest. The standard formula is: "
           "$PV={\\frac {C}{(1+i)^{n}}}\\,$ Where $\\,C\\,$ is the future amount of money that must be discounted, "
           "$\\,n\\,$ is the number of compounding periods, $\\,i\\,$ is the interest rate for one compounding period.")
WEB_TEXT = "| Present Value | $$PV = \\frac{FV}{(1 + i)^N}$$ | Formulas to Solve for Variables in Lump Sum Problems"
KB_CHUNK = {"doc_title": "Present value", "section": "Present value of a lump sum", "text": KB_TEXT, "score": 0.85,
            "source_url": "https://en.wikipedia.org/wiki/Present_value"}
WEB_RESULT = {"title": "Lump Sum Formulas", "url": "https://tvmcalcs.com/tvm-math/lump-sum-formulas", "content": WEB_TEXT,
              "score": 0.9}

UNDERSTAND = {"restated": "How much to deposit today to have $40,000 in 5 years at 4%", "given": [], "find": ["deposit"]}
DEFINE = {"targets": [{"name": "P", "label": "deposit needed today", "unit": "money", "kind": "formula",
                       "concept": "present value of a lump sum", "kb_query": "present value formula",
                       "web_query": "present value lump sum formula"}],
          "assumptions": ["interest is added once a year"]}
KB_EQ = {"found": True, "passage": 1, "quote": "The standard formula is: $PV={\\frac {C}{(1+i)^{n}}}\\,$",
         "equation": "PV = C/(1+i)^n", "variables": {"PV": "present value", "C": "future amount", "i": "rate per period",
                                                     "n": "number of periods"}, "for": "PV", "formula": "C/(1+i)^n"}
WEB_EQ = {"found": True, "passage": 1, "quote": "$$PV = \\frac{FV}{(1 + i)^N}$$", "equation": "PV = FV/(1+i)^N",
          "variables": {"PV": "present value", "FV": "future value", "i": "rate", "N": "periods"}, "for": "PV",
          "formula": "FV/(1+i)^N"}
VARIABLES = {"inputs": {"C": {"value": 40000, "from": "user", "unit": "money", "means": "down payment needed"},
                        "i": {"value": 0.04, "from": "user", "unit": "rate", "means": "yearly interest rate"},
                        "n": {"value": 5, "from": "user", "unit": "years", "means": "years until the purchase"}}}
MATCH = {"reasoning": "Both discount a single future amount with compound interest.", "match": True}


class StepLLM:
    """Scripted replies per calculator step; extraction replies by source (knowledge base or web) and round."""
    model = "steps"

    def __init__(self, understand=UNDERSTAND, define=DEFINE, kb=(KB_EQ,), web=(WEB_EQ,), match=(MATCH,),
                 refine=None, variables=(VARIABLES,), plan=None):
        self.script = {"understand": [understand], "define": [define], "kb": list(kb), "web": list(web),
                       "match": list(match), "refine": [refine or {"kb_query": "pv", "web_query": "pv"}],
                       "variables": list(variables), "plan": [plan or {}]}
        self.calls, self.plan_prompts = [], []

    def _next(self, role):
        self.calls.append(role)
        replies = self.script[role]
        reply = replies.pop(0) if len(replies) > 1 else replies[0]
        return AIMessage(content=reply if isinstance(reply, str) else json.dumps(reply))

    def invoke(self, messages):
        system, user = messages[0][1], messages[1][1]
        if "You are the router" in system:
            return AIMessage(content='{"intents": ["calc"], "confidence": 0.9}')
        if "You are the proofreader" in system:
            return AIMessage(content=user.split("Message: ", 1)[-1])
        for prefix, role in (("Calculator step 1", "understand"), ("Calculator step 2", "define"),
                             ("Calculator step 3: cross-check", "match"), ("Calculator step 3: search again", "refine"),
                             ("Calculator step 4", "variables")):
            if system.startswith(prefix):
                return self._next(role)
        if system.startswith("Calculator step 3: read a reference"):
            return self._next("web" if "tvmcalcs" in user or "Lump Sum Formulas" in user else "kb")
        if "finance calculator" in system:
            self.plan_prompts.append(user)
            return self._next("plan")
        return AIMessage(content="{}")


@pytest.fixture
def sources():
    """The fake knowledge base and web search, recording the queries."""
    seen = {"kb": [], "web": []}
    tools.set_kb_searcher(lambda q, k: seen["kb"].append(q) or [KB_CHUNK])
    T.set_web_searcher(lambda q: seen["web"].append(q) or [WEB_RESULT])
    return seen


def ask(llm, q=Q):
    llm_module.set_llm(llm)
    s = run_chat(q, history=[], profile=PROFILE, holdings=[], db=None)
    return s, s["agent_outputs"]["calc"]


def test_an_equation_found_in_both_sources_is_cross_checked_computed_and_quoted(sources):
    llm = StepLLM()
    s, out = ask(llm)
    assert out["status"] == "answered" and out["verbatim"]
    assert sorted(llm.calls) == ["define", "kb", "match", "understand", "variables", "web"]   # one call per step
    assert sources == {"kb": ["present value formula"], "web": ["present value lump sum formula"]}
    text = out["content"]
    assert "**Result: deposit needed today = $32,877.08**" in text                       # 40,000 ÷ 1.04^5
    assert "- Formula: `P = C/(1+i)^n`" in text and "rearranged" not in text             # the source's own equation
    assert "**Where the equations come from**" in text
    assert "found in the knowledge base and on the web, and they agree ✓" in text
    assert "— [Present value › Present value of a lump sum](https://en.wikipedia.org/wiki/Present_value), knowledge base" in text
    assert "— [Lump Sum Formulas](https://tvmcalcs.com/tvm-math/lump-sum-formulas), web" in text
    assert {x["url"] for x in s["sources"]} == {KB_CHUNK["source_url"], WEB_RESULT["url"]}
    assert any(t.startswith("calc step 3 cross-check P: match") for t in s["trace"])


def test_a_quote_that_isnt_in_the_source_is_rejected_and_the_search_repeated(sources):
    invented = {**WEB_EQ, "quote": "PV equals FV over one plus i to the N"}
    llm = StepLLM(web=(invented, WEB_EQ))
    s, out = ask(llm)
    assert out["status"] == "answered" and llm.calls.count("refine") == 1
    assert any("web its quote isn't in the source" in t for t in s["trace"])
    assert sources["kb"] == ["present value formula", "pv"]                              # the refined searches


def test_sources_that_still_disagree_after_searching_again_ask_the_user(sources):
    annuity = {**WEB_EQ, "equation": "PV = PMT*(1-(1+i)^(-N))/i", "formula": "PMT*(1-(1+i)^(-N))/i",
               "variables": {"PV": "present value", "PMT": "payment", "i": "rate", "N": "periods"}}
    llm = StepLLM(web=(annuity,), match=({"reasoning": "One is an annuity.", "match": False},))
    s, out = ask(llm)
    assert out["status"] == "need_info" and "I found two different equations for deposit needed today" in out["content"]
    assert "- `PV = C/(1+i)^n` (knowledge base: Present value › Present value of a lump sum)" in out["content"]
    assert "- `PV = PMT*(1-(1+i)^(-N))/i` (web: Lump Sum Formulas)" in out["content"]
    assert llm.calls.count("match") == 2 and "variables" not in llm.calls


def test_without_web_search_the_knowledge_base_alone_is_used_and_marked(sources):
    T.set_web_searcher(None)                                                            # and no TAVILY_API_KEY in tests
    s, out = ask(StepLLM())
    assert "**Result: deposit needed today = $32,877.08**" in out["content"]
    assert "found in one source only, not cross-checked" in out["content"] and sources["web"] == []


def test_a_wrong_rearrangement_from_a_source_is_replaced_by_the_equations_own_side(sources):
    s, out = ask(StepLLM(kb=({**KB_EQ, "formula": "C*(1+i)^n"},)))
    assert "Solved numerically" not in out["content"] and "- Formula: `P = C/(1+i)^n`" in out["content"]
    assert "**Result: deposit needed today = $32,877.08**" in out["content"]


def test_an_equation_without_the_target_on_its_own_is_solved_numerically(sources):
    s, out = ask(StepLLM(kb=({**KB_EQ, "equation": "C = PV*(1+i)^n", "formula": None},)))
    assert "- Solved numerically for `P`" in out["content"]
    assert "**Result: deposit needed today = $32,877.08**" in out["content"]


def test_rejected_variables_are_repaired_once(sources):
    invented = {"inputs": {**VARIABLES["inputs"], "i": {"value": 0.05, "from": "user", "unit": "rate", "means": "rate"}}}
    llm = StepLLM(variables=(invented, VARIABLES))
    s, out = ask(llm)
    assert llm.calls.count("variables") == 2 and out["status"] == "answered"
    # 0.05 passes guard 1 ("5 years" is in the question), but then the real 4% is unused: guard 2 rejects it
    assert any("calc step 4 variables rejected: the question's number 4 isn't used" in t for t in s["trace"])


def test_a_target_given_as_a_derived_value_is_dropped_and_the_repair_names_the_spare_input(sources):
    # the trace that prompted this: "r_year" as the input, the target itself "derived" from it, and no value for "i"
    given = VARIABLES["inputs"]
    renamed = {"inputs": {"C": given["C"], "r_year": given["i"], "n": given["n"]},
               "derived": {"P": {"expr": "C/(1+r_year)^n", "unit": "money"}}}
    llm = StepLLM(variables=(renamed, VARIABLES))
    s, out = ask(llm)                                   # a rate for a rate: Python pairs them, no repair round
    assert llm.calls.count("variables") == 1 and out["status"] == "answered"
    unclear = {**renamed, "inputs": {**renamed["inputs"], "r_year": {**given["i"], "unit": "number"}}}
    llm = StepLLM(variables=(unclear, VARIABLES))
    s, out = ask(llm)                                   # not clearly a rate: the repair round names the spare input
    assert llm.calls.count("variables") == 2 and out["status"] == "answered"
    assert any("no value for i (rate per period)" in t and "inputs no variable uses yet: r_year" in t
               and "don't give the targets (P)" in t for t in s["trace"])


def test_a_new_topic_doesnt_carry_the_earlier_conversation_into_the_calculator(sources):
    class Recording(StepLLM):
        def invoke(self, messages):
            if messages[0][1].startswith("Calculator step 1"):
                seen.append(messages[1][1])
            return super().invoke(messages)

    seen = []
    llm_module.set_llm(Recording())
    history = [{"role": "user", "content": "If I invest $10,000 in 5 stocks, how much must each grow to double it?"},
               {"role": "assistant", "content": "Each would need to grow 100%."}]
    s = run_chat(Q, history=history, profile=PROFILE, holdings=[], db=None)
    assert not s["follow_up"] and seen and "5 stocks" not in seen[0]


def test_step_2_defines_targets_from_the_message_not_the_conversation(sources):
    # the trace that prompted this: a follow-up's step 2 re-added the previous answer's calculations as targets
    class Recording(StepLLM):
        def invoke(self, messages):
            if messages[0][1].startswith("Calculator step 2"):
                seen.append(messages[1][1])
            return super().invoke(messages)

    seen = []
    llm = Recording()
    llm_module.set_llm(llm)
    history = [{"role": "user", "content": "Show me how a mutual fund grows"},
               {"role": "assistant", "content": "**Worked example: ending_value** of $2,000 at 7% for 10 years"}]
    run_chat(Q, history=history, profile=PROFILE, holdings=[], db=None, context={"question": "Show me how a fund grows"})
    assert seen and seen[0].startswith(f"Message: {Q}") and "ending_value" not in seen[0]


def test_a_second_target_with_the_same_equation_gets_a_hint_for_its_own_variables():
    targets = [{"name": f, "label": f, "unit": "money", "kind": "formula"} for f in ("FV", "FV_b")]
    found = {t["name"]: {"eq": {"quote": "q", "equation": "F = P*(1+r)^n", "formula": "P*(1+r)^n", "for": "F",
                                "variables": {"P": "present value", "r": "rate", "n": "periods"}}} for t in targets}
    filled = {"inputs": {v: {"value": x, "from": "user", "unit": "number"} for v, x in (("P", 2500), ("r", 0.07), ("n", 10))}}
    with pytest.raises(PLAN.PlanError, match=r"P_2, n_2, r_2 belong to a second target with the same equation"):
        CP.build_plan(targets, CP.name_equations(targets, found), filled, [])


def test_derived_values_and_an_arithmetic_target_chain_onto_a_sourced_equation(sources):
    q = "I save $600 a month split equally into 3 accounts. What goes into each, and what is $40,000 in 5 years at 4% worth today?"
    define = {"targets": [{"name": "each", "label": "each account per month", "unit": "money", "kind": "arithmetic",
                           "expr": "S/k", "variables": {"S": "monthly saving", "k": "number of accounts"}}, DEFINE["targets"][0]]}
    variables = {"inputs": {**VARIABLES["inputs"], "S": {"value": 600, "from": "user", "unit": "money", "means": "saving"},
                            "k": {"value": 3, "from": "user", "unit": "number", "means": "accounts"},
                            "t": {"value": 5, "from": "user", "unit": "years", "means": "years"}}}
    variables["inputs"].pop("n")
    variables["derived"] = {"n": {"expr": "t", "unit": "years"}}
    s, out = ask(StepLLM(define=define, variables=(variables,)), q)
    assert "**Result: each account per month = $200**" in out["content"]
    assert "**Result: deposit needed today = $32,877.08**" in out["content"]


def test_a_simulation_goes_to_the_plan_path_and_says_its_model_isnt_sourced(sources):
    plan = {"label": "how long", "inputs": {"B": {"value": 5000, "unit": "money"}, "p": {"value": 200, "unit": "money"}},
            "steps": [{"name": "m", "label": "months", "result": "periods", "unit": "months",
                       "simulate": {"start": {"balance": "B"}, "each": {"balance": "balance - min(p, balance)"},
                                    "until": "balance <= 0", "period": "month"}}],
            "checks": [{"when": {"B": 0}, "of": "m", "expect": "0"}]}
    define = {"targets": [{"name": "m", "label": "months", "unit": "months", "kind": "simulation"}]}
    s, out = ask(StepLLM(define=define, plan=plan), "I owe $5,000 and pay $200 a month. How many months?")
    assert "**Result: months = 25 months**" in out["content"]
    assert "isn't quoted from a source" in out["content"] and sources == {"kb": [], "web": []}
    assert any("plan path: a target changes period by period" in t for t in s["trace"])


def test_unusable_steps_fall_back_to_the_plan_path(sources):
    s, out = ask(StepLLM(understand="no json", plan={"label": "x"}))
    assert any("plan path: step 1 gave no usable reply" in t for t in s["trace"])


def test_a_constant_stated_by_the_source_is_allowed_and_python_powers_are_read(sources):
    rule = "The Rule of 72: it takes about 72/r years to double."
    tools.set_kb_searcher(lambda q, k: [{**KB_CHUNK, "text": KB_TEXT + " " + rule}])
    kb = {**KB_EQ, "quote": rule, "equation": "PV = C/(1+i)^n*72/72", "formula": "C/(1+i)**n*72/72"}
    s, out = ask(StepLLM(kb=(kb,)))
    assert "**Result: deposit needed today = $32,877.08**" in out["content"]
    invented = {**KB_EQ, "equation": "PV = C/(1+i)^n*73/73", "formula": "C/(1+i)^n*73/73"}   # 73 isn't in the quote
    s, out = ask(StepLLM(kb=(invented, invented)))
    assert any("its equation has 73, which the quote doesn't state" in t for t in s["trace"])


def test_an_equation_step_4_cant_fill_goes_to_the_plan_path(sources):
    s, out = ask(StepLLM(variables=({"inputs": {}},), plan={"label": "x"}))
    assert any("plan path: step 4 couldn't fill the sourced equation: no value for C (future amount), i (rate per period)" in t for t in s["trace"])


def test_equations_that_agree_but_dont_fit_the_question_are_searched_again(sources):
    wrong_quantity = {"reasoning": "Both give future value; the question asks for today's value.", "match": True, "fits": False}
    llm = StepLLM(match=(wrong_quantity, MATCH))
    s, out = ask(llm)
    assert llm.calls.count("refine") == 1 and out["status"] == "answered"
    assert any("they agree, but don't compute what the question asks" in t for t in s["trace"])


def test_a_comparison_in_step_2_is_sent_back_once_with_the_reason(sources):
    q = "I save $40,000 in 5 years at 4%. Is the $32,000 I have today enough?"
    compare = {"targets": [DEFINE["targets"][0], {"name": "enough", "label": "enough?", "unit": "number",
                                                  "kind": "arithmetic", "expr": "H >= P", "variables": {"H": "cash today"}}]}
    diff = {"targets": [DEFINE["targets"][0], {"name": "left", "label": "left over (negative: short by)", "unit": "money",
                                               "kind": "arithmetic", "expr": "H - P", "variables": {"H": "cash today"}}]}
    variables = {"inputs": {**VARIABLES["inputs"], "H": {"value": 32000, "from": "user", "unit": "money", "means": "cash"}}}
    llm = StepLLM(define=None, variables=(variables,))
    llm.script["define"] = [compare, diff]
    s, out = ask(llm, q)
    assert llm.calls.count("define") == 2
    assert any("2 targets rejected: target enough: a formula can't compare" in t for t in s["trace"])
    assert "**Result: left over (negative: short by) = −$877.08**" in out["content"]       # 32,000 − 32,877.08


def test_a_number_the_calculation_doesnt_need_can_be_ignored_with_why(sources):
    q = Q + " The bank also offers a 7-year CD."
    variables = {**VARIABLES, "ignored": [{"number": 7, "why": "the CD is only mentioned, not asked about"}]}
    s, out = ask(StepLLM(variables=(variables,)), q)
    assert "Not used: 7 (the CD is only mentioned, not asked about)." in out["content"]


def test_one_source_per_search_is_cross_checked_across_the_two_searches(sources):
    T.set_web_searcher(lambda q: [])                                                    # the web finds nothing
    other = {**KB_EQ, "quote": "Where $\\\\,C\\\\,$ is the future amount of money that must be discounted"}
    llm = StepLLM(kb=(KB_EQ, other), match=({"reasoning": "One is wrong.", "match": False},))
    s, out = ask(llm)
    assert out["status"] == "need_info" and llm.calls.count("match") == 1
    assert any("cross-check P across searches: no match" in t for t in s["trace"])


# ---------------------------------------------------------------- worked examples (sample numbers only)
from src.workflow import calc_pipeline as CP  # noqa: E402

SAMPLES = {"inputs": {k: {**v, "from": "sample"} for k, v in VARIABLES["inputs"].items()}}


@pytest.mark.parametrize("q,example", [
    ("Can you show me an example of how to calculate WACC?", True), ("How do you calculate APY?", True),
    ("How is present value calculated?", True), ("Illustrate compound interest with numbers", True),
    ("How much will my savings grow?", False), ("Can you calculate how much my savings will grow?", False),
    ("What's the monthly payment on a $300,000 mortgage at 6.5% for 30 years?", False),
])
def test_example_requests_are_recognised_from_the_wording(q, example):
    assert CP.wants_example(q) is example


def test_an_example_request_is_answered_with_sample_numbers_marked(sources):
    s, out = ask(StepLLM(variables=(SAMPLES,)), "Can you show me an example of how to calculate present value?")
    assert out["status"] == "answered" and out["content"].startswith("**Worked example: deposit needed today**")
    assert "- `C` = $40,000: down payment needed **(sample)**" in out["content"]
    assert "Values marked (sample) are illustrative" in out["content"]
    assert any("calc step 1 worked example: sample numbers allowed" in t for t in s["trace"])


def test_step_1_can_flag_an_example_the_wording_doesnt_show(sources):
    s, out = ask(StepLLM(understand={**UNDERSTAND, "example": True}, variables=(SAMPLES,)), "Present value, with numbers?")
    assert out["status"] == "answered" and "**Worked example:" in out["content"]


def test_without_an_example_request_sample_numbers_only_still_ask(sources):
    s, out = ask(StepLLM(variables=(SAMPLES,)), "How much should I deposit today?")
    assert out["status"] == "need_info" and out["content"].startswith("I can work out")



def test_the_judge_picks_which_of_two_matching_equations_to_use(sources):
    general = {**KB_EQ, "equation": "PV = C/(1+i)^n + 0*C", "formula": "C/(1+i)^n + 0*C"}      # a more general form
    web_names = {"inputs": {"FV": VARIABLES["inputs"]["C"], "i": VARIABLES["inputs"]["i"], "N": VARIABLES["inputs"]["n"]}}
    s, out = ask(StepLLM(kb=(general,), match=({**MATCH, "use": "B"},), variables=(web_names,)))
    assert "- Formula: `P = FV/(1+i)^N`" in out["content"]                                   # the web's, as chosen
    assert any("cross-check P: match, using the web's" in t for t in s["trace"])


def test_inputs_listed_as_targets_are_dropped(sources):
    define = {"targets": [{"name": "C", "label": "future amount", "unit": "money", "kind": "given"}, DEFINE["targets"][0]]}
    s, out = ask(StepLLM(define=define))
    assert out["status"] == "answered" and "**Result: deposit needed today = $32,877.08**" in out["content"]


def test_a_fallback_that_isnt_a_simulation_says_the_formula_is_finnies_own(sources):
    plan = {"label": "x", "inputs": {"C": {"value": 40000, "unit": "money"}, "i": {"value": 0.04, "unit": "rate"},
                                     "n": {"value": 5, "unit": "years"}},
            "steps": [{"name": "P", "label": "deposit", "expr": "C/(1+i)^n", "unit": "money"}],
            "checks": [{"when": {"i": 0}, "of": "P", "expect": "C"}]}
    s, out = ask(StepLLM(kb=({"found": False},), web=({"found": False},), plan=plan))
    assert "the formulas above are Finnie's own" in out["content"] and "No single standard equation" not in out["content"]


def test_a_plan_after_step_4_fails_is_built_on_the_sourced_equation_and_quotes_it(sources):
    plan = {"label": "x", "inputs": {"C": {"value": 40000, "unit": "money"}, "i": {"value": 0.04, "unit": "rate"},
                                     "n": {"value": 5, "unit": "years"}},
            "steps": [{"name": "P", "label": "deposit", "expr": "C/(1+i)^n", "unit": "money"}],
            "checks": [{"when": {"i": 0}, "of": "P", "expect": "C"}]}
    llm = StepLLM(variables=({"inputs": {}},), plan=plan)
    s, out = ask(llm)
    assert "build on it with its variables" in llm.plan_prompts[0] and "`P = C/(1+i)^n`" in llm.plan_prompts[0]
    assert "around the quoted equations below" in out["content"] and "Finnie's own" not in out["content"]
    assert "**Where the equations come from**" in out["content"]


# ---------------------------------------------------------------- step 3b: the source's notation, read by Python
CAPM = [(r"r_{e}=r_{f}+\beta \cdot (r_{m}-r_{f})", {r"r_{e}": "expected return", r"r_{f}": "risk-free rate",
                                                    r"\beta": "beta", r"r_{m}": "market return"}, r"r_{e}"),
        ("ERi = Rf + βi × (E(Rm) – Rf)", {"ERi": "expected return", "Rf": "risk-free rate", "βi": "beta",
                                          "E(Rm)": "market return"}, "ERi"),
        ("Ra = Rrf + [βa x (Rm – Rrf)]", {"Ra": "expected return", "Rrf": "risk-free rate", "βa": "beta",
                                          "Rm": "market return"}, "Ra"),
        (r"\mu _{i}=r_{f}+(\mu _{M}-r_{f})*\beta _{i}", {r"\mu _{i}": "expected return", r"r_{f}": "risk-free rate",
                                                         r"\mu _{M}": "market return", r"\beta _{i}": "beta"}, r"\mu _{i}"),
        ("R i = Rf + ßi [ Rm - Rf ]", {"R i": "expected return", "Rf": "risk-free rate", "ßi": "beta",
                                       "Rm": "market return"}, "R i")]


@pytest.mark.parametrize("equation, symbols, target", CAPM)
def test_capm_as_each_source_writes_it_is_read_without_the_llm(equation, symbols, target):
    from src.core import equations as EQ
    from src.workflow import calc_pipeline as CP
    llm_module.set_llm(StepLLM())                       # a translation call would get "{}" and fail
    read, why = CP.translate(equation, symbols, target)
    assert why == "" and read["for"] == CP._ascii_name(target)
    values = {n: {"beta": 1.2, "market return": 0.08, "risk-free rate": 0.03}[m] for n, m in read["variables"].items()}
    formula = CP._isolated(read["equation"], read["for"])
    assert EQ.evaluate(formula, values) == pytest.approx(0.09)                         # 3% + 1.2 × (8% − 3%)


def test_latex_fractions_and_powers_read_tidily():
    from src.workflow import calc_pipeline as CP
    assert CP._tidy(CP.plain(r"PV={\frac {C}{(1+i)^{n}}}\,")) == "PV = C/(1 + i)^n"
    assert CP._tidy(CP.plain(r"T=\left({\frac {ERV}{P}}\right)^{1/n}-1")) == "T = (ERV/P)^(1/n) - 1"
    assert CP.plain(r"\sqrt{x} + 2(y)") == "sqrt(x) + 2(y)"


def test_an_equation_python_cant_read_is_translated_by_the_llm_with_the_reason():
    from src.workflow import calc_pipeline as CP

    class Translator:
        model, prompts = "t", []

        def invoke(self, messages):
            self.prompts.append(messages[1][1])
            return AIMessage(content=json.dumps({"names": {"Return": "R", "Rate": "r", "Years": "n", "Start": "S"},
                                                 "equation": "R = S*(1+r)^n"}))
    llm = Translator()
    llm_module.set_llm(llm)
    read, why = CP.translate("Return equals Start times (1 + Rate) to the power Years",
                             {"Return": "end value", "Start": "start", "Rate": "rate", "Years": "years"}, "Return")
    assert why == "" and read["equation"] == "R = S*(1 + r)^n" and read["for"] == "R"
    assert read["variables"] == {"S": "start", "r": "rate", "n": "years"}
    assert len(llm.prompts) == 1 and "Why Python can't use it:" in llm.prompts[0]


def test_an_equation_neither_python_nor_the_llm_can_read_is_rejected_with_why():
    from src.workflow import calc_pipeline as CP
    llm_module.set_llm(StepLLM())
    read, why = CP.translate("FV = PV × (1 + r)ⁿ", {"FV": "future value", "PV": "present value", "r": "rate"}, "FV")
    assert read is None and why.startswith("unreadable equation")


def test_the_equation_as_the_source_writes_it_is_extracted_and_computed(sources):
    kb = {"found": True, "passage": 1, "quote": KB_EQ["quote"], "equation": r"PV={\frac {C}{(1+i)^{n}}}\,",
          "symbols": {"PV": "present value", "C": "future amount", "i": "rate per period", "n": "number of periods"},
          "for": "PV"}
    web = {"found": True, "passage": 1, "quote": WEB_EQ["quote"], "equation": r"PV = \frac{FV}{(1 + i)^N}",
           "symbols": {"PV": "present value", "FV": "future value", "i": "rate", "N": "periods"}, "for": "PV"}
    s, out = ask(StepLLM(kb=(kb,), web=(web,)))
    assert out["status"] == "answered" and "**Result: deposit needed today = $32,877.08**" in out["content"]
    assert "- Formula: `P = C/(1 + i)^n`" in out["content"]


def test_a_quote_joined_from_two_places_is_replaced_by_the_equation_it_contains(sources):
    stitched = {**WEB_EQ, "quote": "Present Value: PV = FV/(1+i)^N, where FV is the future value",
                "equation": r"PV = \frac{FV}{(1 + i)^N}"}
    s, out = ask(StepLLM(web=(stitched,)))
    assert out["status"] == "answered" and not any("quote isn't in the source" in t for t in s["trace"])


def test_a_target_that_is_a_number_the_message_gives_is_dropped(sources):
    understand = {**UNDERSTAND, "given": [{"value": "40,000", "means": "the down payment amount needed"}],
                  "find": ["the deposit needed today"]}
    extra = {"name": "D", "label": "down payment", "unit": "money", "kind": "arithmetic", "expr": "P*(1+i)^n",
             "variables": {"i": "rate", "n": "years"}}
    s, out = ask(StepLLM(understand=understand, define={**DEFINE, "targets": DEFINE["targets"] + [extra]}))
    assert out["status"] == "answered" and "**Result: deposit needed today = $32,877.08**" in out["content"]
    assert any("2 dropped targets the message gives: D (down payment)" in t for t in s["trace"])


def test_a_target_the_question_asks_for_is_kept_even_if_a_given_sounds_alike():
    from src.workflow import calc_pipeline as CP
    understanding = {"given": [{"value": "5000", "means": "the future value I want"}], "find": ["future value"]}
    assert not CP._is_given({"label": "future value"}, understanding)
    assert CP._is_given({"label": "initial investment"}, {"given": [{"means": "the initial investment amount"}]})


def test_a_target_that_only_names_an_input_is_treated_as_one(sources):
    from src.workflow import calc_pipeline as CP
    targets, why = CP._targets({"targets": [
        {"name": "beta", "label": "beta of the asset", "unit": "number", "kind": "arithmetic", "expr": "given_beta"},
        {"name": "rm", "label": "market return", "unit": "rate", "kind": "arithmetic", "expr": "0.08"},
        {"name": "premium", "label": "market risk premium", "unit": "rate", "kind": "arithmetic", "expr": "rm - rf",
         "variables": {"rf": "risk-free rate"}}]})
    assert why == "" and [t["name"] for t in targets] == ["premium"]
    assert targets[0]["variables"] == {"rf": "risk-free rate", "rm": "market return"}
    assert CP._targets({"targets": [{"name": "b", "label": "b", "kind": "arithmetic", "expr": "x"}]})[0] is None


def test_a_users_number_given_under_its_own_name_fills_the_equations_variable(sources):
    variables = {"inputs": {"C": VARIABLES["inputs"]["C"], "n": VARIABLES["inputs"]["n"],
                            "r_year": {"value": 0.04, "from": "user", "unit": "rate", "means": "yearly interest rate"}}}
    s, out = ask(StepLLM(variables=(variables,)))
    assert out["status"] == "answered" and "**Result: deposit needed today = $32,877.08**" in out["content"]
    assert not any("variables rejected" in t for t in s["trace"])                     # no repair round needed


def test_an_unused_input_of_another_kind_is_not_paired():
    from src.workflow import calc_pipeline as CP
    need = {"r": "interest rate per period", "n": "number of periods"}
    inputs = {"t": {"value": 5, "unit": "years"}, "x": {"value": 0.04, "unit": "rate"}, "y": {"value": 0.05, "unit": "rate"}}
    assert CP._paired(["n"], need, inputs, {}) == {"n": {"expr": "t"}}
    assert CP._paired(["r"], need, inputs, {}) == {}                                   # two rates: which one is a guess
    assert CP._paired(["r"], need, {"t": inputs["t"]}, {}) == {}                       # years aren't a rate


def test_an_equation_the_judge_calls_misread_is_dropped_and_the_other_used(sources):
    misread = {**WEB_EQ, "equation": "PV = FV*(1+i)^N", "formula": None}             # not a present value at all
    verdict = {"reasoning": "B compounds instead of discounting.", "match": False, "misread": "B"}
    llm = StepLLM(web=(misread,), match=(verdict,))
    s, out = ask(llm)
    assert out["status"] == "answered" and "**Result: deposit needed today = $32,877.08**" in out["content"]
    assert any("the web's misread" in t for t in s["trace"]) and llm.calls.count("refine") == 1
    assert "found in one source" in out["content"] or "one source" in out["content"]


def test_two_real_equations_that_differ_still_ask(sources):
    annuity = {**WEB_EQ, "equation": "PV = FV*(1-(1+i)^(-N))/i", "formula": None}
    verdict = {"reasoning": "B is an annuity, A a lump sum.", "match": False, "misread": None}
    s, out = ask(StepLLM(web=(annuity,), match=(verdict,)))
    assert out["status"] == "need_info" and "two different equations" in out["content"]
