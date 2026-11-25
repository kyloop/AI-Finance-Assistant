"""US federal income and payroll tax estimate from a year's income and deductions. Pure Python, no LLM: the rules
(brackets, standard deduction, capital-gains breakpoints, SALT cap, NIIT, FICA) are in src/data/tax_rules.yaml.

Covers all four filing statuses; wages, self-employment income, interest and dividends, other ordinary income, short- and
long-term capital gains; pre-tax retirement contributions; the standard deduction (with the 65+/blind addition) or the
itemized deductions most people have (state/local taxes, mortgage interest, charity); the One Big Beautiful Bill Act
deductions (seniors, tips, overtime, car-loan interest); and the common credits: child tax credit and credit for other
dependents, earned income credit, child and dependent care credit, American Opportunity and Lifetime Learning credits.
Leaves out the AMT, state income tax, the saver's and other credits, and the earned income credit's investment-income
test; married filing separately gets none of the credits and new deductions that require a joint return."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import yaml

RULES_FILE = Path(__file__).resolve().parent.parent / "data" / "tax_rules.yaml"
STATUSES = ("single", "married_joint", "head_of_household", "married_separate")


@dataclass
class TaxInputs:
    """A year's figures, in dollars. Losses are negative capital gains."""
    filing_status: str = "single"
    wages: float = 0.0                       # W-2 pay (payroll taxes withheld)
    self_employment: float = 0.0             # net self-employment / 1099 earnings (self-employment tax applies)
    interest_dividends: float = 0.0          # interest and non-qualified dividends: ordinary rates, counts for NIIT
    other_income: float = 0.0                # other ordinary income (not investment income)
    short_term_gains: float = 0.0            # assets held a year or less
    long_term_gains: float = 0.0             # assets held more than a year
    qualified_dividends: float = 0.0
    pre_tax_retirement: float = 0.0          # traditional 401(k)/IRA contributions: lower taxable income, not payroll tax
    student_loan_interest: float = 0.0       # deducted above the line (up to $2,500, phased out by income)
    state_local_taxes: float = 0.0           # state/local income or sales tax paid (SALT)
    property_tax: float = 0.0                # real estate tax paid (SALT)
    mortgage_interest: float = 0.0
    charity: float = 0.0
    # One Big Beautiful Bill Act deductions (2025-2028), on top of the standard or itemized deduction
    tips: float = 0.0                        # qualified tips (already counted in wages)
    overtime_premium: float = 0.0            # the extra "half" of time-and-a-half overtime (already counted in wages)
    car_loan_interest: float = 0.0           # interest on a loan for a new US-assembled personal vehicle
    # household, for the extra standard deduction and the credits
    age_65_or_older: int = 0                 # filers (you, and a spouse on a joint return) 65 or older
    blind: int = 0
    children_under_17: int = 0               # qualifying children for the child tax credit (and the earned income credit)
    other_dependents: int = 0                # other dependents ($500 credit), e.g. a child 17+ or a parent
    care_expenses: float = 0.0               # child or dependent care paid so you can work
    college_expenses: float = 0.0            # tuition, fees and course materials
    students: int = 0                        # students the college expenses are for
    graduate_school: bool = False            # past the first four years of college: Lifetime Learning, not AOTC


@lru_cache(maxsize=1)
def rules_file() -> dict:
    with open(RULES_FILE) as f:
        return yaml.safe_load(f)


def rules(year: int | None = None) -> tuple[int, dict]:
    data = rules_file()
    year = int(year or data["default_year"])
    if year not in data["years"]:
        raise ValueError(f"no tax rules for {year} (have {', '.join(map(str, data['years']))})")
    return year, data["years"][year]


def _bands(table: list) -> list[tuple[float, float]]:
    return [(float("inf") if top is None else float(top), rate) for top, rate in table]


def bracket_tax(taxable: float, table: list) -> tuple[float, list[dict]]:
    """Tax on ordinary taxable income through progressive brackets, with the amount taxed in each."""
    tax, low, rows = 0.0, 0.0, []
    for top, rate in _bands(table):
        part = max(0.0, min(taxable, top) - low)
        if part > 0:
            rows.append({"rate": rate, "from": low, "to": min(taxable, top), "amount": part, "tax": part * rate})
            tax += part * rate
        low = top
        if taxable <= top:
            break
    return tax, rows


