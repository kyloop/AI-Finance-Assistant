"""A follow-up about the previous answer's worked example ("how would the tax change in this case?" after an example of
saving for a house): the example is saved in the turn's context, the follow-up stays in its topic and is completed with
it, the tax agent works out the example's tax, and a goal answer about another goal (the saved retirement plan) is
dropped. Regression for a chain that ended in "no specific information about how taxes would change in this retirement
plan scenario"."""
from src.core import llm as llm_module
from src.workflow import context as CTX
from src.workflow import nodes as N
from src.workflow import tax_whatif as TW
from src.workflow import topics as TOP
from src.workflow.graph import run_chat
from tests.test_verifier import ScriptedLLM

SAVED = {"goal_type": "retirement", "target_amount": 1_000_000, "horizon_years": 10, "current_savings": 10_000,
         "monthly_contribution": 500, "risk_tolerance": "moderate"}
PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate"}
CHAIN = ["explain the planning goal ?", "Can you give an example of setting a planning goal for a house purchase?",
         "how would the tax change in this case?", "what would be the diff if I borrow 200000 from bank and pay 1.5 interest"]
HOUSE = {"kind": "savings_goal", "goal_type": "house", "text": "saving $60,000 over 5 years (about $905 a month) for a 20% "
         "down payment on a $300,000 house", "figures": {"home_price": 300000, "down_payment_pct": 0.2, "target": 60000,
                                                         "years": 5, "monthly": 905, "annual_return": 0.04}}
NO_ENTITIES = {"target_amount": None, "years": None, "monthly_amount": None}


def _turn(q, history, context, **kw):
    return run_chat(q, history=history, profile=PROFILE, holdings=[], db=None, saved_goal=SAVED, view={"tab": "Goals"},
                    context=context, **kw)


# ---------------------------------------------------------------- step 1: the example is saved with the answer
def test_goal_example_is_computed_and_saved_as_the_turns_scenario():
    s = {"question": CHAIN[1], "original_question": CHAIN[1], "profile": PROFILE, "saved_goal": SAVED, "entities": NO_ENTITIES}
    res = N.goal_node(s, {})
    out, scen = res["agent_outputs"]["goal"], res["turn_context"]["scenario"]
    assert out["goal_type"] == "house" and "retirement" not in out["content"]          # not the saved retirement plan
    assert "$300,000" in out["content"] and "$60,000" in out["content"] and "5 years" in out["content"]
    assert scen["kind"] == "savings_goal" and scen["goal_type"] == "house"
    assert scen["figures"]["target"] == 60000 and scen["figures"]["home_price"] == 300000 and scen["figures"]["years"] == 5
    line = CTX.describe({"scenario": scen})
    assert "home price 300000" in line and "target 60000" in line and "5 years" in line and "down payment share 20%" in line


def test_context_keeps_the_scenario_for_a_follow_up_and_drops_it_for_a_new_question():
    prev = {"question": "Example?", "scenario": HOUSE}
    assert CTX.build({"question": "How is that taxed?", "context_in": prev, "follow_up": True})["scenario"] == HOUSE
    assert CTX.build({"question": "What is an ETF?", "context_in": prev, "follow_up": False, "intent": ["qa"]})["scenario"] is None


def test_an_answers_worked_example_is_noted_with_only_the_figures_it_states():
    answer = ("For example, if you want to buy a house that costs **$300,000** and put down **20%**, your goal would be to "
              "save **$60,000** over **5 years**, about **$1,000** each month.")
    llm_module.set_llm(ScriptedLLM(synth='{"text": "saving $60,000 over 5 years for a 20% down payment on a $300,000 house", '
                                         '"goal_type": "house", "figures": {"target": 60000, "years": 5, "monthly": 1000, '
                                         '"home_price": 300000, "down_payment_pct": 0.2, "interest": 4321}}'))
    got = N._answer_scenario({"question": CHAIN[1], "answered": True}, answer)
    assert got["kind"] == "savings_goal" and got["goal_type"] == "house"
    assert got["figures"] == {"target": 60000, "years": 5, "monthly": 1000, "home_price": 300000, "down_payment_pct": 0.2}
    assert N._answer_scenario({"question": "What is an ETF?", "answered": True}, "An ETF is a fund.") is None


