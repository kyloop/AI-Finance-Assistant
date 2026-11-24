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
    rows: list[tuple[str, float, str, str]] = field(default_factory=list)   # (the user's words, amount, how it is treated, kind)


INCOME_KINDS = {"wages", "self_employment", "job_unspecified", "interest_dividends", "qualified_dividends", "other_income",
                "short_term_gains", "long_term_gains", "stock_unspecified"}
TREATED = {"wages": "wages (job pay)", "self_employment": "self-employment income", "job_unspecified": "wages (job pay), assumed W-2",
           "interest_dividends": "interest / ordinary dividends", "qualified_dividends": "qualified dividends",
           "other_income": "other taxable income", "short_term_gains": "short-term capital gains",
           "long_term_gains": "long-term capital gains", "stock_unspecified": "long-term capital gains (assumed)",
           "pre_tax_retirement": "pre-tax retirement contribution", "state_local_taxes": "state/local tax (itemized deduction)",
           "property_tax": "property tax (itemized deduction)", "mortgage_interest": "mortgage interest (itemized deduction)",
           "charity": "charitable gift (itemized deduction)", "not_tax_input": "not used: doesn't change federal tax"}


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
        loss = it.get("loss") and kind in ("short_term_gains", "long_term_gains")
        r.rows.append((" ".join(str(it.get("text") or "").split()) or f"{amount:,.0f}", -amount if loss else amount,
                       TREATED[kind] + (" (loss)" if loss else ""), kind))
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
    """The estimate as numbered steps: what each step means in plain words, then the working with the user's numbers."""
    i, p, year = est["inputs"], est["payroll"], est["year"]
    single = est["filing_status"] == "single"
    who = "single filers" if single else "married couples filing jointly"
    _, rules = T.rules(year)
    L = [f"**Estimated {year} federal taxes** ({'single' if single else 'married filing jointly'}), step by step", "",
         "**Your numbers**", "", "| You said | Amount | Treated as |", "|---|---|---|"]
    L += [f"| {text} | {money(amount)} | {treated} |" for text, amount, treated, _ in r.rows]
    step = 0

    def head(title: str, why: str) -> None:
        nonlocal step
        step += 1
        L.extend(["", f"**Step {step}. {title}**"] + ([why] if why else []) + [""])

    # 1. income
    parts = [(label, i[k]) for k, label in INCOME_LABELS if i[k]]
    head("Add up your income",
         "Income tax starts from everything you earned in the year: pay from jobs and profit from investments you sold. "
         + ("Taxes you paid, like property tax, are not income; they come in at step 2." if i["property_tax"] or i["state_local_taxes"] else ""))
    yours = [(amount, treated) for _, amount, treated, kind in r.rows if kind in INCOME_KINDS]
    if yours:                                           # each of the user's amounts, in their order
        L.append(f"- {' + '.join(money(a) for a, _ in yours).replace('+ -$', '− $')} = **{money(sum(a for a, _ in yours))}**")
    else:
        L.append(f"- {' + '.join(money(v) for _, v in parts)} = **{money(sum(v for _, v in parts))}**")
    if est["capital_loss_deducted"]:
        L.append(f"- Your investments lost money overall: at most $3,000 of the loss can be subtracted from other income, "
                 f"so total income is **{money(est['gross_income'])}**.")
    if est["adjustments"]:
        L.append(f"- Subtract pre-tax retirement contributions and half of the self-employment tax: "
                 f"{money(est['gross_income'])} − {money(est['adjustments'])} = **{money(est['agi'])}** (adjusted gross income)")

    # 2. deduction
    head("Choose your deduction",
         f"Before tax is worked out you subtract a deduction: either the standard deduction ({money(est['standard'])} for {who} "
         f"in {year}) or your itemized deductions (state and local taxes, property tax included, up to {money(rules['salt']['cap'])}; "
         "mortgage interest; gifts to charity), whichever is larger.")
    items = []
    if est["salt_paid"]:
        capped = est["salt_paid"] > est["salt_deduction"]
        salt_words = ("property tax" if not i["state_local_taxes"] else "state and local taxes" if not i["property_tax"]
                      else "state/local and property taxes")
        items.append(f"{salt_words} {money(est['salt_paid'])}"
                     + (f", capped at {money(est['salt_cap'])}" if capped else ""))
    if i["mortgage_interest"]:
        items.append(f"mortgage interest {money(i['mortgage_interest'])}")
    if i["charity"]:
        items.append(f"charity {money(i['charity'])}")
    L.append(f"- Itemized: {' + '.join(items)} = {money(est['itemized'])}" if len(items) > 1
             else f"- Itemized: {items[0] if items else 'nothing you mentioned, $0'}")
    L.append(f"- Standard: {money(est['standard'])}")
    if est["itemizes"]:
        L.append(f"- Itemizing is larger, so you deduct **{money(est['deduction'])}**.")
    else:
        L.append(f"- The standard deduction is larger, so you deduct **{money(est['deduction'])}**"
                 + (". Your property tax doesn't lower your income tax here: you'd get the same deduction without it."
                    if i["property_tax"] else "."))

    # 3. taxable income
    head("Work out your taxable income", "Taxable income is income minus the deduction. "
         + ("Long-term gains and qualified dividends in it are taxed at their own, lower rates (step 5), so they are split off."
            if est["preferential_income"] else ""))
    L.append(f"- {money(est['agi'])} − {money(est['deduction'])} = **{money(est['taxable_income'])}**")
    if est["preferential_income"]:
        L.append(f"- Of this, {money(est['preferential_income'])} is long-term gains and qualified dividends, and "
                 f"{money(est['taxable_income'])} − {money(est['preferential_income'])} = **{money(est['ordinary_taxable'])}** "
                 "is ordinary income.")

    # 4. brackets
    head("Tax the ordinary income bracket by bracket",
         "The US taxes income in slices: each slice pays its own rate, and only the part above a cutoff pays the higher rate. "
         "Earning more never makes the earlier slices cost more.")
    for b in est["ordinary_rows"]:
        span = money(b["amount"]) if b["from"] == 0 else f"({money(b['to'])} − {money(b['from'])}) = {money(b['amount'])}"
        L.append(f"- {pct(b['rate'])} on {span}: {pct(b['rate'])} × {money(b['amount'])} = {money(b['tax'])}")
    L.append(f"- Ordinary income tax: **{money(est['ordinary_tax'])}**")

    # 5. long-term gains
    if est["preferential_rows"]:
        bands = rules["capital_gains"][est["filing_status"]]
        head("Tax the long-term gains at their lower rates",
             f"Profit on investments held more than a year (and qualified dividends) is taxed at 0%, 15% or 20%, depending on "
             f"where it falls when stacked on top of your ordinary income: 0% up to {money(bands[0][0])} of taxable income, 15% "
             f"up to {money(bands[1][0])}, 20% above.")
        for b in est["preferential_rows"]:
            L.append(f"- It sits between {money(b['from'])} and {money(b['to'])} of taxable income, so "
                     f"{pct(b['rate'])} × {money(b['amount'])} = {money(b['tax'])}")
        L.append(f"- Long-term gains tax: **{money(est['preferential_tax'])}**")

    # 6. NIIT
    if est["niit"]:
        thr = rules["niit"]["threshold"][est["filing_status"]]
        over = est["agi"] - thr
        nii = est["niit"] / rules["niit"]["rate"]
        head("Add the net investment income tax",
             f"Above {money(thr)} of income ({who}), investment income pays an extra 3.8% on whichever is smaller: the "
             "investment income, or the income over that line.")
        L.append(f"- Income over the line: {money(est['agi'])} − {money(thr)} = {money(over)}")
        L.append(f"- The smaller of that and your investment income is {money(nii)}: 3.8% × {money(nii)} = **{money(est['niit'])}**")

    # 7. income tax
    pieces = [est["ordinary_tax"], est["preferential_tax"], est["niit"]]
    head("Federal income tax", "Add the pieces.")
    L.append(f"- {' + '.join(money(x) for x in pieces if x)} = **{money(est['income_tax'])}**")
    L.append(f"- That is {est['effective_rate'] * 100:.1f}% of your total income; your next dollar of ordinary income "
             f"would be taxed at {pct(est['marginal_rate'])}.")

    # 8. payroll
    if p["total"]:
        pr = rules["payroll"]
        head("Payroll taxes on your pay",
             f"Separately from income tax, pay is taxed for Social Security ({pct(pr['social_security_rate'])} on wages up to "
             f"{money(pr['social_security_wage_base'])}) and Medicare ({pct(pr['medicare_rate'])} on all wages, plus "
             f"{pct(pr['additional_medicare_rate'])} above {money(pr['additional_medicare_threshold'][est['filing_status']])}). "
             "Self-employed people pay both the worker's and the employer's share (15.3% on 92.35% of earnings). "
             "Investment profit isn't taxed here.")
        wages = i["wages"]
        if p["social_security"]:
            base = min(wages, pr["social_security_wage_base"])
            L.append(f"- Social Security: {pct(pr['social_security_rate'])} × {money(base)} = {money(p['social_security'])}"
                     + (f" (only the first {money(base)} of your {money(wages)})" if wages > base else ""))
        if p["medicare"]:
            L.append(f"- Medicare: {pct(pr['medicare_rate'])} × {money(wages)} = {money(p['medicare'])}")
        if p["self_employment_tax"]:
            L.append(f"- Self-employment tax on {money(i['self_employment'])}: {money(p['self_employment_tax'])} "
                     "(Social Security part only up to what your wages left of the wage base)")
        if p["additional_medicare"]:
            L.append(f"- Additional Medicare: {pct(pr['additional_medicare_rate'])} × "
                     f"{money(p['additional_medicare'] / pr['additional_medicare_rate'])} = {money(p['additional_medicare'])}")
        L.append(f"- Payroll taxes: **{money(p['total'])}** (usually already withheld from your paycheck)")

    # total
    head("Total", "")
    total = est["total_federal"] + est["property_tax"]
    L.append(f"- Federal: {money(est['income_tax'])}" + (f" + {money(p['total'])}" if p["total"] else "")
             + f" = **{money(est['total_federal'])}**")
    if est["property_tax"]:
        L.append(f"- With the {money(est['property_tax'])} property tax (paid to your local government): **{money(total)}** in all")

    if r.assumed:
        L += ["", "**What I assumed** (tell me if any is wrong and I'll redo it)"] + [f"- {a[0].upper()}{a[1:]}." for a in r.assumed]
    if alts:
        L += ["", "**If an assumption is different**"]
        for label, alt in alts:
            diff = alt["total_federal"] - est["total_federal"]
            L.append(f"- If {label}: federal taxes would be **{money(alt['total_federal'])}** "
                     f"({'+' if diff >= 0 else '−'}{money(abs(diff))})")
    if r.ignored:
        L += ["", "Not used (doesn't change federal tax): " + "; ".join(r.ignored) + "."]
    L += ["", "_Not included: state and local income tax, tax credits (child, education, ...), the alternative minimum "
              "tax and the newer deductions for seniors, tips and overtime. This is an estimate from the published "
              f"{year} rules, not a tax return; Finnie computed every number in Python._"]
    return "\n".join(L)


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