def preferential_tax(ordinary_taxable: float, preferential: float, table: list) -> tuple[float, list[dict]]:
    """Long-term gains and qualified dividends sit on top of ordinary income; each part is taxed at the capital-gains
    rate of the band it falls in."""
    tax, low, rows, start, end = 0.0, 0.0, [], ordinary_taxable, ordinary_taxable + preferential
    for top, rate in _bands(table):
        part = max(0.0, min(end, top) - max(start, low))
        if part > 0:
            rows.append({"rate": rate, "from": max(start, low), "to": min(end, top), "amount": part, "tax": part * rate})
            tax += part * rate
        low = top
    return tax, rows


def _net_gains(st: float, lt: float, loss_limit: float) -> tuple[float, float, float]:
    """(short-term taxed as ordinary, long-term taxed at preferential rates, capital loss deducted) after netting."""
    total = st + lt
    if total < 0:
        return 0.0, 0.0, -min(-total, loss_limit)
    if lt < 0:
        return total, 0.0, 0.0
    if st < 0:
        return 0.0, total, 0.0
    return st, lt, 0.0


def payroll_taxes(inp: TaxInputs, r: dict) -> dict:
    p, status = r["payroll"], inp.filing_status
    wages, se = max(inp.wages, 0.0), max(inp.self_employment, 0.0)
    ss = min(wages, p["social_security_wage_base"]) * p["social_security_rate"]
    medicare = wages * p["medicare_rate"]
    se_base = se * p["self_employment_base"]
    se_ss = min(se_base, max(0.0, p["social_security_wage_base"] - wages)) * 2 * p["social_security_rate"]
    se_medicare = se_base * 2 * p["medicare_rate"]
    additional = max(0.0, wages + se_base - p["additional_medicare_threshold"][status]) * p["additional_medicare_rate"]
    return {"social_security": ss, "medicare": medicare, "self_employment_tax": se_ss + se_medicare,
            "additional_medicare": additional, "half_se_deduction": (se_ss + se_medicare) / 2,
            "total": ss + medicare + se_ss + se_medicare + additional}


def estimate(inp: TaxInputs, year: int | None = None) -> dict:
    """The estimate, step by step: income, deductions, taxable income, tax by bracket, NIIT, payroll taxes."""
    if inp.filing_status not in STATUSES:
        raise ValueError(f"filing status must be one of {', '.join(STATUSES)}")
    year, r = rules(year)
    status = inp.filing_status
    st, lt, loss = _net_gains(inp.short_term_gains, inp.long_term_gains, r["capital_loss_limit"])
    qdiv = max(inp.qualified_dividends, 0.0)
    payroll = payroll_taxes(inp, r)
    gross = (inp.wages + inp.self_employment + inp.interest_dividends + inp.other_income + st + lt + qdiv + loss)
    agi_before = max(0.0, gross - payroll["half_se_deduction"] - inp.pre_tax_retirement)
    student_loan = student_loan_deduction(inp, agi_before, r)
    agi = max(0.0, agi_before - student_loan)

    s = {**r["salt"], **(r["salt"].get("separate") or {})} if status == "married_separate" else r["salt"]
    salt_cap = max(s["floor"], s["cap"] - s["phase_down_rate"] * max(0.0, agi - s["phase_down_start"]))
    salt_paid = max(inp.state_local_taxes, 0.0) + max(inp.property_tax, 0.0)
    salt = min(salt_paid, salt_cap)
    itemized = salt + max(inp.mortgage_interest, 0.0) + max(inp.charity, 0.0)
    standard = r["standard_deduction"][status]
    deduction = max(standard, itemized)

    if inp.age_65_or_older or inp.blind:
        extra = r["additional_standard_deduction"]["married" if status in ("married_joint", "married_separate") else "unmarried"]
        standard += extra * (inp.age_65_or_older + inp.blind)
        deduction = max(standard, itemized)
    new_deductions = obbba_deductions(inp, agi, r)
    taxable = max(0.0, agi - deduction - sum(d["amount"] for d in new_deductions))
    preferential = min(taxable, lt + qdiv)
    ordinary_taxable = taxable - preferential
    ordinary_tax, ordinary_rows = bracket_tax(ordinary_taxable, r["brackets"][status])
    pref_tax, pref_rows = preferential_tax(ordinary_taxable, preferential, r["capital_gains"][status])
    nii = max(0.0, inp.interest_dividends + st + lt + qdiv + loss)
    niit = r["niit"]["rate"] * min(nii, max(0.0, agi - r["niit"]["threshold"][status]))
    tax_before_credits = ordinary_tax + pref_tax + niit
    cr = credits(inp, agi, ordinary_tax + pref_tax, r)
    income_tax = tax_before_credits - cr["nonrefundable_used"] - cr["refundable"]
    marginal = ordinary_rows[-1]["rate"] if ordinary_rows else _bands(r["brackets"][status])[0][1]
    return {
        "year": year, "filing_status": status, "inputs": asdict(inp),
        "gross_income": gross, "short_term_taxed": st, "long_term_taxed": lt, "capital_loss_deducted": loss,
        "adjustments": payroll["half_se_deduction"] + inp.pre_tax_retirement + student_loan, "agi": agi,
        "student_loan_deduction": student_loan,
        "salt_paid": salt_paid, "salt_cap": salt_cap, "salt_deduction": salt, "itemized": itemized, "standard": standard,
        "itemizes": itemized > standard, "deduction": deduction,
        "taxable_income": taxable, "ordinary_taxable": ordinary_taxable, "preferential_income": preferential,
        "ordinary_tax": ordinary_tax, "ordinary_rows": ordinary_rows, "preferential_tax": pref_tax, "preferential_rows": pref_rows,
        "niit": niit, "tax_before_credits": tax_before_credits, "credits": cr, "new_deductions": new_deductions,
        "income_tax": income_tax, "payroll": payroll,
        "property_tax": max(inp.property_tax, 0.0),
        "total_federal": income_tax + payroll["total"],
        "marginal_rate": marginal,
        "effective_rate": income_tax / gross if gross > 0 else 0.0,
    }