# ---------------------------------------------------------------- step 2: the follow-up stays in the topic, completed
def test_pointing_back_is_recognised():
    for q in ("how would the tax change in this case?", "What about that scenario?", "and in that example?",
              "what about tax here?", "How is it taxed in this situation?"):
        assert CTX.refers_back(q), q
    for q in ("What is an ETF?", "Is this case study about index funds?", "How are Roth IRAs taxed?"):
        assert not CTX.refers_back(q), q


def test_proofread_marks_it_a_follow_up_and_adds_the_example_even_when_the_model_does_not():
    llm_module.set_llm(ScriptedLLM())                       # the proofreader returns the message unchanged, no follow_up
    s = {"question": CHAIN[2], "context_in": {"question": CHAIN[1], "scenario": HOUSE, "tab": "Goals"},
         "view": {"tab": "Goals"}, "history": [{"role": "user", "content": CHAIN[1]}]}
    out = N.proofread_node(s, {})
    assert out["follow_up"] is True
    assert "$60,000 over 5 years" in out["question"] and "$300,000 house" in out["question"]
    assert out["original_question"] == CHAIN[2]


def test_basic_mode_completes_it_too():
    s = {"question": CHAIN[2], "context_in": {"question": CHAIN[1], "scenario": HOUSE}, "history": []}
    out = N.proofread_node(s, {})
    assert out["follow_up"] is True and "$300,000 house" in out["question"]


def test_a_rewrite_that_already_names_the_example_is_kept():
    q = "How would federal tax apply to saving $60,000 over 5 years for a house?"
    assert CTX.with_scenario(q, {"scenario": HOUSE}) == q


def test_topic_stays_when_the_message_points_back_whatever_follow_up_says():
    pool = {"current": [{"topic_id": "t1", "uid": "u1", "label": "Savings plan", "companies": [], "markets": []}], "earlier": []}
    s = {"question": CHAIN[2], "original_question": CHAIN[2], "context_in": {"topic_id": "t1"}, "follow_up": False}
    got = TOP.choose(s, pool, embed=None)
    assert got["action"] == "continue" and got["topic_id"] == "t1"


# ---------------------------------------------------------------- step 3: the tax agent works out the example
def test_savings_goal_tax_gives_the_examples_figures():
    text, note = TW.savings_goal_tax(HOUSE)
    for phrase in ("$60,000", "$300,000", "1099-INT", "$10,000", "Roth IRA", "standard deduction", "$16,100", "$32,200",
                   "$240,000", "Section 121", "$250,000", "**Assumed:**"):
        assert phrase in text, phrase
    assert "| **Total** | **$5,701** |" in text                   # interest on $905 a month at 4% for 5 years
    assert note.startswith("savings_goal_tax(house, 60,000, 5y)")


def test_savings_goal_tax_uses_the_users_estimate_when_there_is_one():
    profile = {"year": 2026, "filing_status": "single", "items": [{"text": "salary", "amount": 90000, "kind": "wages", "loss": False, "included": False}]}
    text, note = TW.savings_goal_tax(HOUSE, profile)
    assert "Measured against your last estimate" in text and "with your estimate" in note
    assert "lowers your federal tax by" in text


def test_savings_goal_tax_assumes_a_price_for_a_down_payment_without_one():
    scen = {**HOUSE, "figures": {"target": 50000, "years": 4}}
    text, _ = TW.savings_goal_tax(scen)
    assert "a home of about $250,000" in text


def test_the_tax_agent_alone_answers_a_tax_question_about_the_example():
    s = {"question": CHAIN[2], "original_question": CHAIN[2], "follow_up": True, "context_in": {"scenario": HOUSE}}
    assert N._example_tax_to_tax_agent(["tax", "goal"], s) == ["tax"]
    assert N._example_tax_to_tax_agent(["goal"], {**s, "question": "How about a car?", "original_question": "How about a car?"}) == ["goal"]
    roth = "What about Roth IRA limits?"           # a tax subject of its own: not the example's
    assert N._example_tax_to_tax_agent(["tax"], {**s, "question": roth, "original_question": roth}) == ["tax"]
    assert N._savings_scenario({**s, "question": roth, "original_question": roth, "entities": NO_ENTITIES}) is None


