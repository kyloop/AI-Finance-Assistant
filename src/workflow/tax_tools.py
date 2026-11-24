"""The Tax agent's tools. Lookups read the knowledge base or the year's rules; every figure is computed in Python
(src/core/income_tax.py), the LLM only sorts the user's amounts (tax_calc). See mds/agent-tax-agent.md.

  search_tax_pages     the rule to explain, from the tax and retirement pages only
  get_tax_rules        a year's figures from src/data/tax_rules.yaml
  estimate_income_tax  the step-by-step federal estimate from the user's own income and deductions
  tax_on_plan          the saved Goals plan's tax, per kind of account
"""
from __future__ import annotations

from src.core import income_tax as T

from . import tax_calc as TC
from .tools import kb_search

TAX_CATEGORIES = ("taxes-and-accounts", "retirement")


def search_tax_pages(query: str, k: int | None = None) -> list[dict]:
    """Knowledge-base chunks for a tax question, from the tax and retirement pages only (best first)."""
    return kb_search(query, k, categories=TAX_CATEGORIES)


def get_tax_rules(year: int | None = None) -> tuple[int, dict]:
    """(year, that year's rules): brackets, standard deduction, capital-gains breakpoints, SALT cap, NIIT, payroll."""
    return T.rules(year)


def estimate_income_tax(question: str, context: str = "", profile: dict | None = None,
                        typed: str = "") -> tuple[TC.Estimate | None, str]:
    """(estimate, trace) for "I earn $X ... how much tax?"; with `profile` (the last estimate's figures, carried in the
    conversation) for a message that changes them: "what if I'm married?", "the stocks were short-term".
    (None, why) when the amounts can't be read or nothing changed."""
    return TC.follow_up(question, profile, typed) if profile else TC.answer(question, context)


def tax_on_plan(goal: dict, projection: dict) -> tuple[str, str]:
    """(table, trace): the plan's money taxed in a brokerage account, a traditional 401(k)/IRA and a Roth."""
    return TC.plan_tax_text(goal, projection)


TOOLS = {"search_tax_pages": search_tax_pages, "get_tax_rules": get_tax_rules,
         "estimate_income_tax": estimate_income_tax, "tax_on_plan": tax_on_plan}