def student_loan_deduction(inp: TaxInputs, magi: float, r: dict) -> float:
    """Student loan interest: up to the cap ($2,500), reduced in proportion across the phase-out range of modified AGI;
    none on a separate return."""
    sl = r.get("student_loan_interest")
    if not sl or inp.student_loan_interest <= 0 or inp.filing_status == "married_separate":
        return 0.0
    lo, hi = sl["phase_out"][inp.filing_status]
    allowed = min(inp.student_loan_interest, sl["cap"])
    share = 1.0 if magi <= lo else 0.0 if magi >= hi else (hi - magi) / (hi - lo)
    return allowed * share


def _steps(amount_over: float, step: float) -> int:
    """How many steps (each $step "or fraction thereof") an amount is over a threshold, as the tax code counts them."""
    return math.ceil(amount_over / step) if amount_over > 0 else 0


def obbba_deductions(inp: TaxInputs, agi: float, r: dict) -> list[dict]:
    """The One Big Beautiful Bill Act deductions (2025-2028), each {name, claimed, amount, reduced_by}: seniors ($6,000 per
    person 65+), qualified tips, the overtime premium, car-loan interest; each phased out above an income line. The first
    three need a joint return if married."""
    nd, status, out = r.get("new_deductions") or {}, inp.filing_status, []
    joint_only = status == "married_separate"
    key = "single" if status == "married_separate" else status

    def add(name, claimed, cap, start, reduce):
        if claimed <= 0:
            return
        allowed = 0.0 if joint_only and name != "car_loan_interest" else max(0.0, min(claimed, cap) - reduce(max(0.0, agi - start)))
        out.append({"name": name, "claimed": claimed, "amount": allowed, "cap": cap, "start": start,
                    "reduced_by": max(0.0, min(claimed, cap) - allowed)})
    if "senior" in nd and inp.age_65_or_older:
        sn = nd["senior"]
        add("senior", sn["amount"] * inp.age_65_or_older, sn["amount"] * inp.age_65_or_older, sn["phase_out_start"][key],
            lambda over: sn["rate"] * over)
    for name, claimed in (("tips", inp.tips), ("overtime", inp.overtime_premium), ("car_loan_interest", inp.car_loan_interest)):
        if name in nd and claimed:
            d = nd[name]
            cap = d["cap"][key] if isinstance(d["cap"], dict) else d["cap"]
            add(name, claimed, cap, d["phase_out_start"][key], lambda over, d=d: d["per_1000"] * _steps(over, 1000))
    return out


