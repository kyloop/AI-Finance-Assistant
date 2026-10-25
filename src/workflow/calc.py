"""Calculator agent: the LLM designs the calculation as a plan (inputs, formulas, equations, period-by-period rules and
checks; see mds/calc-plan-design.md), src/core/calc_plan.py validates and executes it, and this module renders the result
with its working. Without an LLM, a keyword fallback picks one of the CATALOG calculators, which the illustrate node also
uses for worked examples."""
from __future__ import annotations

import json
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


# ---------------------------------------------------------------- the LLM designs the calculation (calc_plan runs it)
PLAN_SYSTEM = (
    "You design the calculation for a finance calculator. You never compute a result: you write a plan as JSON, and "
    "Python checks it and computes every number.\n"
    "INPUTS: every number the calculation needs, each {\"value\", \"from\", \"means\", \"unit\"}. \"from\" is \"user\" "
    "for a number stated in the message or the conversation, \"sample\" for a typical value you chose because it wasn't "
    "given (a yearly return of 0.06, inflation of 0.03, 20 years). \"unit\" is \"money\", \"rate\" (a DECIMAL: 0.08 for "
    "8%, also for shares such as 50% of an amount; only for a percentage), \"years\", \"months\" or \"number\" (a "
    "count, or a ratio or multiplier that isn't a percentage: a beta of 1.2, a P/E of 15). Words are numbers too: "
    "\"compounded monthly\" is 12, \"annually\" 1, \"no more money\" 0.\n"
    "STEPS, in order, each with \"name\", \"label\" (what it is, in a few words), \"unit\" and exactly one of:\n"
    "- \"expr\": a formula over inputs and earlier steps, e.g. \"P*(1+r/n)^(n*t)\". When the unknown sits inside an "
    "equation (a deposit needed, a rate needed, a number of years), rearrange the equation yourself into a formula for "
    "the unknown and give the original equation as \"satisfies\" (with the step's name for the unknown): Python checks "
    "that the result solves it.\n"
    "- \"solve\" with \"for\": an equation and its unknown, only when the unknown can't be isolated (an internal rate of "
    "return over several cash flows, a rate inside a loan or annuity formula); Python solves it numerically.\n"
    "- \"simulate\": period-by-period rules, for anything that changes over time with conditions (withdrawals rising with "
    "inflation, a debt paid down, contributions that grow): {\"start\": {state: formula}, \"each\": {state: formula of "
    "the previous period's state, all updated together; a name in \"each\" that isn't in \"start\" is a helper for "
    "the period (\"interest\": \"balance*r/12\", \"payment\": \"max(m*balance, F)\"), computed first in the order "
    "given}, then either \"until\": a condition such as \"balance < "
    "withdrawal\" (checked before each period, with \"max\" periods, at most 1200) or \"periods\": a formula for how "
    "many periods, and \"period\": \"year\" or \"month\"}. \"result\" is \"periods\" (how many full periods ran before "
    "\"until\" became true) or a state variable (its final value). The stop condition must be reachable: an amount "
    "that only shrinks by a percentage of itself never reaches 0, so stop below a small amount (balance < 1) or apply "
    "a floor (a sample minimum payment) and say so in \"assumptions\". Keep running totals (interest paid, amount "
    "contributed) as extra state variables, and add a step per total asked for (\"result\": that variable). A debt "
    "stops when it is paid off: stop with \"until\" when the balance reaches 0 and pay at most what is owed "
    "(\"payment\": \"min(P, balance + interest)\"), so a balance never goes below 0.\n"
    "- \"vary\": a table of earlier steps over one input: {\"input\": name, \"values\": [...]} or {\"input\": name, "
    "\"from\": 1, \"to\": 10, \"step\": 1}, with \"of\": [step names]. Use it for a year-by-year table, and whenever the "
    "answer depends on a sample: show the result for several values of that sample.\n"
    "A yes/no question (is it enough? which costs less?) is a step for the difference (cash saved - price), labelled "
    "with what its sign means; formulas never compare with < or >.\n"
    "Formulas use names, + - * / ^ ( ) and log exp sqrt abs floor ceil min max. The only numbers allowed in a formula "
    "are 0, 1, 2, 12, 52, 100 and 365, plus whole numbers up to 12 as exponents (year 3 of a cash flow); every other "
    "number, including an assumption such as a minimum payment, must be an input (\"sample\" if you chose it). Money "
    "paid out may be a negative input (-10000 for an amount invested).\n"
    "CHECKS: when the plan has a power (^), exp, log, a solve or a simulate, add 1 to 3 checks {\"when\": {input: value}, "
    "\"of\": step, \"expect\": formula} with cases whose answer you know for certain (a rate of 0, a time of 0 or 1, no "
    "withdrawals). Python reruns the plan with those inputs and rejects it "
    "if the result differs. A check with a rate "
    "of 0 is evaluated as the limit (rate → 0) when a formula divides by the rate, so \"with r = 0 the payment is "
    "P/N\" works for a loan formula.\n"
    "RULES: Use every number in the message: each must be a \"user\" input that a step uses, or be listed in \"ignored\" "
    "({\"number\", \"why\"}, e.g. a percentage that only restates two other numbers). Model every condition the message "
    "states (inflation adjustments, contributions, timing, compounding). Answer every part of the question, with several "
    "steps if needed. Put what you assumed in \"assumptions\" (when payments happen, how often interest compounds). "
    "Never write a number that isn't in the message, the conversation or a sample. \"label\" names the whole calculation.\n"
    "EXAMPLES\n"
    "\"$10,000 split 50% / 30% / 20% into an index fund, a stock and crypto, how much in each?\" -> "
    '{"label": "how the $10,000 is split", "inputs": {"T": {"value": 10000, "from": "user", "means": "amount '
    'invested", "unit": "money"}, "a": {"value": 0.5, "from": "user", "means": "share in the index fund", "unit": '
    '"rate"}, "b": {"value": 0.3, "from": "user", "means": "share in the stock", "unit": "rate"}, "c": {"value": 0.2, '
    '"from": "user", "means": "share in crypto", "unit": "rate"}}, "steps": [{"name": "index", "label": "index fund", '
    '"expr": "T*a", "unit": "money"}, {"name": "stock", "label": "stock", "expr": "T*b", "unit": "money"}, {"name": '
    '"crypto", "label": "crypto", "expr": "T*c", "unit": "money"}]}\n'
    "\"$10,000 at 8% compounded annually, how much after 10 years?\" -> "
    '{"label": "balance after 10 years", "inputs": {"P": {"value": 10000, "from": "user", "means": "starting amount", '
    '"unit": "money"}, "r": {"value": 0.08, "from": "user", "means": "yearly interest rate", "unit": "rate"}, "n": '
    '{"value": 1, "from": "user", "means": "compounding periods a year", "unit": "number"}, "t": {"value": 10, "from": '
    '"user", "means": "years", "unit": "years"}}, "steps": [{"name": "A", "label": "balance", "expr": "P*(1+r/n)^(n*t)", '
    '"unit": "money"}, {"name": "by_year", "label": "year by year", "vary": {"input": "t", "from": 1, "to": 10}, "of": '
    '["A"]}], "checks": [{"when": {"r": 0}, "of": "A", "expect": "P"}, {"when": {"t": 1}, "of": "A", "expect": '
    '"P*(1+r/n)^n"}], "assumptions": ["the rate is the same every year"]}\n'
    "\"I retire with $1,000,000 and withdraw $45,000 (4.5%) the first year, raised 3% a year for inflation\" -> "
    '{"label": "how long the savings last", "inputs": {"B": {"value": 1000000, "from": "user", "means": "savings at '
    'retirement", "unit": "money"}, "W": {"value": 45000, "from": "user", "means": "first-year withdrawal", "unit": '
    '"money"}, "g": {"value": 0.03, "from": "user", "means": "yearly increase for inflation", "unit": "rate"}, "r": '
    '{"value": 0.05, "from": "sample", "means": "yearly return on the savings", "unit": "rate"}}, "steps": [{"name": '
    '"years", "label": "years of full withdrawals", "simulate": {"start": {"balance": "B", "withdrawal": "W"}, "each": '
    '{"balance": "(balance - withdrawal)*(1 + r)", "withdrawal": "withdrawal*(1 + g)"}, "until": "balance < '
    'withdrawal", "max": 100, "period": "year"}, "result": "periods", "unit": "years"}, {"name": "by_return", "label": '
    '"depending on the return", "vary": {"input": "r", "values": [0.03, 0.04, 0.05, 0.06, 0.07, 0.08]}, "of": '
    '["years"]}], "checks": [{"when": {"r": 0, "g": 0}, "of": "years", "expect": "floor(B/W)"}], "assumptions": '
    '["withdrawals are taken at the start of each year"], "ignored": [{"number": 4.5, "why": "the same as 45,000 of '
    '1,000,000"}]}\n'
    "\"I invest $10,000 and want $15,000 in 5 years, what yearly return do I need?\" -> "
    '{"label": "yearly return needed", "inputs": {"P": {"value": 10000, "from": "user", "means": "amount invested", '
    '"unit": "money"}, "F": {"value": 15000, "from": "user", "means": "target", "unit": "money"}, "t": {"value": 5, '
    '"from": "user", "means": "years", "unit": "years"}}, "steps": [{"name": "x", "label": "yearly return needed", '
    '"expr": "(F/P)^(1/t) - 1", "satisfies": "P*(1+x)^t = F", "unit": "rate"}], "checks": [{"when": {"F": 10000}, '
    '"of": "x", "expect": "0"}]}\n'
    "\"What's the IRR if I invest $10,000 and get back $3,000, $4,000 and $5,000 over three years?\" -> "
    '{"label": "internal rate of return", "inputs": {"a": {"value": -10000, "from": "user", "means": "amount invested", '
    '"unit": "money"}, "b": {"value": 3000, "from": "user", "means": "year 1", "unit": "money"}, "c": {"value": 4000, '
    '"from": "user", "means": "year 2", "unit": "money"}, "d": {"value": 5000, "from": "user", "means": "year 3", "unit": '
    '"money"}}, "steps": [{"name": "irr", "label": "internal rate of return", "solve": "a + b/(1+x) + c/(1+x)^2 + '
    'd/(1+x)^3 = 0", "for": "x", "unit": "rate"}], "checks": [{"when": {"b": 0, "c": 0, "d": 10000}, "of": "irr", '
    '"expect": "0"}], "ignored": [{"number": 3, "why": "the three years are the three cash flows"}]}\n'
    "Reply with ONLY the JSON plan.")