# ---------------------------------------------------------------- step 4: a goal answer about another goal is dropped
def test_verifier_drops_a_goal_answer_about_another_goal():
    s = {"question": "How would the tax change for saving $60,000 for a house?", "context_in": {"scenario": HOUSE},
         "follow_up": True, "agent_outputs": {
             "goal": {"agent": "goal", "status": "answered", "content": "Based on your retirement plan on the Goals tab ...",
                      "goal_type": "retirement", "sources": []}}}
    out = N.verifier_node(s, {})
    goal = out["agent_outputs"]["goal"]
    assert goal["status"] == "not_found" and goal["content"] == "" and goal["handed_off"]
    assert "not the house one" in out["trace"][0]
    same = {**s, "agent_outputs": {"goal": {**s["agent_outputs"]["goal"], "goal_type": "house"}}}
    assert N.verifier_node(same, {})["agent_outputs"]["goal"]["status"] == "answered"


def test_goal_agent_does_not_answer_a_house_question_with_the_saved_retirement_plan():
    q = "How much should I save for a house?"
    res = N.goal_node({"question": q, "original_question": q, "profile": PROFILE, "saved_goal": SAVED, "entities": NO_ENTITIES}, {})
    assert res["agent_outputs"]["goal"]["status"] == "need_info"


# ---------------------------------------------------------------- the whole chain, offline
def test_the_chain_ends_with_the_house_examples_tax():
    llm_module.set_llm(ScriptedLLM(router=['{"intents": ["goal"], "confidence": 0.9}',
                                           '{"intents": ["goal", "qa"], "confidence": 0.9}',
                                           '{"intents": ["tax"], "confidence": 0.9}']))
    history, context = [], None
    for q in CHAIN[:3]:
        s = _turn(q, history, context)
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": s["final_response"]}]
        context = s["context"]
    text = s["final_response"]
    assert s["agents"] == ["Tax Education"] and s["intent"] == ["tax"]
    assert "$60,000" in text and "$300,000 house" in text and "Section 121" in text and "standard deduction" in text
    assert "retirement plan" not in text
    assert s["context"]["scenario"]["goal_type"] == "house"           # kept for the next follow-up


# ---------------------------------------------------------------- a follow-up that changes the example
def test_a_loan_changes_the_example_and_keeps_the_rest():
    got = CTX.scenario_change(CHAIN[3], HOUSE)
    f = got["figures"]
    assert f["home_price"] == 300000 and f["loan_amount"] == 200000 and f["loan_rate"] == 0.015 and f["loan_years"] == 30
    assert f["target"] == 100000 and f["monthly"] == 1508 and f["years"] == 5          # price − loan, saved at the same 4%
    assert got["previous"] == {"target": 60000, "monthly": 905, "loan_amount": 240000, "loan_rate": 0.065, "loan_years": 30}
    assert "borrowing $200,000 at 1.5% over 30 years" in got["text"] and not got["assumed"]
    assert CTX.scenario_change("borrow $250k at 6% for 15 years", HOUSE)["figures"]["loan_years"] == 15
    assert CTX.scenario_change("what if I borrow 200000?", HOUSE)["assumed"]          # no rate: the default, said
    assert CTX.scenario_change("How is it taxed?", HOUSE) is None                        # no loan
    assert CTX.scenario_change("borrow 400000 at 2%", HOUSE) is None                     # more than the house
    assert CTX.scenario_change(CHAIN[3], {**HOUSE, "goal_type": "education"}) is None


def test_the_changed_example_goes_to_goal_and_tax_and_is_saved():
    llm_module.set_llm(ScriptedLLM(router='{"intents": ["qa"], "confidence": 0.9}'))
    s = _turn(CHAIN[3], [{"role": "user", "content": CHAIN[2]}], {"question": CHAIN[2], "scenario": HOUSE, "tab": "Goals"})
    assert s["follow_up"] is True and s["intent"] == ["goal", "tax"]
    assert s["agents"] == ["Goal Planning", "Tax Education"]
    text = s["final_response"]
    for phrase in ("**$100,000** to pay up front", "**$40,000 more**", "**$1,508 a month**", "(instead of $905)",
                   "**$690 a month**", "**$827 a month lower**",                       # goal: savings and the loan payment
                   "**$2,964** of interest", "$6,264 vs $16,100", "personal (unsecured) loan's interest isn't deductible",
                   "$12,557 less interest to deduct"):                                 # tax
        assert phrase in text, phrase
    assert "retirement" not in text
    saved = s["context"]["scenario"]
    assert saved["figures"]["loan_amount"] == 200000 and saved["figures"]["target"] == 100000


def test_basic_mode_applies_the_change_too():
    s = _turn(CHAIN[3], [], {"question": CHAIN[2], "scenario": HOUSE, "tab": "Goals"})
    assert s["intent"] == ["goal", "tax"] and "**$690 a month**" in s["final_response"]
