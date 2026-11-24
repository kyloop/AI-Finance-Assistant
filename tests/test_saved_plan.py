"""Questions about the plan saved on the Goals tab: "explain my Goals plan" reaches the goal agent even when the router LLM
calls it Q&A, a figure asked about the plan ("how much tax if the plan runs as planned?") also gets the calculator with
the plan's own numbers, and the tax explanation isn't lost when the calculator only asks for details."""
from src.core import llm as llm_module
from src.workflow import nodes as N
from src.workflow.graph import run_chat
from tests.test_verifier import ScriptedLLM

SAVED = {"goal_type": "retirement", "target_amount": 1_000_000, "horizon_years": 10, "current_savings": 10_000,
         "monthly_contribution": 500, "risk_tolerance": "moderate"}
PROFILE = {"knowledge_level": "beginner", "risk_tolerance": "moderate"}


def ask(q, **kw):
    return run_chat(q, history=[], profile=PROFILE, holdings=[], db=None, saved_goal=SAVED, **kw)


def state(q, intents=(), saved=SAVED):
    return {"question": q, "original_question": q, "saved_goal": saved, "intent": list(intents), "profile": PROFILE}


def test_explain_my_goals_plan_goes_to_goal_agent_when_router_says_qa():
    llm_module.set_llm(ScriptedLLM(router='{"intents": ["qa"], "confidence": 0.9}'))
    s = ask("Can you explain my Goals plan?")
    assert s["intent"] == ["goal"] and "Goals** tab" in s["agent_outputs"]["goal"]["content"]


def test_explain_my_goals_plan_in_basic_mode():
    s = ask("Can you explain my Goals plan?")
    assert "goal" in s["intent"] and "$1,000,000" in s["final_response"]


def test_plan_reference_needs_a_saved_plan_and_a_reference():
    assert N._with_saved_plan(["qa"], state("What is the goal of diversification?")) == ["qa"]
    assert N._with_saved_plan(["qa"], state("Can you explain my Goals plan?", saved=None)) == ["qa"]
    assert N._with_saved_plan(["qa", "market"], state("How does my plan compare with the S&P 500?")) == ["qa", "market", "goal"]


def test_tax_figure_on_the_plan_adds_goal_and_calc():
    q = "How much tax do I need to take care of if the plan runs as planned?"
    assert N._with_saved_plan(["tax"], state(q)) == ["tax", "goal", "calc"]
    assert N._with_saved_plan(["tax"], state("How are gains in my plan taxed?")) == ["tax", "goal"]   # no figure asked


def test_plan_figures_are_the_users_and_computed_in_python():
    text = N.saved_plan_figures(state("How much tax if the plan runs as planned?"))
    assert "target 1000000 in 10 years" in text and "contributing 500 a month" in text
    assert "total paid in: 70000" in text and "projected value after 10 years: 100133.64" in text
    assert "investment growth (projected value minus paid in): 30133.64" in text
    assert N.saved_plan_figures(state("What is an ETF?")) == ""                  # not about the plan
    assert N.saved_plan_figures(state("How much tax?", saved=None)) == ""


def test_researched_explanation_is_kept_when_calculator_only_asks():
    explanation = {"agent": "tax", "status": "answered", "origin": "wikipedia", "content": "Gains are taxed when sold.", "sources": []}
    s = {"question": "How much tax on my plan?", "entities": {}, "profile": PROFILE, "trace": [],
         "agent_outputs": {"tax": {"agent": "tax", "status": "not_found", "content": "", "fallback": explanation},
                           "calc": {"agent": "calc", "status": "need_info", "content": "What tax rate applies?", "choices": []}}}
    out = N.synthesizer_node(s, {})
    assert "Gains are taxed when sold." in out["final_response"] and "What tax rate applies?" in out["final_response"]


def test_cost_me_on_the_tax_asks_for_a_figure():
    q = "How does my goal planning cost me on the tax?"
    assert N._with_saved_plan(["goal", "tax"], state(q)) == ["goal", "tax", "calc"]


def test_tax_agent_searches_how_the_plans_savings_are_taxed_and_gets_its_figures():
    from src.workflow import tools
    searched = []

    def searcher(query, k=None):
        searched.append(query)
        return [{"score": 0.8, "doc_id": "roth-ira", "doc_title": "Roth IRA", "section": "(lead)", "text": "Roth growth is tax-free.",
                 "source_url": "https://en.wikipedia.org/wiki/Roth_IRA", "category": "retirement", "piece": 0, "pieces": 1,
                 "tokens": 5, "section_tokens": 5}]
    tools.set_kb_searcher(searcher)
    q = "How does my goal planning affect my taxes?"
    s = {**state(q, ["goal", "tax"]), "entities": {"wiki_query": q}, "history": []}
    out = N.tax_node(s, {})
    content = out["agent_outputs"]["tax"]["content"]
    assert searched == N.PLAN_TAX_SEARCHES["retirement"]
    assert "$70,000 paid in over 10 years" in content and "$30,134 of investment growth" in content
    assert "Roth growth is tax-free." in content and out["trace"][0].startswith("tax: saved retirement plan")
    searched.clear()
    N.tax_node({**s, "saved_goal": None}, {})                     # no plan: the question itself is searched
    assert searched == [q]


def test_goal_agent_is_dropped_from_a_question_that_is_not_about_a_goal():
    q = "I earn 200000 a year and stock earning 30000. How much tax do I need to pay?"
    assert N._without_stray_goal(["goal", "tax", "calc"], state(q)) == ["tax", "calc"]
    assert N._without_stray_goal(["goal"], state("I want $50k for a down payment in 4 years")) == ["goal"]
    assert N._without_stray_goal(["goal", "tax"], state("How is my goal planning cost me on the tax?")) == ["goal", "tax"]


def test_tax_figure_on_the_plan_is_worked_out_per_account_in_python():
    llm_module.set_llm(ScriptedLLM())
    q = "How does my goal planning cost me on the tax?"
    out = N.calc_node({**state(q, ["goal", "tax", "calc"]), "history": []}, {})["agent_outputs"]["calc"]
    text = out["content"]
    assert out["verbatim"] and "$70,000 paid in, projected $100,134 after 10 years, so $30,134 of growth" in text
    assert "about **$4,520**: 15% of the $30,134 growth" in text           # long-term gains rate
    assert "about **$22,029**" in text and "saving about $15,400" in text   # 22% sample bracket
    assert "| Roth 401(k) / IRA | **$0**" in text
