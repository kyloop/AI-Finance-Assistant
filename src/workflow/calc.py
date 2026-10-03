"""Calculator agent: the LLM (or a keyword fallback) picks a calculation and extracts its inputs; Python does the maths,
so figures are exact. Each result is shown with its inputs, formula and assumptions."""
from __future__ import annotations

import re

from src.core import calculators as C

# name -> (function, one-line description for the LLM, {arg: description})
CATALOG = {
    "future_value": (C.future_value, "what a lump sum and/or regular monthly deposits grow to",
                     {"annual_rate": "yearly return or interest, percent", "years": "number of years",
                      "principal": "starting amount (0 if none)", "monthly_contribution": "amount added each month (0 if none)",
                      "compounds_per_year": "optional: 1 yearly, 12 monthly, 365 daily"}),
    "present_value": (C.present_value, "what an amount received in the future is worth today",
                      {"future_amount": "amount received later", "annual_rate": "discount rate, percent", "years": "years until received"}),
    "loan_payment": (C.loan_payment, "monthly payment, total paid and total interest on a loan or mortgage",
                     {"principal": "amount borrowed", "annual_rate": "interest rate, percent", "years": "loan term in years"}),
    "doubling_time": (C.doubling_time, "how many years money takes to double (Rule of 72 and exact)",
                      {"annual_rate": "yearly return, percent"}),
    "real_return": (C.real_return, "return after inflation", {"nominal_rate": "return before inflation, percent",
                                                               "inflation_rate": "inflation, percent"}),
    "apy_from_apr": (C.apy_from_apr, "annual percentage yield (APY) from a nominal rate (APR)",
                     {"apr": "nominal annual rate, percent", "compounds_per_year": "e.g. 12 for monthly, 365 for daily"}),
    "percent_change": (C.percent_change, "a price or amount after it rises or falls by a percentage (\"if SBUX rose 2%\")",
                       {"amount": "starting price or amount", "percent": "change in percent, negative for a fall"}),
    "bond_current_yield": (C.bond_current_yield, "a bond's current yield", {"annual_coupon": "yearly coupon payment in dollars",
                                                                           "price": "current bond price in dollars"}),
    "purchasing_power": (C.purchasing_power, "what an amount of money is worth after years of inflation",
                         {"amount": "amount of money today", "inflation_rate": "yearly inflation, percent", "years": "number of years"}),
}

CALC_SYSTEM = (
    "You extract a calculation request for a finance calculator. Pick ONE function and fill its arguments from the user's "
    "message and the recent conversation. Rates are percentages as plain numbers (6 for 6%). Use only numbers the user gave "
    "or that the conversation already states (a price quoted in the last answer counts: \"if Starbucks rose 2%\" after an answer "
    "giving Starbucks at $94.71 uses 94.71); do not invent any. If a required number is missing, set \"function\" to null and say what's missing.\n"
    "Functions:\n" + "\n".join(f"- {name}: {desc}. Args: " + "; ".join(f"{a} ({d})" for a, d in args.items())
                               for name, (_, desc, args) in CATALOG.items()) +
    '\nReply with ONLY JSON: {"function": "future_value", "args": {"annual_rate": 6, "years": 10, "principal": 10000}} '
    'or {"function": null, "missing": "the interest rate"}.')

EXAMPLE_SYSTEM = (
    "A personal-finance learner asked a question and got a conceptual answer. Add a worked example: pick the calculation "
    "that best makes the concept concrete and choose simple, typical sample numbers (or the user's own numbers if they "
    "gave any). Most money concepts have one, so include it whenever the topic involves amounts, rates, prices or time: "
    "interest, compounding, saving or investing growth → future_value; APY, APR, effective rate → apy_from_apr; "
    "inflation, purchasing power, cost of living → purchasing_power; real interest or real return → real_return; "
    "loans, mortgages, credit → loan_payment; present value, NPV, discounting, time value of money → present_value; "
    "Rule of 72, doubling → doubling_time; bond yield, coupon, bond price → bond_current_yield. Reply {\"function\": null} "
    "only when the topic isn't numeric at all (e.g. what an institution is, a type of bond's purpose, history). "
    "Rates are percentages as plain numbers (6 for 6%).\n"
    "Functions:\n" + "\n".join(f"- {name}: {desc}. Args: " + "; ".join(f"{a} ({d})" for a, d in args.items())
                               for name, (_, desc, args) in CATALOG.items()) +
    '\nReply with ONLY JSON: {"function": "future_value", "args": {"annual_rate": 6, "years": 10, "principal": 10000}} '
    'or {"function": null}.')