def repair_prompt(prompt: str, plan: dict | None, error: str, repeated: bool = False) -> str:
    """The second try: why the plan was rejected first, then the plan and the question again."""
    again = ("You sent the SAME plan again and it was rejected for the same reason. Change it.\n" if repeated else "")
    return (f"{again}YOUR PLAN WAS REJECTED: {error}\n\nFix what the error points at. If a check failed, decide whether "
            "the formula or the check is wrong: a check must be a case whose answer is certain and finite, so replace a "
            "check whose expected value is wrong, undefined or infinite (a loan over 0 years, doubling at 0%) with "
            f"another one, or drop it if the plan has other checks.\n\nRejected plan:\n{json.dumps(plan)[:4000]}\n\n{prompt}\n\n"
            "Reply with ONLY the corrected JSON plan.")


JUDGE_SYSTEM = (
    "You review a calculation plan whose self-check failed. The plan models the user's question; the check is a test "
    "case the same planner wrote, and either one may be wrong. You get the question, the plan, the failed check (the "
    "inputs it sets, its expected formula and value) and what the plan computed with those inputs, with the first and "
    "last periods when it is a simulation. Work out by hand what the right answer is for the check's inputs, following "
    "the question as asked (not a different, simpler situation), then decide: \"check\" if the plan is right for the "
    "question and the check's expectation is wrong, \"plan\" if the plan's model or formula is wrong, \"unsure\" if you "
    "can't tell.\n"
    'Reply with ONLY JSON: {"reasoning": "<two or three sentences>", "wrong": "check"}.')


