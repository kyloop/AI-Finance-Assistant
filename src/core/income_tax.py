"""US federal income and payroll tax estimate from a year's income and deductions. Pure Python, no LLM: the rules
(brackets, standard deduction, capital-gains breakpoints, SALT cap, NIIT, FICA) are in src/data/tax_rules.yaml.

Covers single and married filing jointly, wages, self-employment income, interest and ordinary dividends, other
ordinary income, short- and long-term capital gains, qualified dividends, pre-tax retirement contributions and the
itemized deductions most people have (state/local taxes, mortgage interest, charity). Leaves out credits, the AMT,
state income tax, the senior and other OBBBA deductions, and phase-outs other than the SALT cap's."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import yaml

RULES_FILE = Path(__file__).resolve().parent.parent / "data" / "tax_rules.yaml"
STATUSES = ("single", "married_joint")


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
    state_local_taxes: float = 0.0           # state/local income or sales tax paid (SALT)
    property_tax: float = 0.0                # real estate tax paid (SALT)
    mortgage_interest: float = 0.0
    charity: float = 0.0


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
    agi = max(0.0, gross - payroll["half_se_deduction"] - inp.pre_tax_retirement)

    s = r["salt"]
    salt_cap = max(s["floor"], s["cap"] - s["phase_down_rate"] * max(0.0, agi - s["phase_down_start"]))
    salt_paid = max(inp.state_local_taxes, 0.0) + max(inp.property_tax, 0.0)
    salt = min(salt_paid, salt_cap)
    itemized = salt + max(inp.mortgage_interest, 0.0) + max(inp.charity, 0.0)
    standard = r["standard_deduction"][status]
    deduction = max(standard, itemized)

    taxable = max(0.0, agi - deduction)
    preferential = min(taxable, lt + qdiv)
    ordinary_taxable = taxable - preferential
    ordinary_tax, ordinary_rows = bracket_tax(ordinary_taxable, r["brackets"][status])
    pref_tax, pref_rows = preferential_tax(ordinary_taxable, preferential, r["capital_gains"][status])
    nii = max(0.0, inp.interest_dividends + st + lt + qdiv + loss)
    niit = r["niit"]["rate"] * min(nii, max(0.0, agi - r["niit"]["threshold"][status]))
    income_tax = ordinary_tax + pref_tax + niit
    marginal = ordinary_rows[-1]["rate"] if ordinary_rows else _bands(r["brackets"][status])[0][1]
    return {
        "year": year, "filing_status": status, "inputs": asdict(inp),
        "gross_income": gross, "short_term_taxed": st, "long_term_taxed": lt, "capital_loss_deducted": loss,
        "adjustments": payroll["half_se_deduction"] + inp.pre_tax_retirement, "agi": agi,
        "salt_paid": salt_paid, "salt_cap": salt_cap, "salt_deduction": salt, "itemized": itemized, "standard": standard,
        "itemizes": itemized > standard, "deduction": deduction,
        "taxable_income": taxable, "ordinary_taxable": ordinary_taxable, "preferential_income": preferential,
        "ordinary_tax": ordinary_tax, "ordinary_rows": ordinary_rows, "preferential_tax": pref_tax, "preferential_rows": pref_rows,
        "niit": niit, "income_tax": income_tax, "payroll": payroll,
        "property_tax": max(inp.property_tax, 0.0),
        "total_federal": income_tax + payroll["total"],
        "marginal_rate": marginal,
        "effective_rate": income_tax / gross if gross > 0 else 0.0,
    }