EXAMPLE_HEADING = "**Example with sample numbers**"

ASK = ("I can work that out, but I need the numbers. Tell me the amount, the yearly rate and the number of years, "
       "for example “How much will $10,000 grow to at 6% a year over 10 years?”")
CHOICES = ["How much will $10,000 grow to at 6% a year over 10 years?",
           "What is the monthly payment on a $300,000 mortgage at 6.5% for 30 years?",
           "How long does it take to double my money at 7%?"]
NOTE = "_This assumes a steady rate every year. Real returns vary and are never guaranteed._"


def money(x: float) -> str:
    return f"${x:,.2f}".replace(".00", "")


def pct(x: float) -> str:
    return f"{x:g}%"


def compounding(n: int) -> str:
    return {1: "yearly", 2: "twice a year", 4: "quarterly", 12: "monthly", 365: "daily"}.get(n, f"{n} times a year")


def keyword_request(text: str) -> tuple[str | None, dict]:
    """Fallback without an LLM: recognise the two most common requests from the numbers in the message."""
    rate = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    years = re.search(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\b", text, re.I)
    monthly = re.search(r"\$\s?([\d,]+(?:\.\d+)?)\s*(?:a|per|/|each)\s*month", text, re.I)
    amounts = [float(a.replace(",", "")) for a in                # whole numbers only, not followed by "a month"
               re.findall(r"\$\s?(\d[\d,]*(?:\.\d+)?)(?![\d,.]*\d)(?!\s*(?:a|per|/|each)\s*month)", text, re.I)]
    if rate and re.search(r"\bdoubl", text, re.I):
        return "doubling_time", {"annual_rate": float(rate.group(1))}
    if rate and years and (amounts or monthly):
        return "future_value", {"annual_rate": float(rate.group(1)), "years": float(years.group(1)),
                                "principal": amounts[0] if amounts else 0.0,
                                "monthly_contribution": float(monthly.group(1).replace(",", "")) if monthly else 0.0}
    return None, {}


def run(name: str, args: dict) -> str:
    """Run a catalog calculation and format the working. Raises ValueError/TypeError on bad inputs."""
    fn, _, spec = CATALOG[name]
    clean = {k: float(v) for k, v in args.items() if k in spec and v is not None and v != ""}
    if "compounds_per_year" in clean:
        clean["compounds_per_year"] = int(clean["compounds_per_year"])
    r = fn(**clean)
    a = clean
    if name == "future_value":
        lines = ["**Calculation: how an investment grows**", ""]
        if a.get("principal"):
            lines.append(f"- Starting amount: {money(a['principal'])}")
        if a.get("monthly_contribution"):
            lines.append(f"- Added each month: {money(a['monthly_contribution'])}")
        lines += [f"- Return: {pct(a['annual_rate'])} a year, compounded {compounding(r['compounds_per_year'])}",
                  f"- Time: {a['years']:g} years", "",
                  f"**Result: about {money(r['future_value'])}**: you put in {money(r['contributed'])} and growth adds {money(r['growth'])}.", ""]
        if a.get("principal") and not a.get("monthly_contribution"):
            lines.append(f"Formula: value = amount × (1 + rate/n)^(n × years) = {money(a['principal'])} × (1 + {a['annual_rate'] / 100:g}/{r['compounds_per_year']})"
                         f"^({r['compounds_per_year']} × {a['years']:g})")
        else:
            lines.append("Formula: each deposit grows with compound interest until the end, and the results are added up "
                         "(starting amount × growth factor + monthly deposits as an annuity).")
        lines += ["", "| Year | Value |", "|---|---|"] + [f"| {y:g} | {money(v)} |" for y, v in r["table"]] + ["", NOTE]
    elif name == "present_value":
        lines = ["**Calculation: what a future amount is worth today**", "",
                 f"- Amount received later: {money(a['future_amount'])}", f"- Discount rate: {pct(a['annual_rate'])} a year",
                 f"- Time: {a['years']:g} years", "", f"**Result: about {money(r['present_value'])} today** "
                 f"({money(r['discount'])} less than the future amount).", "",
                 f"Formula: present value = future amount ÷ (1 + rate)^years = {money(a['future_amount'])} ÷ (1 + {a['annual_rate'] / 100:g})^{a['years']:g}"]
    elif name == "loan_payment":
        lines = ["**Calculation: loan payment**", "", f"- Amount borrowed: {money(a['principal'])}",
                 f"- Interest rate: {pct(a['annual_rate'])} a year (charged monthly)", f"- Term: {a['years']:g} years ({r['months']} payments)", "",
                 f"**Result: about {money(r['monthly_payment'])} a month.** Over the whole loan you'd pay {money(r['total_paid'])}, "
                 f"of which {money(r['total_interest'])} is interest.", "",
                 "Formula: payment = amount × r ÷ (1 − (1 + r)^−months), where r is the yearly rate ÷ 12."]
    elif name == "doubling_time":
        lines = ["**Calculation: how long money takes to double**", "", f"- Return: {pct(a['annual_rate'])} a year", "",
                 f"**Result: about {r['exact']:g} years** (exact). The Rule of 72 estimate is 72 ÷ {a['annual_rate']:g} = {r['rule_of_72']:g} years.", "", NOTE]
    elif name == "real_return":
        lines = ["**Calculation: return after inflation**", "", f"- Return before inflation: {pct(a['nominal_rate'])}",
                 f"- Inflation: {pct(a['inflation_rate'])}", "",
                 f"**Result: a real return of about {r['real_rate']:g}% a year.** The quick estimate (return minus inflation) is {r['approximate']:g}%.", "",
                 "Formula: real return = (1 + return) ÷ (1 + inflation) − 1"]
    elif name == "apy_from_apr":
        n = int(a.get("compounds_per_year", 12))
        lines = ["**Calculation: APY from APR**", "", f"- Nominal rate (APR): {pct(a['apr'])}", f"- Compounded: {compounding(n)}", "",
                 f"**Result: an APY of about {r['apy']:g}%.**", "", f"Formula: APY = (1 + APR/n)^n − 1, with n = {n}"]
    elif name == "purchasing_power":
        lines = ["**Calculation: what inflation does to money**", "", f"- Amount today: {money(a['amount'])}",
                 f"- Inflation: {pct(a['inflation_rate'])} a year", f"- Time: {a['years']:g} years", "",
                 f"**Result: in {a['years']:g} years, {money(a['amount'])} would buy about what {money(r['real_value'])} buys today** "
                 f"(about {r['lost_pct']:g}% less). Put the other way, goods costing {money(a['amount'])} now would cost "
                 f"about {money(r['future_cost'])}.", "",
                 f"Formula: value in today's money = amount ÷ (1 + inflation)^years = {money(a['amount'])} ÷ (1 + {a['inflation_rate'] / 100:g})^{a['years']:g}",
                 "", "_This assumes inflation stays at the same rate every year; in reality it changes._"]
    elif name == "percent_change":
        up = a["percent"] >= 0
        lines = ["**Calculation: a percentage change**", "", f"- Starting amount: {money(a['amount'])}",
                 f"- Change: {'+' if up else '−'}{pct(abs(a['percent']))}", "",
                 f"**Result: about {money(r['new_amount'])}**, {'up' if up else 'down'} {money(abs(r['change']))}.", "",
                 f"Formula: new amount = amount × (1 {'+' if up else '−'} {abs(a['percent']) / 100:g}) = {money(a['amount'])} × {1 + a['percent'] / 100:g}"]
    else:  # bond_current_yield
        lines = ["**Calculation: bond current yield**", "", f"- Yearly coupon: {money(a['annual_coupon'])}", f"- Current price: {money(a['price'])}", "",
                 f"**Result: a current yield of about {r['current_yield']:g}%.**", "", "Formula: current yield = yearly coupon ÷ current price"]
    return "\n".join(lines)