def credits(inp: TaxInputs, agi: float, tax_liability: float, r: dict) -> dict:
    """The credits, each {name, amount, refundable, note}: nonrefundable ones are used up to the income tax (before NIIT);
    refundable ones are paid even with no tax left. Married filing separately gets only the child tax credit here."""
    c, status = r.get("credits") or {}, inp.filing_status
    key = "single" if status == "married_separate" else status
    earned = max(0.0, inp.wages) + max(0.0, inp.self_employment)
    rows, refundable = [], []
    # child and dependent care: expenses up to $3,000 (one) / $6,000 (two or more), at 50% falling to 35% then 20%
    dc = c.get("dependent_care")
    if dc and inp.care_expenses and status != "married_separate":
        kids = max(1, inp.children_under_17 + inp.other_dependents)
        expenses = min(inp.care_expenses, dc["expense_cap"][1 if kids == 1 else 2], earned)
        rate = max(dc["middle_rate"], dc["top_rate"] - 0.01 * _steps(agi - dc["first_start"], dc["first_step"]))
        rate = max(dc["floor_rate"], rate - 0.01 * _steps(agi - dc["second_start"][key], dc["second_step"][key]))
        rows.append({"name": "child_and_dependent_care", "amount": expenses * rate, "rate": rate, "base": expenses})
    # education: AOTC (first four years, per student) or Lifetime Learning (20% of up to $10,000), phased out by income
    if inp.college_expenses and status != "married_separate" and "education_phase_out" in c:
        lo, hi = c["education_phase_out"][key]
        share = 1.0 if agi <= lo else 0.0 if agi >= hi else (hi - agi) / (hi - lo)
        if inp.graduate_school:
            ll = c["lifetime_learning"]
            base = min(inp.college_expenses, ll["expense_cap"])
            rows.append({"name": "lifetime_learning", "amount": base * ll["rate"] * share, "base": base, "share": share})
        else:
            ao, n = c["american_opportunity"], max(1, inp.students)
            each = inp.college_expenses / n
            full = n * (min(each, ao["full"]) + ao["partial_rate"] * min(max(0.0, each - ao["full"]), ao["partial"])) * share
            refundable.append({"name": "american_opportunity_refundable", "amount": full * ao["refundable_share"]})
            rows.append({"name": "american_opportunity", "amount": full * (1 - ao["refundable_share"]), "base": inp.college_expenses,
                         "share": share, "total": full})
    # child tax credit + credit for other dependents, reduced $50 per $1,000 over the line; part of it refundable
    ct = c.get("child")
    child_total = 0.0
    if ct and (inp.children_under_17 or inp.other_dependents):
        gross = ct["amount"] * inp.children_under_17 + ct["other_dependent"] * inp.other_dependents
        reduce = ct["per_1000"] * _steps(agi - ct["phase_out_start"][status], 1000)
        child_total = max(0.0, gross - reduce)
        rows.append({"name": "child_tax_credit", "amount": child_total, "gross": gross, "reduced_by": min(gross, reduce)})
    # nonrefundable credits in order, up to the tax
    left, used = max(0.0, tax_liability), []
    for row in rows:
        take = min(row["amount"], left)
        left -= take
        used.append({**row, "used": take})
    # the refundable part of the child tax credit: what wasn't used, up to $1,700 a child and 15% of earnings over $2,500
    if ct and inp.children_under_17:
        unused_child = next((u["amount"] - u["used"] for u in used if u["name"] == "child_tax_credit"), 0.0)
        unused_child = min(unused_child, child_total - ct["other_dependent"] * inp.other_dependents) if inp.other_dependents else unused_child
        actc = min(max(0.0, unused_child), ct["refundable"] * inp.children_under_17,
                   ct["refundable_rate"] * max(0.0, earned - ct["refundable_floor"]))
        if actc > 0:
            refundable.append({"name": "additional_child_tax_credit", "amount": actc})
    # earned income credit (not on a separate return); phased out on the larger of AGI and earned income
    ei = c.get("earned_income")
    if ei and status != "married_separate" and earned > 0:
        n = min(3, inp.children_under_17)
        start = ei["phase_out_start_joint" if status == "married_joint" else "phase_out_start"][n]
        credit = min(earned, ei["earned_amount"][n]) * ei["rates"][n]
        credit = max(0.0, min(credit, ei["max_credit"][n]) - ei["phase_out_rate"][n] * max(0.0, max(agi, earned) - start))
        if credit > 0:
            refundable.append({"name": "earned_income_credit", "amount": credit, "children": n})
    return {"nonrefundable": used, "nonrefundable_used": sum(u["used"] for u in used),
            "refundable": sum(x["amount"] for x in refundable), "refundable_rows": refundable}


