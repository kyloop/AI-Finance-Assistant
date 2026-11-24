"""The calculator's income-tax path: "I earn $200,000, my stocks made $30,000, how much tax do I pay?".

The LLM only sorts the user's amounts into kinds (wages, long-term gains, property tax, ...) and reads the filing status;
Python checks that every amount is the user's and none is left out, and src/core/income_tax.py computes the estimate
from the year's rules (src/data/tax_rules.yaml). What the message leaves open (filing status, how long stocks were held,
whether a side job is W-2 or freelance) is assumed and said, and the alternative is worked out too."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.core import income_tax as T
from src.core.llm import ask_llm

from .jsonreply import first_json

KINDS = {
    "wages": "pay from a job (salary, wages, a W-2 part-time job)",
    "self_employment": "freelance, contractor, 1099 or own-business profit (only when the message says so)",
    "job_unspecified": "pay from a side or part-time job without saying whether it is W-2 or freelance",
    "interest_dividends": "interest, or dividends not said to be qualified",
    "qualified_dividends": "dividends the message says are qualified",
    "other_income": "other taxable income (rent received, a bonus not part of the salary, ...)",
    "short_term_gains": "profit from selling investments held a year or less",
    "long_term_gains": "profit from selling investments held more than a year",
    "stock_unspecified": "stock or investment earnings/profit/gains without saying how long they were held",
    "pre_tax_retirement": "traditional 401(k)/403(b)/IRA contributions",
    "state_local_taxes": "state or local income tax paid",
    "property_tax": "property / real estate tax paid",
    "mortgage_interest": "mortgage interest paid",
    "charity": "charitable donations",
    "not_tax_input": "an amount that doesn't change the federal tax (rent paid, savings, a price, a target)",
}

SYSTEM = (
    "You sort the amounts in a US personal income-tax question; you never compute tax. For EVERY dollar amount in the "
    "message, give one item {\"amount\": <number as a plain number, 200k -> 200000>, \"kind\": <kind>, \"loss\": "
    "<true only for a capital loss>, \"text\": <the words it came from>}. Kinds:\n"
    + "\n".join(f"- {k}: {v}" for k, v in KINDS.items())
    + "\nfiling_status: \"married_joint\" if the message says they file jointly or are married and file together, "
    "\"single\" if it says single, otherwise null. year: a tax year the message names, otherwise null.\n"
    "Reply with ONLY JSON: {\"items\": [...], \"filing_status\": null, \"year\": null}")

ASKS = re.compile(r"\b(how much|what|estimate|calculate|work out|figure out|total|owe|pay)\b.{0,80}\btax(es)?\b|"
                  r"\btax(es)?\b.{0,40}\b(owe|pay|due|bill)\b", re.I | re.S)
INCOME = re.compile(r"\b(earn\w*|salary|income|wages?|make|made|paid|job|dividends?|gains?|profit|bonus)\b", re.I)
# the user's amounts: 200000, 200,000, $200k, 1.5 million (not years like 2026, nor percentages)
AMOUNT = re.compile(r"\$?\b(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|thousand|m|million)?\b(?!\s*%)", re.I)
SOURCES = [{"id": "calc:irs-2026", "title": "IRS: tax inflation adjustments for tax year 2026",
            "url": "https://www.irs.gov/newsroom/irs-releases-tax-inflation-adjustments-for-tax-year-2026-including-amendments-from-the-one-big-beautiful-bill"}]


def asks_income_tax(text: str) -> bool:
    """A question asking for the tax on the user's own income, with at least one amount."""
    return bool(ASKS.search(text) and INCOME.search(text) and amounts(text))


def amounts(text: str) -> list[float]:
    out = []
    for m in AMOUNT.finditer(text):
        n = float(m.group(1).replace(",", ""))
        scale = (m.group(2) or "").lower()
        n *= 1e3 if scale in ("k", "thousand") else 1e6 if scale in ("m", "million") else 1
        if n < 100 or (1900 <= n <= 2100 and not m.group(0).startswith("$") and "," not in m.group(1) and not scale):
            continue                                    # small numbers (ages, counts) and years
        out.append(n)
    return out