def judge_prompt(question: str, plan: dict | None, failed) -> str:
    """The judge's material: the question, the plan, the failed check and what the plan computed for it."""
    c = failed.check
    rows = "\n".join(f"  period {p}: " + ", ".join(f"{k} = {v:.6g}" for k, v in st.items()) for p, st in failed.rows)
    return (f"Question: {question}\n\nPlan:\n{json.dumps(plan)[:4000]}\n\nFailed check: with "
            + ", ".join(f"{k} = {v:g}" for k, v in c["when"].items())
            + f", the check expects {c['of']} = {c['expect']}"
            + (f" = {failed.expected:.6g}" if failed.expected is not None else " (no value)")
            + f"; the plan computed {c['of']} = " + (f"{failed.actual:.6g}" if failed.actual is not None else
                                                      "no value (never stopped or no solution)")
            + (f"\nThe plan's simulation with the check's inputs:\n{rows}" if rows else ""))


def needs_input_text(label: str, inputs: list[str]) -> str:
    return "\n".join([f"I can work out {label}. Tell me:", ""] + [f"- {m}" for m in inputs])


def _show(x: float | None, unit: str) -> str:
    """A value for the answer: money, a rate as a percentage, years, or a plain number."""
    if x is None:
        return "none"
    if unit == "money":
        return money(x)
    if unit == "rate":
        return f"{x * 100:,.2f}%".replace(".00%", "%")
    if unit == "percent":
        return f"{x:,.2f}%".replace(".00%", "%")
    if unit in ("years", "months"):
        n = num(round(x, 2))
        return f"{n} {unit[:-1] if n == '1' else unit}"
    return num(round(x, 6))


