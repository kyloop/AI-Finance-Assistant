"""The Tax agent's what-if tools as the user sees them: Roth vs traditional, what an extra amount does, a sale's gain.

Each takes the model's arguments, checks that every amount in them is the user's (in the message or in the carried
estimate), computes in Python (src/core/income_tax.py) and renders the working step by step, like the estimate. What the
message leaves out is assumed and said, never invented: the base income comes from the carried estimate or the
message, the years and return from the message or the Goals plan / risk profile."""
from __future__ import annotations

from datetime import date

from src.core import income_tax as T
from src.core.config import get_config

from .tax_calc import STATUS_WORDS, amounts, money, pct

import re

DEFAULT_YEARS = 20
# a tax figure the what-if tools work out (the calculator would only repeat it)
TAX_FIGURE = re.compile(r"\b(roth|traditional|401\(?k\)?|ira|capital gains?|sold|sell|bought|shares|raise|bonus|deduct\w*|"
                        r"contribut\w*|wash sale)\b", re.I)


class Refused(ValueError):
    """An argument that isn't the user's, or a question the tool can't answer: the reason, shown in the trace."""


def _mine(value, allowed: list[float], name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        v = abs(float(value))
    except (TypeError, ValueError):
        raise Refused(f"{name} {value!r} is not a number")
    if not any(abs(v - a) < 0.5 for a in allowed):
        raise Refused(f"{name} {v:,.0f} is not an amount you gave")
    return v


def _base_income(args: dict, allowed: list[float], profile: dict | None) -> float | None:
    """The base_income argument, which may repeat a figure of the carried estimate (the model passed the $120,000 the
    user gave a message earlier; it's ignored then, since the estimate is the base)."""
    carried = [float(it.get("amount") or 0) for it in (profile or {}).get("items") or []]
    return _mine(args.get("base_income"), allowed + carried, "base income")


def base_inputs(profile: dict | None, base_income: float | None) -> tuple[T.TaxInputs | None, str]:
    """The user's other income to measure against: the carried estimate, else the income the message gives (as wages)."""
    if profile:
        from .tax_calc import reading_from
        r, _ = reading_from(profile.get("items") or [], profile.get("filing_status"), profile.get("year"), profile.get("household"))
        if r is not None:
            return r.inputs, "your last estimate (" + STATUS_WORDS.get(profile.get("filing_status"), "not given").replace("not given", "single, assumed") + ")"
    if base_income:
        return T.TaxInputs(wages=base_income), f"{money(base_income)} of wages, single (assumed)"
    return None, ""


INCOME_FIELDS = {"wages": "a raise or bonus", "self_employment": "freelance income", "long_term_gains": "long-term gains",
                 "short_term_gains": "short-term gains", "interest_dividends": "interest or dividends",
                 "pre_tax_retirement": "a traditional 401(k)/IRA contribution", "charity": "a charitable gift",
                 "mortgage_interest": "mortgage interest", "state_local_taxes": "state or local tax",
                 "property_tax": "property tax"}


def marginal_effect(args: dict, question: str, profile: dict | None) -> tuple[str, str]:
    allowed = amounts(question)
    amount = _mine(args.get("amount"), allowed, "amount")
    kind = str(args.get("kind") or "wages")
    if amount is None or kind not in INCOME_FIELDS:
        raise Refused("no amount or kind")
    inp, base = base_inputs(profile, _base_income(args, allowed, profile))
    if inp is None:
        raise Refused("no income to measure against")
    sign = -1 if args.get("decrease") else 1
    m = T.marginal_effect(inp, {kind: sign * amount})
    b, a, d = m["before"], m["after"], m["diff"]
    label = INCOME_FIELDS[kind]
    lines = [f"**What {money(amount)} of {label} does to your {b['year']} federal taxes**, step by step", "",
             f"Measured against {base}.", ""]
    lines += ["**Step 1. Taxable income**",
              f"- Before: {money(b['taxable_income'])}. After: {money(a['taxable_income'])} ({'+' if d['taxable_income'] >= 0 else '−'}"
              f"{money(abs(d['taxable_income']))})."]
    if kind in ("charity", "mortgage_interest", "state_local_taxes", "property_tax"):
        lines.append(f"- This only lowers tax if you itemize: itemized {money(a['itemized'])} vs standard {money(a['standard'])}"
                     + (" → you itemize." if a["itemizes"] else " → the standard deduction is still larger, so it changes nothing."))
    lines += ["", "**Step 2. Income tax**",
              f"- {money(b['income_tax'])} → {money(a['income_tax'])} ({'+' if d['income_tax'] >= 0 else '−'}{money(abs(d['income_tax']))}); "
              f"your top bracket {'stays' if b['marginal_rate'] == a['marginal_rate'] else 'moves from ' + pct(b['marginal_rate']) + ' to'} "
              f"{pct(a['marginal_rate'])}."]
    if d["payroll"]:
        lines += ["", "**Step 3. Payroll taxes**", f"- {money(b['payroll']['total'])} → {money(a['payroll']['total'])} "
                  f"(+{money(d['payroll'])}: Medicare, and Social Security below its wage base)"]
    lines += ["", "**Result**",
              f"- Federal taxes go from {money(b['total_federal'])} to **{money(a['total_federal'])}** "
              f"({'+' if d['total_federal'] >= 0 else '−'}{money(abs(d['total_federal']))})."]
    if kind in ("wages", "self_employment", "long_term_gains", "short_term_gains", "interest_dividends") and sign > 0:
        lines.append(f"- Of the extra {money(amount)}, **{money(d['total_federal'])}** ({m['share'] * 100:.1f}%) goes to federal tax "
                     f"and you keep {money(amount - d['total_federal'])}.")
    elif d["total_federal"] < 0:
        lines.append(f"- It saves {money(-d['total_federal'])}, {(-m['share']) * 100:.1f}% of the {money(amount)}.")
    lines += ["", "_Federal only (no state tax); computed in Python from the published rules._"]
    return "\n".join(lines), f"marginal_effect({kind} {sign * amount:+,.0f}) → federal {d['total_federal']:+,.0f}"


def compare_accounts(args: dict, question: str, profile: dict | None, goal: dict | None = None) -> tuple[str, str]:
    allowed = amounts(question)
    contribution = _mine(args.get("contribution"), allowed, "contribution")
    if contribution is None:
        raise Refused("no contribution amount")
    inp, base = base_inputs(profile, _base_income(args, allowed, profile))
    if inp is None:
        raise Refused("no income to measure against")
    assumed = []
    years = args.get("years")
    if years and not any(abs(float(years) - n) < 0.01 for n in _small_numbers(question)):
        years = None                                       # not the user's
    if not years:
        years = (goal or {}).get("horizon_years") or DEFAULT_YEARS
        assumed.append(f"{years} years until you withdraw" + (" (your Goals plan's horizon)" if goal and goal.get("horizon_years") else ""))
    rate = args.get("annual_return_pct")
    if rate is not None and not any(abs(float(rate) - n) < 0.01 for n in _small_numbers(question)):
        rate = None
    if rate is None:
        risk = (goal or {}).get("risk_tolerance") or "moderate"
        rate = get_config()["risk_profiles"][risk] * 100
        assumed.append(f"a steady {rate:g}% yearly return ({risk} risk profile)")
    c = T.compare_accounts(inp, contribution, int(years), float(rate) / 100)
    lines = [f"**Traditional vs Roth for {money(contribution)} of your pay**, step by step", "",
             f"Measured against {base}.", "",
             "**Step 1. The tax today**",
             "A traditional 401(k)/IRA contribution is taken out before income tax; a Roth contribution is taxed first.",
             f"- Traditional: your income tax drops by **{money(c['tax_saved_now'])}**, so {money(contribution)} goes in and your "
             f"take-home pay falls by only {money(c['take_home_cost'])}.",
             f"- That is {c['rate_now'] * 100:.1f}% of the contribution: your tax rate today on that slice of pay.",
             f"- Roth, for the same {money(c['take_home_cost'])} out of your take-home pay: {money(c['roth_contribution'])} goes in.", "",
             f"**Step 2. Growth over {years} years at {float(rate):g}% a year**",
             "Neither account is taxed while it grows.",
             f"- Traditional: {money(contribution)} × {c['growth']:.3f} = {money(c['traditional_balance'])}",
             f"- Roth: {money(c['roth_contribution'])} × {c['growth']:.3f} = {money(c['roth_balance'])}", "",
             "**Step 3. The tax when you withdraw**",
             "Traditional withdrawals are taxed as income at your rate then; qualified Roth withdrawals (after 59½ and 5 years) "
             "are tax-free. Your rate in retirement isn't known yet, so here are common ones:", "",
             "| Your tax rate in retirement | Traditional, after tax | Roth | Better |", "|---|---|---|---|"]
    for row in c["rows"]:
        better = "about the same" if abs(row["traditional"] - row["roth"]) < 1 else (
            "traditional" if row["traditional"] > row["roth"] else "Roth")
        lines.append(f"| {pct(row['rate'])} | {money(row['traditional'])} | {money(row['roth'])} | {better} |")
    lines += ["", "**What decides it**",
              f"- If your tax rate in retirement is below today's {c['rate_now'] * 100:.1f}%, traditional ends up with more; "
              "above it, Roth does; equal, they come out the same.",
              "- A Roth also has no required withdrawals in your lifetime and leaves heirs tax-free money; a traditional account "
              "lowers your taxable income now (which can matter for other income limits)."]
    if assumed:
        lines += ["", "**Assumed:** " + "; ".join(assumed) + "."]
    lines += ["", "_An illustration, not a forecast: returns vary and tax rules change. Federal only; computed in Python._"]
    return "\n".join(lines), (f"compare_accounts({contribution:,.0f}, {years}y, {float(rate):g}%) → saved now "
                              f"{c['tax_saved_now']:,.0f} ({c['rate_now'] * 100:.1f}%)")


def _small_numbers(text: str) -> list[float]:
    import re
    return [float(n) for n in re.findall(r"(?<![\d,.$])(\d{1,2}(?:\.\d+)?)(?![\d,])", text)]


def capital_gain(args: dict, question: str, profile: dict | None) -> tuple[str, str]:
    allowed = amounts(question)
    shares = args.get("shares")
    if shares is not None and not any(abs(float(shares) - n) < 0.01 for n in _all_numbers(question)):
        raise Refused(f"shares {shares} is not a number you gave")
    buy, sell = (_price(args.get(k), question, k) for k in ("buy_price", "sell_price"))
    proceeds, basis = _mine(args.get("proceeds"), allowed, "proceeds"), _mine(args.get("cost_basis"), allowed, "cost basis")
    if shares and buy is not None and basis is None:
        basis = float(shares) * buy
    if shares and sell is not None and proceeds is None:
        proceeds = float(shares) * sell
    if proceeds is None or basis is None:
        raise Refused("needs what you paid and what you sold for")
    held_long, assumed = _held_long(args), []
    if held_long is None:
        held_long = True
        assumed.append("you held the shares **more than a year** (long-term)")
    inp, base = base_inputs(profile, _base_income(args, allowed, profile))
    g = T.capital_gain(proceeds, basis, held_long, bool(args.get("rebought_within_30_days")), inp)
    gain = g["gain"]
    lines = ["**Your gain or loss on the sale**, step by step", "", "**Step 1. Gain or loss**",
             "The taxable gain is what you sold for minus your cost basis (what you paid).",
             (f"- {money(proceeds)} − {money(basis)}" if not shares else
              f"- {float(shares):g} × {money(sell or proceeds / float(shares))} − {float(shares):g} × {money(buy or basis / float(shares))}"
              f" = {money(proceeds)} − {money(basis)}") + f" = **{money(gain)}** {'gain' if gain >= 0 else 'loss'}", "",
             "**Step 2. Short or long term**",
             "Shares held more than a year give a long-term gain (0%, 15% or 20%); a year or less, a short-term gain taxed like pay.",
             f"- {'Long-term' if held_long else 'Short-term'}" + (" (assumed)" if assumed else ""), ""]
    if g["wash_sale"]:
        lines += ["**Step 3. Wash sale**",
                  "You bought the same shares within 30 days of selling at a loss, so the loss can't be deducted now; it is added "
                  f"to the cost basis of the new shares (so {money(-gain)} lowers the gain when you sell them).", ""]
    elif g["effect"]:
        e = g["effect"]
        lines += ["**Step 3. Tax on it, with your other income**", f"Measured against {base}.",
                  f"- Federal taxes go from {money(e['before']['total_federal'])} to **{money(e['after']['total_federal'])}** "
                  f"({'+' if e['diff']['total_federal'] >= 0 else '−'}{money(abs(e['diff']['total_federal']))})" +
                  (f": {abs(e['share']) * 100:.1f}% of the {'gain' if gain >= 0 else 'loss'}." if gain else "."), ""]
        if gain < 0:
            lines.append("- A net loss lowers other income by at most $3,000 a year; the rest carries forward to later years.")
    else:
        _, rules = T.rules()
        cg = rules["capital_gains"]["single"]
        lines += ["**Step 3. The rate**", (f"- Long-term: 0% up to {money(cg[0][0])} of taxable income, 15% up to {money(cg[1][0])}, "
                  "20% above (single)." if held_long else "- Short-term: taxed at your income-tax bracket (10% to 37%)."),
                  "- Tell me your income and I'll work out the tax on it exactly.", ""]
    if assumed:
        lines.append("**Assumed:** " + "; ".join(assumed) + ".")
    lines += ["", "_Federal only; computed in Python._"]
    return "\n".join(lines), f"capital_gain({proceeds:,.0f} − {basis:,.0f}, {'long' if held_long else 'short'}) → {gain:+,.0f}"


def _all_numbers(text: str) -> list[float]:
    import re
    return [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def _price(value, question: str, name: str) -> float | None:
    if value in (None, ""):
        return None
    v = float(value)
    if not any(abs(v - n) < 0.005 for n in _all_numbers(question)):
        raise Refused(f"{name} {v:g} is not a price you gave")
    return v


def _held_long(args: dict) -> bool | None:
    if isinstance(args.get("held_more_than_a_year"), bool):
        return args["held_more_than_a_year"]
    try:
        bought, sold = date.fromisoformat(str(args.get("bought"))), date.fromisoformat(str(args.get("sold")))
    except ValueError:
        return None
    return (sold - bought).days > 365


TOOL_SPECS = [
    {"type": "function", "function": {"name": "estimate_income_tax", "description":
        "Work out the user's federal tax from income amounts given in the message (salary, gains, deductions). No arguments: "
        "the message's amounts are read separately.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "update_estimate", "description":
        "Redo the user's last tax estimate with what the message changes (filing status, an amount, how stocks were held, "
        "W-2 or freelance, an amount added or removed). Only when a LAST ESTIMATE is given.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "marginal_effect", "description":
        "How much of an extra amount goes to tax, or what a deduction saves: a raise, a bonus, more freelance income, a "
        "contribution, a gift. Measured against the last estimate, or base_income if the message gives the user's income.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "number", "description": "the extra amount, as the user gave it"},
            "kind": {"type": "string", "enum": list(INCOME_FIELDS)},
            "decrease": {"type": "boolean", "description": "true if the amount is less income (a pay cut)"},
            "base_income": {"type": "number", "description": "the user's income, only if the message gives it"}},
            "required": ["amount", "kind"]}}},
    {"type": "function", "function": {"name": "compare_accounts", "description":
        "Traditional vs Roth (401(k) or IRA) for a contribution amount; also what a 401(k) contribution saves in tax today.",
        "parameters": {"type": "object", "properties": {
            "contribution": {"type": "number"},
            "years": {"type": "number", "description": "years until withdrawal, only if the message gives it"},
            "annual_return_pct": {"type": "number", "description": "yearly return in percent, only if the message gives it"},
            "base_income": {"type": "number", "description": "the user's income, only if the message gives it"}},
            "required": ["contribution"]}}},
    {"type": "function", "function": {"name": "capital_gain", "description":
        "The gain or loss on selling shares or another asset and its tax: from shares and buy/sell prices, or cost basis "
        "and proceeds; short vs long term; wash sale if the same shares were bought back within 30 days of a loss.",
        "parameters": {"type": "object", "properties": {
            "shares": {"type": "number"}, "buy_price": {"type": "number"}, "sell_price": {"type": "number"},
            "cost_basis": {"type": "number", "description": "total paid"}, "proceeds": {"type": "number", "description": "total sold for"},
            "held_more_than_a_year": {"type": "boolean"}, "bought": {"type": "string", "description": "YYYY-MM-DD"},
            "sold": {"type": "string", "description": "YYYY-MM-DD"}, "rebought_within_30_days": {"type": "boolean"},
            "base_income": {"type": "number", "description": "the user's income, only if the message gives it"}}}}},
    {"type": "function", "function": {"name": "explain_rules", "description":
        "Explain a tax rule or account from the tax pages (no figures of the user's to work out).",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

CHOOSER_SYSTEM = (
    "You are the tax expert's planner in a personal-finance education app. Pick the ONE tool that answers the user's "
    "message and fill its arguments only with numbers the user gave (in the message or the LAST ESTIMATE); leave out any "
    "argument the user didn't give. Never compute anything yourself. A question about how a rule works, with no figures to "
    "work out, is explain_rules. A sale the user describes with its price and cost (\"I sold shares for $3,000 that cost "
    "$7,000 ... can I deduct the loss?\") is capital_gain, also when it asks whether the loss is deductible; a sale of the "
    "home they live in is estimate_income_tax.")


WHATIFS = {"marginal_effect": lambda a, q, p, **_: marginal_effect(a, q, p), "compare_accounts": compare_accounts,
           "capital_gain": lambda a, q, p, **_: capital_gain(a, q, p)}


# ---------------------------------------------------------------- a savings goal's tax (the worked example of a goal)
def savings_goal_tax(scenario: dict, profile: dict | None = None) -> tuple[str, str]:
    """How federal tax applies to saving for a goal ({kind: savings_goal, goal_type, figures: target, years, monthly,
    home_price, down_payment_pct}, context.scenario): the interest earned while saving, and for a house the first-home
    IRA withdrawal, the mortgage-interest and property-tax deductions against the standard deduction, and the home-sale
    exclusion. The user's rate comes from their last estimate when there is one, else common brackets are shown; every
    other assumption (yield, mortgage rate, property tax) is config.yaml's tax_assumptions and is said."""
    f = scenario.get("figures") or {}
    target, years = float(f.get("target") or 0), int(f.get("years") or 0)
    if target <= 0 or years <= 0:
        raise Refused("the example has no target or years")
    kind = scenario.get("goal_type") or "other"
    a = get_config().get("tax_assumptions") or {}
    rate = float(a.get("savings_rate", 0.04))
    brackets = [float(b) for b in a.get("brackets") or [0.12, 0.22, 0.24]]
    year, r = T.rules((profile or {}).get("year"))
    L = r.get("limits") or {}
    sd = r["standard_deduction"]
    inp, base = base_inputs(profile, None)
    # what is put away each month at the savings yield to reach the target (the example's own monthly may assume another return)
    from src.core.calculators import project_goal
    monthly = project_goal(target, years, 0, 0, rate)["required_monthly"]
    rows = T.savings_interest(monthly, years, rate)
    total_interest = sum(x["interest"] for x in rows)
    assumed = [f"the savings are kept in a high-yield savings account or CDs paying {rate * 100:g}% a year"]
    lines = [f"**How federal tax applies to {scenario.get('text') or f'saving {money(target)} over {years} years'}**, step by step", "",
             "Saving itself isn't taxed: the money you put aside is pay you already paid tax on. What tax touches is what "
             "the savings earn, and for a home, what you can deduct after you buy and when you sell.", "",
             "**Step 1. Tax on the interest while you save**",
             f"Interest from a savings account, CD or money-market fund is ordinary income, taxed at your top bracket the year "
             f"it is paid (your bank sends a Form 1099-INT). Saving about {money(monthly)} a month at {rate * 100:g}%"
             + (f" (the example's {money(f['monthly'])} a month assumed {'no' if f['monthly'] * 12 * years >= target - 1 else 'a different'} "
                "return)" if f.get("monthly") and abs(float(f["monthly"]) - monthly) > 1 else "") + ":", ""]
    if inp is not None:
        lines += [f"Measured against {base}.", "", "| Year | Interest earned | Federal tax on it |", "|---|---|---|"]
        taxes = []
        for x in rows:
            d = T.marginal_effect(inp, {"interest_dividends": x["interest"]}, year)["diff"]["total_federal"]
            taxes.append(d)
            lines.append(f"| {x['year']} | {money(x['interest'])} | {money(d)} |")
        lines += [f"| **Total** | **{money(total_interest)}** | **{money(sum(taxes))}** |", ""]
    else:
        lines += ["| Year | Interest earned | " + " | ".join(f"Tax at {pct(b)}" for b in brackets) + " |",
                  "|---|---|" + "---|" * len(brackets)]
        for x in rows:
            lines.append(f"| {x['year']} | {money(x['interest'])} | " + " | ".join(money(x["interest"] * b) for b in brackets) + " |")
        lines += [f"| **Total** | **{money(total_interest)}** | " + " | ".join(f"**{money(total_interest * b)}**" for b in brackets) + " |",
                  "", f"Which column is yours depends on your income: for a single filer in {year} the 22% bracket starts at "
                  f"{money(r['brackets']['single'][1][0])} of taxable income and the 24% at {money(r['brackets']['single'][2][0])}. "
                  "Tell me your income and I'll work out your own figure.", ""]
    lines += [f"- After {years} years you'd have about {money(rows[-1]['balance'])}: {money(monthly * 12 * years)} paid in plus "
              f"{money(total_interest)} of interest.",
              "- Treasury bills and I bonds are taxed federally too, but not by your state. Investing the money in a "
              "brokerage account instead gives capital gains (0%, 15% or 20% if held over a year), with the risk of a fall "
              "just before you need it.", ""]
    step = 2
    if kind == "house":
        price = float(f.get("home_price") or 0)
        share = float(f.get("down_payment_pct") or 0)
        if not price:
            share = share or 0.20
            price = target / share
            assumed.append(f"the target is a {share * 100:.0f}% down payment, so a home of about {money(price)}")
        ira = L.get("first_home_ira", 10000)
        top = brackets[len(brackets) // 2]
        lines += [f"**Step {step}. Using an IRA for part of the down payment**",
                  f"A first-time homebuyer (no home owned in the last 2 years) can take up to **{money(ira)}** in their "
                  "lifetime out of IRAs without the 10% early-withdrawal penalty; each spouse has their own "
                  f"{money(ira)}. A 401(k) has no such exception (a 401(k) loan is the usual route there).",
                  f"- Traditional IRA: no penalty, but the withdrawal is still taxed as income: {money(ira)} at {pct(top)} is "
                  f"{money(ira * top)} of tax (it saves the {money(ira * 0.10)} penalty).",
                  "- Roth IRA: your contributions come out tax- and penalty-free at any time. Earnings up to "
                  f"{money(ira)} are tax-free too if the Roth was opened at least 5 years ago; otherwise they're taxed but not "
                  "penalized.", ""]
        step += 1
        given = bool(f.get("loan_amount"))           # the user's loan ("if I borrow $200,000 at 1.5%"), else a typical mortgage
        m_rate = float(f.get("loan_rate") or a.get("mortgage_rate", 0.065))
        m_years = int(f.get("loan_years") or a.get("mortgage_years", 30))
        loan = float(f["loan_amount"]) if given else max(0.0, price - target)
        mort = T.mortgage_first_year(loan, m_rate, m_years)
        prop_rate = float(a.get("property_tax_rate", 0.011))
        prop = price * prop_rate
        cap_debt = L.get("mortgage_debt_limit", 750000)
        salt_cap = r["salt"]["cap"]
        itemized = mort["interest"] + min(prop, salt_cap)
        assumed.append((f"the {money(loan)} loan is a mortgage secured by the home" if given else
                        f"a {m_years}-year mortgage at {m_rate * 100:g}%") + f", and property tax of {prop_rate * 100:g}% of the price a year")
        assumed += list(scenario.get("assumed") or [])
        lines += [f"**Step {step}. After you buy: mortgage interest and property tax**",
                  (f"- Your loan: **{money(loan)}** at {m_rate * 100:g}% over {m_years} years ({money(price)} − {money(loan)} = "
                   f"{money(target)} paid up front)" if given else
                   f"- Mortgage: {money(price)} − {money(target)} down = **{money(loan)}**; at {m_rate * 100:g}% over {m_years} years")
                  + f": {money(mort['payment'])} a month, and about **{money(mort['interest'])}** of interest in the first year.",
                  f"- Property tax: {money(price)} × {prop_rate * 100:g}% = **{money(prop)}** a year.",
                  f"- Both are itemized deductions: interest on up to {money(cap_debt)} of mortgage, and property tax together with "
                  f"state income tax up to the {money(salt_cap)} SALT cap. Together: **{money(itemized)}**.",
                  f"- They only lower your tax if your itemized deductions beat the {year} standard deduction: "
                  f"{money(sd['single'])} single, {money(sd['married_joint'])} married filing jointly."]
        if inp is not None:
            e = T.marginal_effect(inp, {"mortgage_interest": mort["interest"], "property_tax": prop}, year)
            saved = -e["diff"]["total_federal"]
            lines.append(f"- With your figures you'd {'itemize' if e['after']['itemizes'] else 'still take the standard deduction'}: "
                         f"the home lowers your federal tax by **{money(saved)}** in the first year.")
        else:
            for label, std in (("Single", sd["single"]), ("Married filing jointly", sd["married_joint"])):
                over = itemized - std
                lines.append(f"- {label}: {money(itemized)} vs {money(std)} → " + (
                    f"itemizing gives {money(over)} more deduction, worth about {money(over * top)} at {pct(top)}."
                    if over > 0 else f"the standard deduction is larger by {money(-over)}, so the home itself saves no federal tax "
                    "(unless state income tax, charity and other deductions add up to more)."))
        prev = scenario.get("previous") or {}
        if given and prev.get("loan_amount") and prev.get("loan_rate"):
            before = T.mortgage_first_year(float(prev["loan_amount"]), float(prev["loan_rate"]), int(prev.get("loan_years") or m_years))
            lines.append(f"- Compared with the example's {money(float(prev['loan_amount']))} mortgage at {float(prev['loan_rate']) * 100:g}% "
                         f"({money(before['interest'])} of first-year interest), there is {money(abs(before['interest'] - mort['interest']))} "
                         f"{'less' if mort['interest'] < before['interest'] else 'more'} interest to deduct, so itemizing is "
                         f"{'less' if mort['interest'] < before['interest'] else 'more'} likely to beat the standard deduction.")
        if given:
            lines.append("- That interest counts only if the loan is a mortgage secured by the home. A personal (unsecured) loan's "
                         f"interest isn't deductible at all, even if it pays for the house: then the deduction is the {money(min(prop, salt_cap))} "
                         "of property tax alone.")
        lines.append("")
        step += 1
        excl = L.get("home_sale_exclusion") or {"single": 250000, "married_joint": 500000}
        lines += [f"**Step {step}. When you sell it later**",
                  f"Gain on your main home is tax-free up to **{money(excl['single'])}** ({money(excl['married_joint'])} married "
                  "filing jointly) if you owned it and lived in it for 2 of the 5 years before the sale (Section 121). Gain above "
                  "that is a long-term capital gain. The down payment and improvements are part of your cost basis.", ""]
        step += 1
    elif kind == "education":
        lines += [f"**Step {step}. A tax-free account for it**",
                  "Saving in a 529 plan instead: no federal tax on the growth, and withdrawals for tuition, fees, books and room "
                  "and board are tax-free (many states also deduct contributions). Earnings taken for anything else are taxed "
                  "and get a 10% penalty.", ""]
        step += 1
    elif kind == "retirement":
        lines += [f"**Step {step}. A retirement account instead**",
                  "In a 401(k) or traditional IRA the growth isn't taxed each year and contributions lower your taxable income now; "
                  "withdrawals are taxed later. In a Roth, growth and qualified withdrawals are tax-free. Ask me to compare "
                  "Roth and traditional for your contribution.", ""]
        step += 1
    lines += ["**Assumed:** " + "; ".join(assumed) + ".", "",
              f"_Federal only ({year} rules), no state tax; an illustration computed in Python, not a forecast._"]
    return "\n".join(lines), (f"savings_goal_tax({kind}, {target:,.0f}, {years}y) → interest {total_interest:,.0f}"
                              + (", with your estimate" if inp is not None else ", brackets shown"))