@dataclass
class Reading:
    inputs: T.TaxInputs
    year: int | None = None
    assumed: list[str] = field(default_factory=list)      # what we assumed, in words
    alternatives: list[tuple[str, dict]] = field(default_factory=list)    # (what if, field changes to the inputs)
    ignored: list[str] = field(default_factory=list)


def read(question: str, reply: dict | None) -> tuple[Reading | None, str]:
    """(reading, "") or (None, why it was rejected). Every amount must be one of the user's, and every amount of theirs used."""
    if not reply or not isinstance(reply.get("items"), list) or not reply["items"]:
        return None, "no amounts sorted"
    given = amounts(question)
    used: list[float] = []
    inp, r = T.TaxInputs(), Reading(T.TaxInputs())
    unspecified_stock = unspecified_job = 0.0
    for it in reply["items"]:
        try:
            amount, kind = abs(float(it["amount"])), str(it["kind"])
        except (KeyError, TypeError, ValueError):
            return None, f"unreadable item {it!r}"
        if kind not in KINDS:
            return None, f"unknown kind {kind}"
        if not any(abs(amount - g) < 0.5 for g in given):
            return None, f"{amount:,.0f} is not an amount in the question"
        used.append(amount)
        if kind == "not_tax_input":
            r.ignored.append(f"{it.get('text') or amount:}")
            continue
        if kind == "stock_unspecified":
            unspecified_stock += amount
            continue
        if kind == "job_unspecified":
            unspecified_job += amount
            continue
        sign = -1 if it.get("loss") and kind in ("short_term_gains", "long_term_gains") else 1
        setattr(inp, kind, getattr(inp, kind) + sign * amount)
    missing = [g for g in given if not any(abs(g - u) < 0.5 for u in used)]
    if missing:
        return None, "left out " + ", ".join(f"{m:,.0f}" for m in missing)
    status = reply.get("filing_status")
    inp.filing_status = status if status in T.STATUSES else "single"
    if status not in T.STATUSES:
        r.assumed.append("you file as **single** (married couples filing jointly get wider brackets and a $32,200 standard deduction)")
    if unspecified_job:
        inp.wages += unspecified_job
        r.assumed.append(f"the ${unspecified_job:,.0f} job pays a W-2 wage (if it is freelance or 1099 work, self-employment tax applies instead)")
        r.alternatives.append((f"the ${unspecified_job:,.0f} job is freelance (1099) work",
                               {"wages": -unspecified_job, "self_employment": unspecified_job}))
    if unspecified_stock:
        inp.long_term_gains += unspecified_stock
        r.assumed.append(f"the ${unspecified_stock:,.0f} from stocks is profit on shares sold after holding them **more than a year** "
                         "(long-term capital gains)")
        r.alternatives.append((f"the ${unspecified_stock:,.0f} came from shares held a year or less (short-term gains)",
                               {"long_term_gains": -unspecified_stock, "short_term_gains": unspecified_stock}))
    r.inputs = inp
    try:
        r.year = int(reply["year"]) if reply.get("year") else None
    except (TypeError, ValueError):
        r.year = None
    income = (inp.wages + inp.self_employment + inp.interest_dividends + inp.other_income + inp.short_term_gains
              + inp.long_term_gains + inp.qualified_dividends)
    if income <= 0:
        return None, "no income among the amounts"
    return r, ""


def changed(inp: T.TaxInputs, deltas: dict) -> T.TaxInputs:
    """The inputs with one assumption turned the other way (each alternative changes only its own amounts)."""
    return T.TaxInputs(**{**vars(inp), **{k: getattr(inp, k) + v for k, v in deltas.items()}})


def money(x: float) -> str:
    n = int(abs(x) + 0.5)                               # whole dollars, halves up
    return f"-${n:,}" if x < 0 else f"${n:,}"


def pct(x: float) -> str:
    return f"{x * 100:.4g}%"


INCOME_LABELS = [("wages", "Wages"), ("self_employment", "Self-employment income"), ("interest_dividends", "Interest and dividends"),
                 ("qualified_dividends", "Qualified dividends"), ("other_income", "Other income"),
                 ("short_term_gains", "Short-term capital gains"), ("long_term_gains", "Long-term capital gains")]