def _input_text(i: dict) -> str:
    return f"{i['value'] * 100:g}%" if i["unit"] == "rate" else _show(i["value"], i["unit"])


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def _working(expr: str, values: dict) -> str:
    """A formula with every name replaced by its value."""
    return _WORD.sub(lambda m: f"{values[m[0]]:.10g}" if values.get(m[0]) is not None else m[0], expr)


def _sampled(rows: list, most: int = 12) -> list:
    """At most `most` rows of a long table: the first two, then evenly spaced round periods, and the last."""
    if len(rows) <= most:
        return rows
    last = rows[-1][0]
    step = next(k for k in (5, 10, 12, 20, 24, 25, 50, 60, 100, 120, 200, 240, 500, 600) if last / k <= most - 3)
    keep = {0, 1} | {j for j, (p, _) in enumerate(rows) if p % step == 0} | {len(rows) - 1}
    return [r for j, r in enumerate(rows) if j in keep]


def _money_vars(s: dict, inputs: dict) -> set[str]:
    """State variables and helpers that hold money: those started from a money input or a money step result, then any
    whose formula uses one of those."""
    money_names = {k for k, i in inputs.items() if i["unit"] == "money"}
    found = {k for k, f in s["start"].items() if set(_WORD.findall(f)) & money_names}
    if s["result"] in s["start"] and s["unit"] == "money":
        found.add(s["result"])
    formulas = {**s["helpers"], **s["each"]}
    for _ in range(len(formulas)):
        found |= {k for k, f in formulas.items() if set(_WORD.findall(f)) & (found | money_names)}
    return found


def _step_value(s: dict, x: float | None, details: dict) -> str:
    if x is None and s["kind"] == "simulate":
        return f"more than {details[s['name']]['limit']} {s['period']}s"
    if x is None and s["kind"] == "solve":
        return "no solution"
    return _show(x, s["unit"])


def _same_text(a: str, b: str) -> bool:
    return re.sub(r"\s+", "", a) == re.sub(r"\s+", "", b)


QUOTE_CHARS = 300


def _same_simulation(a: dict, b: dict) -> bool:
    return a is not b and a["kind"] == b["kind"] == "simulate" and all(
        a[k] == b[k] for k in ("start", "helpers", "each", "until", "periods", "max", "period"))


