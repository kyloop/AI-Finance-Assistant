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

TAX_CATEGORIES = ("tax-notes", "taxes-and-accounts", "retirement")


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


# ---------------------------------------------------------------- this year's figures, for explanations
def _m(x: float) -> str:
    return f"${x:,.0f}"


def _figure_lines(year: int, r: dict) -> list[tuple[str, str]]:
    """(cue, line) for each figure: the line is quoted when the question matches the cue."""
    L, sd, cg = r.get("limits") or {}, r["standard_deduction"], r["capital_gains"]
    ct, ei = r["credits"]["child"], r["credits"]["earned_income"]
    out = [
        (r"standard deduction|deduct|itemi[sz]", f"Standard deduction: {_m(sd['single'])} single, {_m(sd['married_joint'])} "
         f"married filing jointly, {_m(sd['head_of_household'])} head of household; {_m(r['additional_standard_deduction']['unmarried'])} "
         f"more if 65+ or blind ({_m(r['additional_standard_deduction']['married'])} each if married)"),
        (r"bracket|rate|marginal", "Tax brackets: 10%, 12%, 22%, 24%, 32%, 35%, 37%; for a single filer the 22% bracket starts at "
         f"{_m(r['brackets']['single'][1][0])} and the 24% at {_m(r['brackets']['single'][2][0])} of taxable income"),
        (r"capital gain|long[- ]term|dividend|sell|sold|stock|crypto", f"Long-term capital gains: 0% up to {_m(cg['single'][0][0])} "
         f"of taxable income single ({_m(cg['married_joint'][0][0])} joint), 15% up to {_m(cg['single'][1][0])} "
         f"({_m(cg['married_joint'][1][0])}), 20% above; plus 3.8% net investment income tax above "
         f"{_m(r['niit']['threshold']['single'])} ({_m(r['niit']['threshold']['married_joint'])} joint)"),
        (r"salt|state and local|property tax", f"SALT deduction cap: {_m(r['salt']['cap'])} (reduced above "
         f"{_m(r['salt']['phase_down_start'])} of income, never below {_m(r['salt']['floor'])}); it was $10,000 for 2018-2024"),
        (r"child tax credit|child credit|kids?|children|dependent", f"Child tax credit: {_m(ct['amount'])} per child under 17, up "
         f"to {_m(ct['refundable'])} refundable; {_m(ct['other_dependent'])} for other dependents; reduced above "
         f"{_m(ct['phase_out_start']['single'])} ({_m(ct['phase_out_start']['married_joint'])} joint)"),
        (r"earned income|eitc|\beic\b", f"Earned income credit: up to {_m(ei['max_credit'][0])} (no children), "
         f"{_m(ei['max_credit'][1])} (one), {_m(ei['max_credit'][2])} (two), {_m(ei['max_credit'][3])} (three or more)"),
        (r"senior|65|tip|overtime|car loan|auto loan|big beautiful", "2025-2028 deductions (One Big Beautiful Bill Act): $6,000 "
         "per person 65+, tips up to $25,000, overtime premium up to $12,500 ($25,000 joint), car-loan interest up to $10,000; "
         "each reduced at higher incomes"),
    ]
    if L:
        w, ira, roth, hsa = L["workplace_plan"], L["ira"], L["roth_ira_phase_out"], L["hsa"]
        out += [
            (r"401|403|457|thrift|tsp|workplace|retirement plan|contribut", f"401(k)/403(b)/457/TSP: {_m(w['employee'])} a year, "
             f"plus {_m(w['catch_up_50'])} catch-up at 50+ ({_m(w['catch_up_60_63'])} at ages 60-63); earners over "
             f"{_m(w['roth_catch_up_wage_line'])} must make catch-ups as Roth"),
            (r"\bira\b|roth|contribut|retirement account", f"IRA (traditional and Roth combined): {_m(ira['limit'])}, plus "
             f"{_m(ira['catch_up_50'])} at 50+"),
            (r"roth", f"Roth IRA income limits: contributions phase out between {_m(roth['single'][0])} and {_m(roth['single'][1])} "
             f"single, {_m(roth['married_joint'][0])} and {_m(roth['married_joint'][1])} married filing jointly"),
            (r"hsa|health savings", f"HSA: {_m(hsa['self_only'])} self-only, {_m(hsa['family'])} family, plus "
             f"{_m(hsa['catch_up_55'])} at 55+"),
            (r"gift", f"Gift tax: {_m(L['gift_annual_exclusion'])} per recipient a year without filing; lifetime estate and "
             f"gift exemption {_m(L['estate_gift_exemption'])} per person"),
            (r"estate|inherit|death|heir", f"Estate tax: exemption {_m(L['estate_gift_exemption'])} per person "
             f"({_m(2 * L['estate_gift_exemption'])} for a couple), top rate {L['estate_tax_top_rate'] * 100:.0f}% above it"),
            (r"home|house|residence", f"Selling your main home: up to {_m(L['home_sale_exclusion']['single'])} of gain tax-free "
             f"({_m(L['home_sale_exclusion']['married_joint'])} married filing jointly) if you owned and lived in it 2 of the "
             "last 5 years"),
            (r"social security|benefits", "Social Security benefits: up to 50% taxable when income plus half the benefits is over "
             f"{_m(L['social_security_benefits_taxed']['up_to_50_percent']['single'])} single "
             f"({_m(L['social_security_benefits_taxed']['up_to_50_percent']['married_joint'])} joint), up to 85% over "
             f"{_m(L['social_security_benefits_taxed']['up_to_85_percent']['single'])} "
             f"({_m(L['social_security_benefits_taxed']['up_to_85_percent']['married_joint'])}); these lines aren't indexed"),
            (r"\brmd\b|required minimum|withdraw", f"Required minimum distributions start at {L['rmd_age']['born_1951_to_1959']} "
             f"(born 1951-1959) or {L['rmd_age']['born_1960_or_later']} (born 1960 or later)"),
        ]
    return out


def current_figures(question: str, year: int | None = None, most: int = 4) -> str:
    """This year's figures the question touches, from the rules file, as lines for the tax agent's answer ('' if none).
    Wikipedia pages often give an older year's numbers; these are the ones to state."""
    import re
    year, r = T.rules(year)
    lines = [line for cue, line in _figure_lines(year, r) if re.search(cue, question, re.I)][:most]
    if not lines:
        return ""
    return (f"**Current {year} figures (IRS), newer than any figure in the pages below:**\n"
            + "\n".join(f"- {line}" for line in lines) + "\n\n")