def render(r: Reading, est: dict, alts: list[tuple[str, dict]]) -> str:
    i, p = est["inputs"], est["payroll"]
    status = "single" if est["filing_status"] == "single" else "married filing jointly"
    lines = [f"**Estimated {est['year']} federal taxes** ({status})", "",
             "| Income | Amount |", "|---|---|"]
    lines += [f"| {label} | {money(i[k])} |" for k, label in INCOME_LABELS if i[k]]
    if est["capital_loss_deducted"]:
        lines.append(f"| Capital loss deducted (limit $3,000) | {money(est['capital_loss_deducted'])} |")
    lines.append(f"| **Total income** | **{money(est['gross_income'])}** |")
    if est["adjustments"]:
        lines.append(f"| Pre-tax contributions and half of self-employment tax | {money(-est['adjustments'])} |")
        lines.append(f"| **Adjusted gross income** | **{money(est['agi'])}** |")
    lines.append("")
    salt_note = ""
    if est["salt_paid"]:
        capped = est["salt_paid"] > est["salt_deduction"]
        salt_note = (f" State and local taxes, property tax included ({money(est['salt_paid'])}), count toward itemizing"
                     + (f", capped at {money(est['salt_cap'])}" if capped else f" in full (the cap is {money(est['salt_cap'])})") + ".")
    if est["itemizes"]:
        lines.append(f"**Deduction:** itemizing ({money(est['itemized'])}) beats the standard deduction ({money(est['standard'])}).{salt_note}")
    else:
        lines.append(f"**Deduction:** the standard deduction ({money(est['standard'])}) is larger than itemizing "
                     f"({money(est['itemized'])}), so it is used.{salt_note}"
                     + (" So the property tax does **not** lower your income tax here." if i["property_tax"] else ""))
    lines += ["", f"**Taxable income:** {money(est['agi'])} − {money(est['deduction'])} = **{money(est['taxable_income'])}**", ""]
    lines += ["| Taxed at | On | Tax |", "|---|---|---|"]
    lines += [f"| {pct(b['rate'])} (ordinary income {money(b['from'])}–{money(b['to'])}) | {money(b['amount'])} | {money(b['tax'])} |"
              for b in est["ordinary_rows"]]
    lines += [f"| {pct(b['rate'])} (long-term gains and qualified dividends) | {money(b['amount'])} | {money(b['tax'])} |"
              for b in est["preferential_rows"]]
    if est["niit"]:
        lines.append(f"| 3.8% net investment income tax | | {money(est['niit'])} |")
    lines.append(f"| **Federal income tax** | | **{money(est['income_tax'])}** |")
    lines += ["", f"Marginal rate on the next dollar of ordinary income: **{pct(est['marginal_rate'])}**; "
                  f"income tax as a share of total income: **{est['effective_rate'] * 100:.1f}%**.", ""]
    pay = [("Social Security (6.2%, up to $184,500 of wages)", p["social_security"]), ("Medicare (1.45%)", p["medicare"]),
           ("Self-employment tax (15.3% on 92.35% of earnings, Social Security part up to the wage base)", p["self_employment_tax"]),
           ("Additional Medicare tax (0.9% above the threshold)", p["additional_medicare"])]
    if p["total"]:
        lines += ["| Payroll taxes | Tax |", "|---|---|"] + [f"| {label} | {money(v)} |" for label, v in pay if v]
        lines += [f"| **Payroll taxes** | **{money(p['total'])}** |", ""]
    total = est["total_federal"] + est["property_tax"]
    lines.append(f"**Total: about {money(est['total_federal'])} in federal taxes** (income tax {money(est['income_tax'])}"
                 + (f" + payroll {money(p['total'])}" if p["total"] else "") + ")"
                 + (f", plus the {money(est['property_tax'])} property tax you pay locally, **{money(total)}** in all." if est["property_tax"] else "."))
    if r.assumed:
        lines += ["", "**Assumed:** " + "; ".join(r.assumed) + "."]
    for label, alt in alts:
        diff = alt["total_federal"] - est["total_federal"]
        lines.append(f"- If {label}: federal taxes would be **{money(alt['total_federal'])}** "
                     f"({'+' if diff >= 0 else '−'}{money(abs(diff))}).")
    if r.ignored:
        lines += ["", "Not used (doesn't change federal tax): " + "; ".join(r.ignored) + "."]
    lines += ["", "_Not included: state and local income tax, tax credits (child, education, ...), the alternative minimum "
                  "tax and the newer deductions for seniors, tips and overtime. This is an estimate from the published "
                  f"{est['year']} rules, not a tax return; Finnie computed every number in Python._"]
    return "\n".join(lines)