def plan_text(r: dict) -> str:
    """An executed plan as the answer: inputs (samples marked), each step's formula, working and result, tables, the
    checks that passed, assumptions and ignored numbers. Everything shown was computed in Python."""
    inputs, values, details, steps = r["inputs"], r["values"], r["details"], r["steps"]
    by_name = {s["name"]: s for s in steps}
    lines = [f"**Worked example: {r['label']}**" if r.get("example") else f"**Calculation: {r['label']}**", "", "Inputs:"]
    lines += [f"- `{k}` = {_input_text(i)}: {i['means']}" + (" **(sample)**" if i["from"] == "sample" else "")
              for k, i in inputs.items()]
    for n, s in enumerate(steps, 1):
        name, d = s["name"], details.get(s["name"], {})
        lines += ["", f"**Step {n}: {s['label']}**" if len(steps) > 1 else f"**{s['label'][:1].upper()}{s['label'][1:]}**"]
        if s["kind"] == "expr":
            lhs, _, rhs = (s.get("satisfies") or "").partition("=")
            rearranged = s.get("satisfies") and not (lhs.strip() == name and _same_text(rhs, s["expr"]))
            if rearranged:
                lines.append(f"- From the equation `{s['satisfies']}`, rearranged for `{name}`")
            lines += [f"- Formula: `{name} = {s['expr']}`", f"- Working: `{_working(s['expr'], values)}`"]
            if rearranged:
                lines.append(f"- Checked: the result solves `{s['satisfies']}` ✓")
        elif s["kind"] == "solve":
            lines += [f"- Equation: `{s['solve']}`", f"- Solved numerically for `{s['unknown']}` (no formula isolates it)"]
        elif s["kind"] == "simulate" and (same := next((t for t in steps[:n - 1] if _same_simulation(t, s)), None)):
            lines.append(f"- The same simulation as step {steps.index(same) + 1}, reading "
                         + ("how many " + s["period"] + "s it ran" if s["result"] == "periods" else f"`{s['result']}` at the end"))
        elif s["kind"] == "simulate":
            lines.append("- Start: " + "; ".join(f"`{k} = {f}`" for k, f in s["start"].items()))
            if s["helpers"]:
                lines.append(f"- Each {s['period']}, first: " + "; ".join(f"`{k} = {f}`" for k, f in s["helpers"].items()))
            lines.append(f"- Each {s['period']}: " + "; ".join(f"`{k} → {f}`" for k, f in s["each"].items()))
            lines.append(f"- Stops when: `{' '.join(s['until'])}` (at most {s['max']} {s['period']}s)" if s["until"]
                         else f"- For: `{s['periods']}` {s['period']}s")
        if s["kind"] == "vary":
            cols = [by_name[o] for o in s["of"]]
            inp = inputs[s["input"]]
            lines += [f"| {inp['means']} | " + " | ".join(c["label"] for c in cols) + " |",
                      "|---" * (len(cols) + 1) + "|"]
            for v, row in d.get("rows", []):
                lines.append(f"| {_input_text({**inp, 'value': v})} | "
                             + " | ".join(_step_value(c, row[c["name"]], details) for c in cols) + " |")
            continue
        lines += ["", f"**Result: {s['label']} = {_step_value(s, values[name], details)}**"]
        if s["kind"] == "simulate" and d.get("rows") and not any(_same_simulation(t, s) for t in steps[:n - 1]):
            money_vars = _money_vars(s, inputs) | {t["result"] for t in steps if _same_simulation(t, s) and t["unit"] == "money"}
            lines += ["", f"| {s['period'].title()} | " + " | ".join(s["start"]) + " |", "|---" * (len(s["start"]) + 1) + "|"]
            lines += [f"| {p} | " + " | ".join(money(st[k]) if k in money_vars else num(round(st[k], 4)) for k in s["start"])
                      + " |" for p, st in _sampled(d["rows"])]
    if r["checks"]:
        lines += ["", "Checked: " + "; ".join(
            f"with {', '.join(f'`{k} = {v:g}`' for k, v in c['when'].items())}, `{c['of']}` equals `{c['expect']}` ✓"
            for c in r["checks"])]
    if r.get("quotes"):
        lines += ["", "**Where the equations come from**"]
        for qt in r["quotes"]:
            agreed = ("found in the knowledge base and on the web, and they agree ✓" if qt["status"] == "matched"
                      else "found in one source only, not cross-checked")
            lines += ["", f"{qt['label'][:1].upper()}{qt['label'][1:]}: `{qt['equation']}` ({agreed})"]
            for src in qt["sources"]:
                link = f"[{src['title']}]({src['url']})" if src.get("url") else src["title"]
                quote = src["quote"] if len(src["quote"]) <= QUOTE_CHARS else src["quote"][:QUOTE_CHARS].rsplit(" ", 1)[0] + " …"
                lines.append(f"> \"{quote}\"  \n> — {link}, {src['where']}")
    if r.get("model_note"):
        lines += ["", f"_{r['model_note']}_"]
    for a in r.get("set_aside", []):
        lines += ["", f"Set aside: a self-check with {a['when']} expected `{a['expect']}` = {a['expected']}, but the plan "
                      f"gives {a['actual']}. A separate review judged the check wrong, not the plan: {a['why']}"]
    if r["assumptions"]:
        lines += ["", "Assumes: " + "; ".join(a.rstrip(". ") for a in r["assumptions"]) + "."]
    if r["ignored"]:
        lines += ["", "Not used: " + "; ".join(f"{g['number']:g} ({g['why']})" for g in r["ignored"]) + "."]
    if any(i["from"] == "sample" for i in inputs.values()):
        lines += ["", "_Values marked (sample) are illustrative, not yours: tell me your own numbers to redo the calculation._"]
    lines += ["", "_Finnie computed every number above in Python from these formulas; real returns vary and are never "
                  "guaranteed._"]
    return "\n".join(lines)

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

ASK = ("I couldn't tell which calculation you mean. Tell me what you'd like to work out and the numbers you have, "
       "such as one of the questions below.")
CHOICES = ["How much will $10,000 grow to at 6% a year over 10 years?",
           "What is the monthly payment on a $300,000 mortgage at 6.5% for 30 years?",
           "How long does it take to double my money at 7%?"]
NOTE = "_This assumes a steady rate every year. Real returns vary and are never guaranteed._"


def num(x: float) -> str:
    """A plain number with thousands separators, never in scientific notation (1,000,000, 0.08, 41.04)."""
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.6f}".rstrip("0").rstrip(".")


def money(x: float) -> str:
    return ("−" if x < 0 else "") + f"${abs(x):,.2f}".replace(".00", "")


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