# ---------------------------------------------------------------- what-ifs on top of an estimate (the tax agent's tools)
def marginal_effect(inp: TaxInputs, changes: dict, year: int | None = None) -> dict:
    """What a change to the inputs does: the estimate before and after, and how much of the change goes to tax.
    `changes` adds to the input fields ({"wages": 10000} for a raise, {"charity": 5000} for a gift)."""
    after_inp = TaxInputs(**{**asdict(inp), **{k: getattr(inp, k) + v for k, v in changes.items()}})
    before, after = estimate(inp, year), estimate(after_inp, year)
    amount = sum(changes.values())
    diff = {k: after[k] - before[k] for k in ("income_tax", "total_federal", "taxable_income")}
    diff["payroll"] = after["payroll"]["total"] - before["payroll"]["total"]
    return {"before": before, "after": after, "amount": amount, "diff": diff,
            "share": diff["total_federal"] / amount if amount else 0.0}


def compare_accounts(inp: TaxInputs, contribution: float, years: int, annual_return: float,
                     retirement_rates: tuple[float, ...] = (0.10, 0.12, 0.22, 0.24, 0.32), year: int | None = None) -> dict:
    """Traditional vs Roth for `contribution` dollars of pre-tax pay this year. Traditional: deducted now (the tax saved is
    worked out from the user's own estimate), grows untaxed, every dollar taxed as income when withdrawn. Roth: taxed now,
    so only the pay left after that tax goes in; qualified withdrawals are tax-free. With the same cost to you today, the
    one taxed at the lower rate wins: today's rate on that slice of pay vs the rate in retirement."""
    effect = marginal_effect(inp, {"pre_tax_retirement": contribution}, year)
    saved = -effect["diff"]["income_tax"]                        # payroll tax isn't saved by a 401(k)/IRA contribution
    rate_now = saved / contribution if contribution else 0.0
    growth = (1 + annual_return) ** years
    trad_balance = contribution * growth
    roth_in = contribution - saved                               # the same pre-tax pay, after the tax on it
    roth_balance = roth_in * growth
    rows = [{"rate": t, "traditional": trad_balance * (1 - t), "roth": roth_balance} for t in retirement_rates]
    return {"contribution": contribution, "years": years, "annual_return": annual_return, "tax_saved_now": saved,
            "rate_now": rate_now, "take_home_cost": contribution - saved, "traditional_balance": trad_balance,
            "roth_contribution": roth_in, "roth_balance": roth_balance, "rows": rows, "growth": growth,
            "before": effect["before"], "after": effect["after"]}


def capital_gain(proceeds: float, cost_basis: float, held_more_than_a_year: bool, rebought_within_30_days: bool = False,
                 inp: TaxInputs | None = None, year: int | None = None) -> dict:
    """A sale's gain or loss and its tax. A loss with substantially identical shares bought within 30 days before or after
    is a wash sale: not deductible now, added to the new shares' basis. With the user's other income (`inp`), the tax is
    the change in their estimate; without it, only the rates that apply are given."""
    gain = proceeds - cost_basis
    wash = gain < 0 and rebought_within_30_days
    out = {"proceeds": proceeds, "cost_basis": cost_basis, "gain": gain, "long_term": held_more_than_a_year,
           "wash_sale": wash, "effect": None}
    if inp is not None and not wash and gain:
        field = "long_term_gains" if held_more_than_a_year else "short_term_gains"
        out["effect"] = marginal_effect(inp, {field: gain}, year)
    return out