def answer(question: str, context: str = "") -> tuple[str | None, str]:
    """(answer text, trace) for an income-tax question; (None, why) when it isn't one this path can work out."""
    reply = first_json(ask_llm(SYSTEM, f"{context}\n\nMessage: {question}" if context else f"Message: {question}"))
    reading, why = read(question, reply)
    if reading is None:
        return None, f"income tax: {why} → general calculator"
    try:
        est = T.estimate(reading.inputs, reading.year)
    except ValueError as e:
        try:
            est = T.estimate(reading.inputs)
        except ValueError:
            return None, f"income tax: {e} → general calculator"
        reading.assumed.append(f"the {est['year']} rules ({e})")
    alts = [(label, T.estimate(changed(reading.inputs, d), est["year"])) for label, d in reading.alternatives]
    i = est["inputs"]
    shown = ", ".join(f"{k}={i[k]:,.0f}" for k in i if k != "filing_status" and i[k])
    return render(reading, est, alts), (f"income_tax.estimate({est['year']}, {est['filing_status']}, {shown}) → "
                                        f"income tax {money(est['income_tax'])}, federal total {money(est['total_federal'])}")


# ---------------------------------------------------------------- tax on a saved Goals plan, by account type
SAMPLE_INCOME_RATE = 0.22        # a common bracket, shown as a sample: the plan doesn't say the user's income


def plan_tax_text(g: dict, projection: dict, year: int | None = None) -> tuple[str, str]:
    """(text, trace) for "how much will my plan cost me in tax?": the plan doesn't say which account it is in, so the tax on
    its money is worked out for each kind. Computed here; the rates are the year's long-term gains rate for most incomes
    and a sample income-tax bracket, both said."""
    year, r = T.rules(year)
    years, current, monthly = g["horizon_years"], g.get("current_savings", 0) or 0, g.get("monthly_contribution", 0) or 0
    paid_in = current + monthly * 12 * years
    value = projection["projected_value"]
    growth = max(0.0, value - paid_in)
    ltcg = next(rate for _, rate in r["capital_gains"]["single"] if rate > 0)       # 15%: the rate most people pay
    taxable_tax, traditional_tax, deduction = growth * ltcg, value * SAMPLE_INCOME_RATE, paid_in * SAMPLE_INCOME_RATE
    text = "\n".join([
        f"**Tax on your {g['goal_type']} plan, by account** ({money(paid_in)} paid in, projected {money(value)} after "
        f"{years} years, so {money(growth)} of growth)", "",
        "| Where the money is | Tax | When |", "|---|---|---|",
        f"| Regular brokerage account | about **{money(taxable_tax)}**: {pct(ltcg)} of the {money(growth)} growth "
        f"(the long-term gains rate for most incomes; 0% at low incomes, 20% at high ones) | when you sell; dividends are taxed each year |",
        f"| Traditional 401(k) / IRA | about **{money(traditional_tax)}**: all {money(value)} is taxed as income when withdrawn, "
        f"at {pct(SAMPLE_INCOME_RATE)} **(sample rate)**; but the {money(paid_in)} you put in was deducted, saving about "
        f"{money(deduction)} at the same rate | when you withdraw |",
        "| Roth 401(k) / IRA | **$0** on qualified withdrawals (after age 59½ and 5 years); contributions get no deduction | — |",
        "", f"_Rates from the {year} federal rules; {pct(SAMPLE_INCOME_RATE)} is a sample bracket, not yours: tell me your "
            "income or the account and I'll work it out for you. State tax not included; Finnie computed every number in Python._"])
    return text, (f"plan tax by account ({money(paid_in)} in, {money(value)} out): taxable {money(taxable_tax)}, "
                  f"traditional {money(traditional_tax)} at sample {pct(SAMPLE_INCOME_RATE)}, Roth $0")
