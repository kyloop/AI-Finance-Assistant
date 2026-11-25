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
    "wages": "pay from a job (salary, wages, an employer's bonus, a W-2 part-time job)",
    "self_employment": "freelance, contractor, 1099 or own-business profit (only when the message says so)",
    "job_unspecified": "pay from a SECOND, side or part-time job without saying whether it is W-2 or freelance (a person's "
                       "only or main job is wages)",
    "interest_dividends": "interest, or dividends not said to be qualified",
    "qualified_dividends": "dividends the message says are qualified",
    "other_income": "other taxable income that isn't pay from a job or a rental property (prizes, jury pay, ...)",
    "rental_income": "rent received from a rental property the person owns (gross rents)",
    "rental_expense": "a cost of a rental property: management fees, repairs and maintenance, insurance, utilities, the "
                      "rental's property tax, the rental's mortgage interest, depreciation, advertising",
    "short_term_gains": "profit from selling investments held a year or less",
    "long_term_gains": "profit from selling investments held more than a year",
    "stock_unspecified": "stock or investment earnings/profit/gains without saying how long they were held",
    "pre_tax_retirement": "money put INTO a traditional 401(k)/403(b)/IRA (contributions)",
    "retirement_withdrawal": "money taken OUT of a traditional IRA or 401(k), or a pension or annuity payment (taxable income)",
    "state_local_taxes": "state or local income tax paid",
    "property_tax": "property / real estate tax paid on the home the person lives in (a rental's is rental_expense)",
    "mortgage_interest": "mortgage interest paid on the home the person lives in (a rental's is rental_expense)",
    "charity": "charitable donations",
    "tips": "tips received (cash or card tips at a job that gets tips)",
    "overtime": "overtime pay",
    "car_loan_interest": "interest paid on a car loan",
    "student_loan_interest": "interest paid on student loans",
    "care_expenses": "child care or dependent care paid (daycare, after-school care, a nanny) so the user can work",
    "college_expenses": "college tuition, fees and course materials paid",
    "not_tax_input": "an amount that doesn't change the federal tax (rent paid, savings, a price, a target)",
}

SYSTEM = (
    "You sort the amounts in a US personal income-tax question; you never compute tax. For EVERY dollar amount in the "
    "message, give one item {\"amount\": <number as a plain number, 200k -> 200000>, \"kind\": <kind>, \"loss\": "
    "<true only for a capital loss>, \"text\": <the words it came from>}. Kinds:\n"
    + "\n".join(f"- {k}: {v}" for k, v in KINDS.items())
    + "\nFor tips and overtime also give \"included_in_pay\": true when the message says the job pay already includes "
    "them (\"I earn $60k including $10k in tips\").\n"
    "filing_status: \"married_joint\" (married filing jointly, or married and filing together), \"married_separate\" "
    "(married filing separately), \"head_of_household\" (head of household, or an unmarried parent supporting their "
    "children: \"single mom\", \"single dad\", \"single parent\"), \"single\" if the message says single, "
    "otherwise null. year: a tax year the message names, otherwise null.\n"
    "household (counts the message states, else 0): children_under_17 (only children the message says are under 17, or "
    "gives an age under 17 for; a child in college is NOT under 17), other_dependents (dependents 17 or older, e.g. a "
    "college student or a parent), age_65_or_older (the user, and a spouse if filing jointly), students (for college "
    "expenses), graduate_school (true if the college costs are for graduate school or past the first four years).\n"
    "Reply with ONLY JSON: {\"items\": [...], \"filing_status\": null, \"year\": null, \"household\": {}}")

# "tax", and its common typos ("tsx", "tex", "tx"): the proofreader doesn't always get to fix them
_TAX = r"\b(?:tax(?:es)?|tsx|tex|txa?)\b"
ASKS = re.compile(rf"\b(how much|what|estimate|calculate|work out|figure out|total|owe|pay)\b.{{0,80}}{_TAX}|"
                  rf"{_TAX}.{{0,40}}\b(owe|pay|due|bill)\b", re.I | re.S)
INCOME = re.compile(r"\b(earn\w*|salary|income|wages?|make|made|paid|job|dividends?|gains?|profit|bonus)\b", re.I)
# the user's amounts: 200000, 200,000, $200k, 1.5 million (not years like 2026, nor percentages)
AMOUNT = re.compile(r"\$?\b(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|thousand|m|million)?\b(?!\s*%)", re.I)
SOURCES = [{"id": "calc:irs-2026", "title": "IRS: tax inflation adjustments for tax year 2026",
            "url": "https://www.irs.gov/newsroom/irs-releases-tax-inflation-adjustments-for-tax-year-2026-including-amendments-from-the-one-big-beautiful-bill"}]


def asks_income_tax(text: str) -> bool:
    """A question asking for the tax on the user's own income, with at least one amount."""
    return bool(ASKS.search(text) and INCOME.search(text) and amounts(text))


# "I earned $10,600 from stock trading", "I have $10,000 property tax": one of the user's own tax figures, stated
_MINE = re.compile(r"\b(i|i'm|im|i've|ive|my|we|we're|our|me)\b", re.I)
_FIGURE = re.compile(r"\b(earn\w*|salary|income|wages?|job|bonus|stocks?|shares|trading|capital gains?|dividends?|"
                     r"property tax|real estate tax|state tax|local tax|mortgage|charit\w*|donat\w*|tips?|overtime|tuition|"
                     r"college|daycare|child ?care|pension|freelanc\w*|1099|w-?2|rental income|student loans?|loan interest|ira)\b"
                     r"|\bma(?:k|d)e\s+\$?\d", re.I)
# a question about something else that happens to mention a figure: a price, the news, a loan or savings calculation
_OTHER_QUESTION = re.compile(r"\b(stock price|price of|quote|news|how(?:'s| is) .{0,20} doing|should i (?:buy|sell)|"
                             r"how many (?:months|years)|how long|grow|be worth|monthly payment|pay (?:it )?off|save for|"
                             r"retire with)\b", re.I)


def states_tax_figure(text: str) -> bool:
    """A message giving one of the user's own figures (an amount of their income or a deductible cost), with or
    without a question: the tax agent collects it into the running estimate."""
    return bool(amounts(text) and _MINE.search(text) and _FIGURE.search(text) and not _OTHER_QUESTION.search(text))


# a tax situation laid out with its figures, about the user or anyone ("David is a single taxpayer who earns $120,000 ...
# rental income received: $30,000 ... What is David's net rental income?"): the tax agent works it out
_RENTAL = re.compile(r"\b(rental (?:income|property|properties|house|home|unit|apartment)|rents? (?:received|collected)|"
                     r"landlord|schedule e)\b", re.I)
_TAX_SITUATION = re.compile(rf"{_TAX}|\b(taxpayer|deduct\w*|filing (?:status|jointly|separately)|itemi[sz]\w*|"
                            r"student loan interest|charit\w*)\b", re.I)


def is_scenario(text: str) -> bool:
    """Three or more amounts, income among them, and tax words or a rental property: a tax situation to work out."""
    return bool(len(amounts(text)) >= 3 and INCOME.search(text) and _FIGURE.search(text)
                and (_TAX_SITUATION.search(text) or _RENTAL.search(text)) and not _OTHER_QUESTION.search(text))


# A deductible cost mentioned without its amount: what to ask for
_NEEDS_AMOUNT = [
    (re.compile(r"\bmortgage\b", re.I), "mortgage_interest",
     "How much **mortgage interest** do you pay in a year? Only the interest counts, not the whole payment (it's on the "
     "Form 1098 your lender sends each January)."),
    (re.compile(r"\b(property|real estate) tax\b", re.I), "property_tax", "How much **property tax** do you pay in a year?"),
    (re.compile(r"\b(charit\w*|donat\w*)\b", re.I), "charity", "How much did you **give to charity** this year?"),
    (re.compile(r"\b(daycare|child ?care|nanny|babysit\w*)\b", re.I), "care_expenses",
     "How much do you pay for **child care** in a year?"),
    (re.compile(r"\b(tuition|college)\b", re.I), "college_expenses", "How much **tuition and fees** did you pay this year?"),
]


def pending_kind(text: str) -> str:
    """The kind of figure missing_amount asked for."""
    return next((kind for cue, kind, _ in _NEEDS_AMOUNT if cue.search(text)), "")


def missing_amount(text: str, profile: dict | None) -> str:
    """The question to ask when a message names a deductible cost without an amount ("I have a monthly mortgage
    payment"), with what it would take to matter against the user's last estimate; '' when there's nothing to ask."""
    if amounts(text):
        return ""
    for cue, kind, ask in _NEEDS_AMOUNT:
        if not cue.search(text):
            continue
        if kind in ("mortgage_interest", "property_tax", "charity") and profile:
            reading, _ = reading_from(profile.get("items") or [], profile.get("filing_status"), profile.get("year"),
                                      profile.get("household"))
            if reading is not None:
                est = T.estimate(reading.inputs, reading.year)
                gap = est["standard"] - est["itemized"]
                if gap > 0:
                    ask += (f" It lowers your tax only if your itemized deductions beat the {money(est['standard'])} standard "
                            f"deduction: you have {money(est['itemized'])} so far"
                            + (f" (your {money(est['salt_deduction'])} of state, local and property tax)" if est["salt_deduction"] else "")
                            + f", so it would need to be more than {money(gap)} to make a difference.")
                else:
                    ask += " You already itemize, so every dollar of it lowers your taxable income."
        return ask
    return ""


# names with numbers in them, not amounts: 401(k), 403(b), 457 plan, 529 plan, Form 1099 / 1040 / 1098 / W-2, Section 121
NOT_AMOUNTS = re.compile(r"\b(?:401|403)\s*\(?\s*[kb]\s*\)?|\b457\s*(?:\(b\)|plans?)|\b529\b|\b(?:form|schedule|section|"
                         r"publication|pub\.?)\s*[\w-]+|\b(?:1099|1040|1098|8949)(?:-[a-z]+)?\b|\bw-?[24]\b", re.I)


def amounts(text: str) -> list[float]:
    out = []
    text = NOT_AMOUNTS.sub(" ", text)
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
    alternatives: list[tuple[str, str, dict]] = field(default_factory=list)   # (key, what if, changes to the inputs)
    ignored: list[str] = field(default_factory=list)
    rows: list[tuple[str, float, str, str]] = field(default_factory=list)   # (the user's words, amount, how it is treated, kind)
    items: list[dict] = field(default_factory=list)       # the checked figures {text, amount, kind, loss}, for the next turn
    household: dict = field(default_factory=dict)         # children, dependents, 65+, students (household_of)
    status_given: bool = False


INCOME_KINDS = {"wages", "self_employment", "job_unspecified", "interest_dividends", "qualified_dividends", "other_income",
                "short_term_gains", "long_term_gains", "stock_unspecified", "tips", "overtime", "retirement_withdrawal"}
TREATED = {"wages": "wages (job pay)", "self_employment": "self-employment income", "job_unspecified": "wages (job pay), assumed W-2",
           "interest_dividends": "interest / ordinary dividends", "qualified_dividends": "qualified dividends",
           "other_income": "other taxable income", "short_term_gains": "short-term capital gains",
           "long_term_gains": "long-term capital gains", "stock_unspecified": "long-term capital gains (assumed)",
           "pre_tax_retirement": "pre-tax retirement contribution", "state_local_taxes": "state/local tax (itemized deduction)",
           "property_tax": "property tax (itemized deduction)", "mortgage_interest": "mortgage interest (itemized deduction)",
           "charity": "charitable gift (itemized deduction)", "not_tax_input": "not used: doesn't change federal tax",
           "tips": "tips (pay, and a deduction)", "retirement_withdrawal": "retirement withdrawal / pension (income)", "overtime": "overtime pay (pay, and a deduction for the premium)",
           "car_loan_interest": "car-loan interest (deduction)", "student_loan_interest": "student loan interest (deduction)", "care_expenses": "child/dependent care (credit)",
           "college_expenses": "college costs (credit)", "rental_income": "rent received (rental income)",
           "rental_expense": "rental expense (subtracted from the rent)"}


def _items(raw: list, allowed: list[float], must_use: list[float], base: list[dict] | None = None) -> tuple[list[dict] | None, str]:
    """The LLM's items, checked: each a known kind, each amount one the user gave (in the message, or kept from `base`,
    the figures carried from the last estimate), and every amount in the message used. Normalised to
    {text, amount, kind, loss}."""
    out, used = [], []
    for it in raw:
        if not isinstance(it, dict):
            return None, f"unreadable item {it!r}"
        src = base[it["from"]] if base and isinstance(it.get("from"), int) and 0 <= it["from"] < len(base) else None
        if src is None and it.get("amount") in (0, 0.0, "0"):
            continue                                # "$0 of gains": nothing to tax
        if it.get("amount") in (None, "") and it.get("kind") in (None, ""):
            if src is None:
                continue                        # an empty placeholder the model sometimes appends
            it = {**src, **{k: v for k, v in it.items() if v not in (None, "")}}    # a carried figure copied by number only
        try:
            amount = abs(float(it["amount"] if it.get("amount") not in (None, "") else src["amount"]))
            kind = str(it.get("kind") or (src or {}).get("kind"))
        except (KeyError, TypeError, ValueError):
            return None, f"unreadable item {it!r}"
        if kind in HOUSEHOLD or kind == "graduate_school":
            continue                                # a household count put among the figures; it's read from "household"
        words = f"{it.get('text') or ''}"
        if kind == "not_tax_input" and re.search(r"\b(earn\w*|salary|wages?|job|paycheck|make|made)\b", words, re.I):
            kind = "wages"                          # "I earn $70,000" once came back as not a tax input
        if kind not in KINDS:
            return None, f"unknown kind {kind}"
        # a carried figure may be kept, or changed by an amount the message gives ("$10,000 more" on top of $200,000)
        step = [g for g in must_use if src and abs(abs(amount - src["amount"]) - g) < 0.5]
        if not any(abs(amount - g) < 0.5 for g in allowed) and not (src and abs(amount - src["amount"]) < 0.5) and not step:
            return None, f"{amount:,.0f} is not an amount you gave"
        used.append(step[0] if step else amount)
        text = " ".join(str(it.get("text") or (src or {}).get("text") or "").split()) or f"{amount:,.0f}"
        out.append({"text": text, "amount": amount, "kind": kind,
                    "loss": bool(it.get("loss")) and kind in ("short_term_gains", "long_term_gains"),
                    "included": bool(it.get("included_in_pay", (src or {}).get("included"))) and kind in ("tips", "overtime"),
                    "from": it["from"] if src else None})
    missing = [g for g in must_use if not any(abs(g - u) < 0.5 for u in used)]
    if missing:
        return None, "left out " + ", ".join(f"{m:,.0f}" for m in missing)
    if not out:
        return None, "no amounts sorted"
    return out, ""


def read(question: str, reply: dict | None, typed: str = "") -> tuple[Reading | None, str]:
    """(reading, "") or (None, why it was rejected). Every amount must be one of the user's, and every amount of theirs used.
    `typed` is the message as the user wrote it: the proofreader's rewrite once dropped "I'm single", and may add a total."""
    if not reply or not isinstance(reply.get("items"), list) or not reply["items"]:
        return None, "no amounts sorted"
    both = f"{typed} {question}"
    allowed = list(dict.fromkeys(amounts(question) + amounts(typed)))
    items, why = _items(reply["items"], allowed, amounts(typed) if typed else amounts(question))
    if items is None:
        return None, why
    if re.search(r"\b(includ\w*|of which|out of which)\b", both, re.I):     # "$38,000 including $12,000 in tips"
        for it in items:
            if it["kind"] in ("tips", "overtime"):
                it["included"] = True
    return reading_from(items, status_from(reply.get("filing_status"), both), reply.get("year"),
                        household_of(reply.get("household"), both))

HOUSEHOLD = {"children_under_17": r"\b(kids?|child|children|sons?|daughters?|toddler|baby|babies|dependents?|\d{1,2}[- ](year|yr)s?[- ]old)\b",
             # a student or relative is a dependent only when the message says so: tuition for "my son" doesn't make him one
             "other_dependents": r"\b(dependents?|claim(s|ed)? (him|her|them)|support(s|ing)? (my|our) (mother|father|mom|dad|parents?))\b",
             "age_65_or_older": r"\b(6[5-9]|[7-9]\d|retired|retiree|senior|over 65|older)\b",
             "students": r"\b(college|tuition|universit\w*|school|students?)\b"}
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "both": 2, "twins": 2}


_STATUS_WORDS = {
    "married_joint": re.compile(r"\b(jointly|joint return|married|my (wife|husband|spouse)|we file|we're|we are|our)\b", re.I),
    "married_separate": re.compile(r"\bseparate(ly)?\b", re.I),
    "head_of_household": re.compile(r"\b(head of (the )?household|hoh|single (mom|mother|dad|father|parent)|unmarried|divorced|"
                                    r"widow(ed|er)?)\b", re.I),
    "single": re.compile(r"\bsingle\b|\bunmarried\b", re.I),
}
_SAYS_SINGLE = re.compile(r"\b(i['’]?m|i am|she['’]?s|he['’]?s|is a|as a|file as|filing as)\s+(a\s+)?single\b"
                          r"(?!\s+(mom|mother|dad|father|parent))", re.I)     # the proofreader writes I’m with a curly quote


def status_from(status, text: str):
    """The filing status, only as the message supports it: the model once guessed head of household for "I earn $50,000
    and have two kids", and missed "I'm single". A status with no word for it in the message is not given (None)."""
    if status in _STATUS_WORDS and _STATUS_WORDS[status].search(text):
        return status
    return "single" if _SAYS_SINGLE.search(text) else None


def is_question(text: str) -> bool:
    """A question rather than a statement ("How are short-term gains taxed?" vs "The stocks were held less than a year")."""
    t = text.strip().lower()
    return t.endswith("?") or bool(re.match(r"(how|what|why|when|which|who|is|are|do|does|can|could|should|will|would)\b", t))


def household_of(raw, text: str) -> dict:
    """The household counts the model read, kept only when the message talks about them (a count of children needs a
    word for children in it). Counts are 0-10; graduate_school a bool."""
    out = {}
    for key, cue in HOUSEHOLD.items():
        try:
            n = int((raw or {}).get(key) or 0)
        except (TypeError, ValueError):
            n = 0
        if 0 < n <= 10 and re.search(cue, text, re.I):
            out[key] = n
    if (raw or {}).get("graduate_school") is True:
        out["graduate_school"] = True
    # "my son's first year of college": the model has counted a college student as a child under 17 (a $2,200 credit
    # he can't get). With college in the message, a child under 17 needs a sign of a young age.
    young = re.search(r"\b(under (1[0-7]|[1-9])|(\d|1[0-6])[- ]?(year|yr)s?[- ]old|aged? (\d|1[0-6])\b|kids?|toddler|bab(y|ies)|"
                      r"daycare|preschool|elementary|middle school)\b", text, re.I)
    if out.get("children_under_17") and re.search(r"\b(college|universit\w*|tuition)\b", text, re.I) and not young:
        out.pop("children_under_17")
    return out


def reading_from(items: list[dict], status: str | None, year=None, household: dict | None = None) -> tuple[Reading | None, str]:
    """The estimate's inputs from checked items: what is unknown (filing status, holding period, W-2 or 1099) is assumed,
    said, and kept as an alternative to work out too."""
    inp, r = T.TaxInputs(), Reading(T.TaxInputs())
    if not any(it["kind"] == "wages" for it in items):                     # an only job is pay, not a side job
        first = next((it for it in items if it["kind"] == "job_unspecified"), None)
        if first:
            first["kind"] = "wages"
    r.items = [{k: it.get(k, False) for k in ("text", "amount", "kind", "loss", "included")} for it in items]
    r.status_given = status in T.STATUSES
    r.household = dict(household or {})
    for key, n in r.household.items():
        setattr(inp, key, n)
    unspecified_stock = unspecified_job = 0.0
    for it in items:
        amount, kind, loss = it["amount"], it["kind"], it["loss"]
        included = it.get("included") and kind in ("tips", "overtime")
        r.rows.append((it["text"], -amount if loss else amount,
                       TREATED[kind] + (" (loss)" if loss else "") + (" (already in your pay)" if included else ""),
                       "included" if included else kind))
        if kind == "not_tax_input":
            r.ignored.append(it["text"])
        elif kind == "stock_unspecified":
            unspecified_stock += amount
        elif kind == "job_unspecified":
            unspecified_job += amount
        elif kind == "rental_expense":
            inp.rental_expenses += amount               # subtracted from the rent, not itemized (no SALT cap on it)
        elif kind == "retirement_withdrawal":
            inp.other_income += amount                  # taxed as ordinary income (not wages: no payroll tax)
        elif kind == "tips":
            inp.tips += amount
            if not it.get("included"):
                inp.wages += amount                 # tips are pay too; the deduction then takes them back out
        elif kind == "overtime":
            inp.overtime_premium += amount / 3      # the deductible part: the extra "half" of time-and-a-half
            if not it.get("included"):
                inp.wages += amount
            r.assumed.append(f"the ${amount:,.0f} of overtime is paid at time-and-a-half, so the deductible part is the extra "
                             f"half: ${amount / 3:,.0f}")
        else:
            setattr(inp, kind, getattr(inp, kind) + (-amount if loss else amount))
    inp.filing_status = status if status in T.STATUSES else "single"
    if inp.college_expenses and not inp.students:
        inp.students = 1
    said = " ".join(it["text"] for it in items)
    if (inp.college_expenses and not (inp.children_under_17 or inp.other_dependents)
            and re.search(r"\b(son|daughter|child|kid|stepson|stepdaughter)\b", said, re.I)):
        r.alternatives.append(("dependent", "your student is your dependent ($500 credit for other dependents)",
                               {"other_dependents": 1}))
    if not r.status_given:
        r.assumed.append("you file as **single** (married couples filing jointly get wider brackets and a $32,200 standard deduction)")
        r.alternatives.append(("status", "you file jointly with a spouse", {"filing_status": "married_joint"}))
        if inp.children_under_17 or inp.other_dependents:
            r.alternatives.append(("status_hoh", "you're unmarried and pay most of the cost of a home for your children "
                                   "(head of household)", {"filing_status": "head_of_household"}))
    if unspecified_job:
        inp.wages += unspecified_job
        r.assumed.append(f"the ${unspecified_job:,.0f} job pays a W-2 wage (if it is freelance or 1099 work, self-employment tax applies instead)")
        r.alternatives.append(("job", f"the ${unspecified_job:,.0f} job is freelance (1099) work",
                               {"wages": -unspecified_job, "self_employment": unspecified_job}))
    if unspecified_stock:
        inp.long_term_gains += unspecified_stock
        r.assumed.append(f"the ${unspecified_stock:,.0f} from stocks is profit on shares sold after holding them **more than a year** "
                         "(long-term capital gains)")
        r.alternatives.append(("stock", f"the ${unspecified_stock:,.0f} came from shares held a year or less (short-term gains)",
                               {"long_term_gains": -unspecified_stock, "short_term_gains": unspecified_stock}))
    r.inputs = inp
    try:
        r.year = int(year) if year else None
    except (TypeError, ValueError):
        r.year = None
    income = (inp.wages + inp.self_employment + inp.interest_dividends + inp.other_income + inp.short_term_gains
              + inp.long_term_gains + inp.qualified_dividends + inp.rental_income)
    if income <= 0:
        return None, "no income among the amounts"
    return r, ""


def changed(inp: T.TaxInputs, deltas: dict) -> T.TaxInputs:
    """The inputs with one assumption turned the other way (each alternative changes only its own amounts)."""
    return T.TaxInputs(**{**vars(inp), **{k: v if isinstance(v, str) else getattr(inp, k) + v for k, v in deltas.items()}})


def label_of(text: str) -> str:
    """The user's label for a figure listed as "Repairs and maintenance: $3,000" -> "Repairs and maintenance"; '' when the
    amount sits inside a sentence ("paid $4,000 of property tax on the rental")."""
    m = re.fullmatch(r"\s*(.*?\w)\s*[:=-]?\s*\$?\s*\d[\d,]*(?:\.\d+)?\s*(?:k|thousand)?\s*", text, re.I)
    return m.group(1) if m and not AMOUNT.search(m.group(1)) else ""


def figure_words(text: str, amount: float) -> str:
    """A figure in the user's words: "$3,000 (repairs and maintenance)", or their sentence as it is."""
    label = label_of(text)
    return f"{money(amount)} ({label[0].lower() + label[1:]})" if label else text


def money(x: float) -> str:
    n = int(abs(x) + 0.5)                               # whole dollars, halves up
    return f"-${n:,}" if x < 0 else f"${n:,}"


def pct(x: float) -> str:
    return f"{x * 100:.4g}%"


INCOME_LABELS = [("wages", "Wages"), ("self_employment", "Self-employment income"), ("interest_dividends", "Interest and dividends"),
                 ("qualified_dividends", "Qualified dividends"), ("other_income", "Other income"),
                 ("short_term_gains", "Short-term capital gains"), ("long_term_gains", "Long-term capital gains")]


NEW_DEDUCTION_WORDS = {"senior": "Senior deduction ($6,000 per person 65+)", "tips": "Tips", "overtime": "Overtime premium",
                       "car_loan_interest": "Car-loan interest"}
REFUNDABLE_WORDS = {"additional_child_tax_credit": "Refundable part of the child tax credit",
                    "earned_income_credit": "Earned income credit", "american_opportunity_refundable":
                    "Refundable 40% of the American Opportunity credit"}


def credit_line(c: dict, est: dict) -> str:
    """One nonrefundable credit, with how it was worked out."""
    i = est["inputs"]
    if c["name"] == "child_tax_credit":
        kids = [f"{i['children_under_17']} × $2,200 (children under 17)"] if i["children_under_17"] else []
        kids += [f"{i['other_dependents']} × $500 (other dependents)"] if i["other_dependents"] else []
        cut = f" − {money(c['reduced_by'])} (income over the limit)" if c["reduced_by"] else ""
        return f"Child tax credit: {' + '.join(kids)}{cut} = **{money(c['amount'])}**"
    if c["name"] == "child_and_dependent_care":
        return (f"Child and dependent care credit: {pct(c['rate'])} of {money(c['base'])} of care costs "
                f"= **{money(c['amount'])}**")
    if c["name"] == "american_opportunity":
        part = "" if c["share"] >= 1 else f", reduced to {c['share'] * 100:.0f}% by income"
        return (f"American Opportunity credit: {money(c['total'])}{part}; the 60% that isn't refundable is "
                f"**{money(c['amount'])}**")
    if c["name"] == "lifetime_learning":
        part = "" if c["share"] >= 1 else f", reduced to {c['share'] * 100:.0f}% by income"
        return f"Lifetime Learning credit: 20% of {money(c['base'])}{part} = **{money(c['amount'])}**"
    return f"{c['name']}: {money(c['amount'])}"


def render(r: Reading, est: dict, alts: list[tuple[str, dict]]) -> str:
    """The estimate as numbered steps: what each step means in plain words, then the working with the user's numbers."""
    i, p, year = est["inputs"], est["payroll"], est["year"]
    who = {"single": "single filers", "married_joint": "married couples filing jointly", "head_of_household": "heads of household",
           "married_separate": "married people filing separately"}[est["filing_status"]]
    _, rules = T.rules(year)
    L = [f"**Estimated {year} federal taxes** ({STATUS_WORDS[est['filing_status']]}), step by step", "",
         "**Your numbers**", "", "| You said | Amount | Treated as |", "|---|---|---|"]
    L += [f"| {text} | {money(amount)} | {treated} |" for text, amount, treated, _ in r.rows]
    step = 0

    def head(title: str, why: str) -> None:
        nonlocal step
        step += 1
        L.extend(["", f"**Step {step}. {title}**"] + ([why] if why else []) + [""])

    # 1. a rental property
    rent = est["rental"]
    if rent["income"] or rent["expenses"]:
        head("Work out the rental property's profit",
             "Rent is income, but every ordinary cost of the rental comes off it first (on Schedule E): management fees, "
             "repairs, insurance, the rental's property tax and mortgage interest, and depreciation of the building. Its "
             "property tax is a rental expense, so the cap on deducting state and local taxes doesn't limit it.")
        costs = [(text, amount) for text, amount, _, kind in r.rows if kind == "rental_expense"]
        L.append(f"- Rent received: {money(rent['income'])}")
        if costs:
            L.append(f"- Expenses: {' + '.join(figure_words(t, a) for t, a in costs)} = {money(rent['expenses'])}")
        L.append(f"- Net rental {'income' if rent['net'] >= 0 else 'loss'}: {money(rent['income'])} − {money(rent['expenses'])} "
                 f"= **{money(rent['net'])}**")
        if rent["net"] < 0:
            a = rules["rental_loss_allowance"]
            L.append(f"- A rental loss is passive: up to {money(a['amount'])} of it can offset your other income if you actively "
                     f"manage the rental, reduced by half of your income over {money(a['phase_out_start'])} "
                     f"({money(rent['magi'])} here) → {money(rent['allowance'])} allowed"
                     + (" (none married filing separately)" if est["filing_status"] == "married_separate" else ""))
            L.append(f"- Subtracted from income this year: **{money(-rent['allowed'])}**"
                     + (f"; the other {money(rent['carried_forward'])} carries forward to later years (or until you sell)"
                        if rent["carried_forward"] else ""))

    # 2. income
    parts = [(label, i[k]) for k, label in INCOME_LABELS if i[k]]
    head("Add up your income",
         "Income tax starts from everything you earned in the year: pay from jobs and profit from investments you sold. "
         + ("Taxes you paid, like property tax, are not income; they come in at step 2." if i["property_tax"] or i["state_local_taxes"] else ""))
    yours = [(amount, treated) for _, amount, treated, kind in r.rows if kind in INCOME_KINDS]
    if rent["allowed"]:
        yours.append((rent["allowed"], "net rental income"))
        parts.append(("Net rental income", rent["allowed"]))
    if yours:                                           # each of the user's amounts, in their order
        L.append(f"- {' + '.join(money(a) for a, _ in yours).replace('+ -$', '− $')} = **{money(sum(a for a, _ in yours))}**")
    else:
        L.append(f"- {' + '.join(money(v) for _, v in parts)} = **{money(sum(v for _, v in parts))}**")
    if est["capital_loss_deducted"]:
        L.append(f"- Your investments lost money overall: at most $3,000 of the loss can be subtracted from other income, "
                 f"so total income is **{money(est['gross_income'])}**.")
    if est["adjustments"]:
        parts = [(i["pre_tax_retirement"], "pre-tax retirement contributions"),
                 (est["adjustments"] - i["pre_tax_retirement"] - est["student_loan_deduction"], "half of the self-employment tax"),
                 (est["student_loan_deduction"], "student loan interest")]
        parts = [(v, label) for v, label in parts if v > 0.5]
        L.append(f"- Subtract {', '.join(label for _, label in parts)}: {money(est['gross_income'])} − "
                 + " − ".join(money(v) for v, _ in parts) + f" = **{money(est['agi'])}** (adjusted gross income)")
        if i["student_loan_interest"] and est["student_loan_deduction"] < min(i["student_loan_interest"], 2500) - 0.5:
            sl = rules.get("student_loan_interest") or {}
            lo, hi = (sl.get("phase_out") or {}).get(est["filing_status"], (0, 0))
            L.append(f"- Student loan interest: you paid {money(i['student_loan_interest'])}; at most $2,500 counts"
                     + ((f", and none once income is over {money(hi)}" if est["agi"] + est["student_loan_deduction"] >= hi
                         else f", reduced because income is between {money(lo)} and {money(hi)}") if hi else "")
                     + f" → {money(est['student_loan_deduction'])}")

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
    base_std = rules["standard_deduction"][est["filing_status"]]
    L.append(f"- Standard: {money(est['standard'])}" + (f" ({money(base_std)} + {money(est['standard'] - base_std)} for being 65 "
                                                         "or older or blind)" if est["standard"] > base_std else ""))
    if est["itemizes"]:
        L.append(f"- Itemizing is larger, so you deduct **{money(est['deduction'])}**.")
    else:
        L.append(f"- The standard deduction is larger, so you deduct **{money(est['deduction'])}**"
                 + (". Your property tax doesn't lower your income tax here: you'd get the same deduction without it."
                    if i["property_tax"] else "."))

    # 2b. the One Big Beautiful Bill Act deductions
    nd = est["new_deductions"]
    if nd:
        head("The new deductions (2025–2028)",
             "The 2025 tax law added deductions you get on top of the standard or itemized deduction, each capped and "
             "phased out at higher incomes: $6,000 for each person 65 or older, tips, the extra half of overtime pay, and "
             "car-loan interest.")
        for d in nd:
            label = NEW_DEDUCTION_WORDS[d["name"]]
            line = f"- {label}: {money(d['claimed'])}" + (f", capped at {money(d['cap'])}" if d["claimed"] > d["cap"] else "")
            if est["filing_status"] == "married_separate" and d["name"] != "car_loan_interest":
                line += " → **$0** (needs a joint return if you're married)"
            elif d["reduced_by"] > 0 and d["claimed"] <= d["cap"] or d["reduced_by"] > max(0.0, d["claimed"] - d["cap"]):
                line += f", reduced because income is over {money(d['start'])} → **{money(d['amount'])}**"
            else:
                line += f" → **{money(d['amount'])}**"
            L.append(line)

    # 3. taxable income
    head("Work out your taxable income", "Taxable income is income minus the deduction"
         + (" and the new deductions" if nd else "") + ". "
         + ("Long-term gains and qualified dividends in it are taxed at their own, lower rates, so they are split off."
            if est["preferential_income"] else ""))
    extra = sum(d["amount"] for d in nd)
    L.append(f"- {money(est['agi'])} − {money(est['deduction'])}" + (f" − {money(extra)}" if extra else "")
             + f" = **{money(est['taxable_income'])}**")
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
    cr = est["credits"]
    has_credits = bool(cr["nonrefundable"] or cr["refundable_rows"])
    head("Federal income tax" + (" before credits" if has_credits else ""), "Add the pieces.")
    L.append(f"- {' + '.join(money(x) for x in pieces if x) or '$0'} = **{money(est['tax_before_credits'])}**")
    if has_credits:
        head("Credits",
             "Credits come off the tax itself, dollar for dollar. Most can only bring the tax down to zero; the refundable "
             "ones (part of the child tax credit, the earned income credit, part of the American Opportunity credit) are "
             "paid to you even beyond that.")
        for c in cr["nonrefundable"]:
            L.append(f"- {credit_line(c, est)}" + (f"; {money(c['used'])} of it used against your tax" if c["used"] < c["amount"] - 0.5 else ""))
        for c in cr["refundable_rows"]:
            L.append(f"- {REFUNDABLE_WORDS[c['name']]}: **{money(c['amount'])}** (refundable)")
        L.append(f"- Income tax after credits: {money(est['tax_before_credits'])} − {money(cr['nonrefundable_used'])}"
                 + (f" − {money(cr['refundable'])}" if cr["refundable"] else "") + f" = **{money(est['income_tax'])}**"
                 + (" (negative: the IRS pays you this much beyond what was withheld)" if est["income_tax"] < 0 else ""))
    L.append(f"- That is {max(est['effective_rate'], 0) * 100:.1f}% of your total income; your next dollar of ordinary income "
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
    L += ["", "_Not included: state and local income tax, the alternative minimum tax, the saver's and less common "
              "credits, and the earned income credit's limit on investment income. This is an estimate from the published "
              f"{year} rules, not a tax return; Finnie computed every number in Python._"]
    return "\n".join(L)


# ---------------------------------------------------------------- one estimate, its question, and the follow-ups
# The open point that changes the total most is asked about (with the answers as buttons) when it is worth asking:
# at least ASK_MIN_DOLLARS and ASK_MIN_SHARE of the federal total. The others stay stated assumptions.
ASK_MIN_DOLLARS, ASK_MIN_SHARE = 500, 0.01
QUESTIONS = {
    "stock": ("Did you hold the shares more than a year before selling them?",
              ["I held the shares more than a year", "I held the shares a year or less"]),
    "job": ("Is the side job regular W-2 pay, or freelance (1099) work?",
            ["The side job is W-2 pay", "The side job is freelance (1099) work"]),
    "status": ("Do you file as single, or married filing jointly?", ["I file as single", "We're married filing jointly"]),
    "status_hoh": ("Are you married filing jointly, or unmarried and supporting your children (head of household)?",
                   ["I file as head of household", "We're married filing jointly"]),
    "dependent": ("Is the student you pay tuition for your dependent?",
                  ["Yes, my student is my dependent", "No, they aren't my dependent"]),
}


@dataclass
class Estimate:
    text: str
    note: str                               # for the trace
    profile: dict                           # carried to the next turn (context["tax"])
    choices: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)   # tax pages that explain what this estimate used (Read more)


def topics_of(est: dict) -> list[str]:
    """The knowledge-base pages behind an estimate, most specific first: one per credit or deduction it used."""
    i, cr, out = est["inputs"], est["credits"], []
    names = {c["name"] for c in cr["nonrefundable"]} | {c["name"] for c in cr["refundable_rows"]}
    if "american_opportunity" in names:
        out.append("American Opportunity Tax Credit")
    if "lifetime_learning" in names:
        out.append("Lifetime Learning Credit")
    if "child_tax_credit" in names:
        out.append("Child tax credit (United States)")
    if "earned_income_credit" in names:
        out.append("Earned income tax credit")
    if "child_and_dependent_care" in names:
        out.append("Child and Dependent Care Credit")
    if est["rental"]["income"] or est["rental"]["expenses"]:
        out.append("How rental income is taxed")
    if est["new_deductions"]:
        out.append("One Big Beautiful Bill Act")
    if i["long_term_gains"] or i["short_term_gains"] or i["qualified_dividends"]:
        out.append("Capital gains tax in the United States")
    if est["salt_paid"]:
        out.append("State and local tax deduction")
    if i["mortgage_interest"]:
        out.append("Home mortgage interest deduction")
    if i["self_employment"]:
        out.append("Self-employment")
    if est["filing_status"] == "head_of_household":
        out.append("Head of household")
    out += ["Standard deduction", "Tax bracket"]
    return out


def profile_of(r: Reading, est: dict) -> dict:
    """What the next turn needs to redo the estimate: the user's figures as sorted, and what they said or we assumed."""
    return {"year": est["year"], "filing_status": est["filing_status"] if r.status_given else None, "items": r.items,
            "household": r.household,
            "total_federal": round(est["total_federal"], 2), "income_tax": round(est["income_tax"], 2), "choices": []}


def estimate(r: Reading, change: str = "", before: dict | None = None) -> Estimate:
    try:
        est = T.estimate(r.inputs, r.year)
    except ValueError as e:                  # a year without rules: use the latest
        est = T.estimate(r.inputs)
        r.assumed.append(f"the {est['year']} rules ({e})")
    alts = [(key, label, T.estimate(changed(r.inputs, d), est["year"])) for key, label, d in r.alternatives]
    worth = [(abs(a["total_federal"] - est["total_federal"]), key, label, a) for key, label, a in alts]
    worth = [w for w in worth if w[0] >= max(ASK_MIN_DOLLARS, ASK_MIN_SHARE * est["total_federal"])]
    ask = max(worth, key=lambda w: w[0]) if worth else None
    text = render(r, est, [(label, a) for _, label, a in alts])
    if change and before and before.get("total_federal") is not None:
        diff = est["total_federal"] - before["total_federal"]
        text = (f"**Updated:** {change}. Federal taxes go from {money(before['total_federal'])} to "
                f"**{money(est['total_federal'])}** ({'+' if diff >= 0 else '−'}{money(abs(diff))}).\n\n" + text)
    elif change and before:
        text = f"**Updated:** {change}. With your income, federal taxes are **{money(est['total_federal'])}**.\n\n" + text
    choices = []
    if ask:
        key = "status_hoh" if ask[1] in ("status", "status_hoh") and any(k == "status_hoh" for k, _, _ in r.alternatives) else ask[1]
        question, choices = QUESTIONS[key]
        text = text.replace("\n\n_Not included:", f"\n\n**One question:** {question} It changes your federal taxes by about "
                                                  f"{money(ask[0])}; tap an answer below and I'll redo it.\n\n_Not included:", 1)
    i = est["inputs"]
    shown = ", ".join(f"{k}={i[k]:,.0f}" for k in i if k != "filing_status" and i[k])
    note = (f"estimate({est['year']}, {est['filing_status']}, {shown}) → income tax {money(est['income_tax'])}, federal total "
            f"{money(est['total_federal'])}" + (f"; asks about {ask[1]} ({money(ask[0])})" if ask else ""))
    return Estimate(text, note, {**profile_of(r, est), "choices": choices}, choices, topics_of(est))


def answer(question: str, context: str = "", typed: str = "") -> tuple[Estimate | None, str]:
    """(estimate, trace) for an income-tax question; (None, why) when it isn't one this path can work out. `typed` is the
    message as the user wrote it, when the proofreader reworded it."""
    typed = typed if typed and typed.strip() != question.strip() else ""
    said = f"Message: {typed}\n(Reworded: {question})" if typed else f"Message: {question}"
    prompt = f"{context}\n\n{said}" if context else said
    reply = first_json(ask_llm(SYSTEM, prompt))
    reading, why = read(question, reply, typed)
    if reading is None and why not in ("no amounts sorted", "no income among the amounts") and reply:   # one repair round
        retry = first_json(ask_llm(SYSTEM, f"{prompt}\n\nYour last reply was rejected: {why}. Every dollar amount the user "
                                           "typed must be one item, and only those. Reply again with the full JSON."))
        if retry:
            reading2, why2 = read(question, retry, typed)
            if reading2 is not None or why2 == "no income among the amounts":
                reply, reading, why = retry, reading2, why2
    if reading is None and why == "no income among the amounts":           # "I have $10,000 property tax": keep it
        both = f"{typed} {question}"
        items, _ = _items(reply["items"], amounts(both), amounts(typed or question))
        out = noted(items or [], status_from(reply.get("filing_status"), both), household_of(reply.get("household"), both),
                    reply.get("year"))
        return out, out.note
    if reading is None:
        return None, f"income tax: {why}"
    out = estimate(reading)
    return out, out.note


def noted(items: list[dict], status, household: dict, year=None, change: str = "") -> Estimate:
    """Figures with no income yet (a deduction or a credit cost): kept for the estimate, and the income asked for."""
    kept = [{k: it.get(k, False) for k in ("text", "amount", "kind", "loss", "included")} for it in items]
    listed = "; ".join(f"{money(it['amount'])} {TREATED[it['kind']]}" for it in kept) or "nothing yet"
    text = ((f"**Updated:** {change}.\n\n" if change else "")
            + f"**Noted for your tax estimate:** {listed}.\n\nThere's no income yet to work the tax out from. Tell me what "
            "you earn (pay from a job, freelance income, investment gains or dividends) and I'll estimate your federal "
            "tax with everything you've given me.")
    profile = {"year": year, "filing_status": status if status in T.STATUSES else None, "items": kept, "household": household,
               "total_federal": None, "income_tax": None, "choices": []}
    return Estimate(text, f"noted {listed}; no income yet", profile, [], [])


UPDATE_SYSTEM = (
    "You update a US income-tax estimate after the user's latest message; you never compute tax. CURRENT FIGURES are "
    "numbered. Reply with the full new list: copy each current figure the message doesn't remove, with \"from\": its "
    "number; change its kind when the message says what it is (\"the stocks were short-term\" -> short_term_gains, \"the "
    "side job is freelance\" -> self_employment, \"I held them over a year\" -> long_term_gains); change its amount only "
    "to an amount the message gives; add a figure the message adds with \"from\": null (pay the user earns, \"I earn "
    "$70,000\", is wages). Each figure: {\"from\", "
    "\"amount\", \"kind\", \"loss\", \"text\"}. Kinds:\n" + "\n".join(f"- {k}: {v}" for k, v in KINDS.items())
    + "\nfiling_status: what the message says (\"married_joint\", \"married_separate\", \"head_of_household\", "
    "\"single\"), otherwise the current one. household: the full new counts (children_under_17, other_dependents, "
    "age_65_or_older, students, graduate_school): copy the current ones and change only what the message changes. A "
    "message about something else: copy everything unchanged.\n"
    "Reply with ONLY JSON: {\"items\": [...], \"filing_status\": null, \"household\": {}}")


# A message that may change the last estimate: an answer button, or a "what if" about the figures it used
_CHANGES = re.compile(r"\b(what if|instead|also|more|less|extra|another|bonus|raise|married|single|jointly|spouse|wife|husband|"
                      r"held|hold|short[- ]term|long[- ]term|freelance|1099|w-?2|side job|charity|donat\w*|mortgage|deduct\w*|"
                      r"401\(?k\)?|ira|filing)\b", re.I)


def changes_estimate(text: str, profile: dict | None) -> bool:
    """Whether a message may change the last estimate (so the tax agent redoes it rather than explaining)."""
    if not profile:
        return False
    said = " ".join(text.lower().strip(" .!?").split())
    return (any(said == " ".join(c.lower().split()) for c in profile.get("choices") or []) or bool(_CHANGES.search(text))
            or states_tax_figure(text) or bool(missing_amount(text, None))
            or bool(profile.get("pending") and amounts(text)))                 # "$12,000" after "how much interest?"


def describe_profile(p: dict) -> str:
    status = STATUS_WORDS.get(p.get("filing_status"), "not given")
    figures = "\n".join(f"{n}. {it['amount']:.0f} {it['kind']}{' (loss)' if it['loss'] else ''}: \"{it['text']}\""
                        for n, it in enumerate(p.get("items") or []))
    household = ", ".join(f"{k} {v}" for k, v in (p.get("household") or {}).items()) or "none given"
    asked = f"\nThe assistant just asked for: {p['pending']} (an amount in the message is that)" if p.get("pending") else ""
    return f"Filing status: {status}\nHousehold: {household}{asked}\nCURRENT FIGURES:\n{figures or '(none yet)'}"


def follow_up(question: str, profile: dict, typed: str = "") -> tuple[Estimate | None, str]:
    """(estimate, trace) for a message that changes the last estimate ("what if I'm married?", "the stocks were
    short-term", "and if I earn $10,000 more?"); (None, why) when it changes nothing or can't be read. `typed` is the
    message as the user wrote it, when the proofreader reworded it (a rewrite once lost "tax" and "what if")."""
    said = f"Message: {typed}\n(Reworded: {question})" if typed and typed.strip() != question.strip() else f"Message: {question}"
    prompt = f"{describe_profile(profile)}\n\n{said}"
    reply = first_json(ask_llm(UPDATE_SYSTEM, prompt))
    if not reply or not isinstance(reply.get("items"), list):
        return None, "tax follow-up: no usable reply"
    base0, given0 = profile.get("items") or [], list(dict.fromkeys(amounts(question) + amounts(typed)))
    _, why0 = _items(reply["items"], given0 + [b["amount"] for b in base0], amounts(typed) if typed else amounts(question), base0)
    if why0 and why0 != "no amounts sorted":                # one repair round ("left out 40,000": the wife's pay was dropped)
        retry = first_json(ask_llm(UPDATE_SYSTEM, f"{prompt}\n\nYour last reply was rejected: {why0}. Keep every current "
                                                  "figure the message doesn't remove, and add every amount the message gives. "
                                                  "Reply again with the full JSON."))
        if retry and isinstance(retry.get("items"), list):
            reply = retry
    said = f"{question} {typed}"
    status = status_from(reply.get("filing_status"), said) or profile.get("filing_status")
    base = profile.get("items") or []
    # every amount the user typed must be used; the proofreader's rewrite may add some (a total it summed), which are
    # allowed but not required
    given = list(dict.fromkeys(amounts(question) + amounts(typed)))
    items, why = _items(reply["items"], given + [b["amount"] for b in base], amounts(typed) if typed else amounts(question), base)
    if items is None:
        return None, f"tax follow-up: {why}"
    taken = {it["from"] for it in items if it.get("from") is not None}
    for it in items:                    # a carried figure re-listed without its number: match it by amount
        if it.get("from") is None:
            n = next((n for n, b in enumerate(base) if n not in taken and abs(b["amount"] - it["amount"]) < 0.5), None)
            if n is not None:
                it["from"] = n
                taken.add(n)
                it["text"] = base[n]["text"]
    old_house = profile.get("household") or {}
    house = {**old_house, **household_of(reply.get("household"), f"{question} {typed}")} if reply.get("household") else old_house
    said_now = " ".join((typed or question).lower().strip(" .!?").split())
    if said_now == QUESTIONS["dependent"][1][0].lower():      # the "yes, my student is my dependent" button
        house = {**house, "other_dependents": max(house.get("other_dependents", 0), house.get("students", 0) or 1)}
    same = (status == profile.get("filing_status") and house == old_house and
            [(i["amount"], i["kind"], i["loss"]) for i in items] == [(b["amount"], b["kind"], b["loss"]) for b in base])
    if same:
        return None, "tax follow-up: nothing changed"
    reading, why = reading_from(items, status, profile.get("year"), house)
    if reading is None and why == "no income among the amounts":
        out = noted(items, status, house, profile.get("year"), what_changed(base, items, profile.get("filing_status"), status))
        return out, f"follow-up: {out.note}"
    if reading is None:
        return None, f"tax follow-up: {why}"
    change = what_changed(base, items, profile.get("filing_status"), status)
    moved = [f"{HOUSEHOLD_WORDS.get(k, k)}: {house.get(k, 0)}" for k in sorted(set(house) | set(old_house))
             if house.get(k, 0) != old_house.get(k, 0)]
    if moved:
        change = "; ".join([*([] if change == "your figures changed" else [change]), *moved])
    out = estimate(reading, change, profile)
    return out, f"follow-up ({change}): " + out.note


STATUS_WORDS = {"single": "single", "married_joint": "married filing jointly", "married_separate": "married filing separately",
                "head_of_household": "head of household", None: "not given"}
HOUSEHOLD_WORDS = {"children_under_17": "children under 17", "other_dependents": "other dependents",
                   "age_65_or_older": "people 65 or older", "students": "students", "graduate_school": "graduate school"}


def what_changed(base: list[dict], items: list[dict], old_status, new_status) -> str:
    """The follow-up's changes in words, worked out from the figures (not the model's summary)."""
    bits = [f"filing status is now {STATUS_WORDS[new_status]}"] if new_status != old_status else []
    kept = set()
    for it in items:
        b = base[it["from"]] if it.get("from") is not None else None
        if b is None:
            bits.append(f"added {money(it['amount'])} of {TREATED[it['kind']].split(' (')[0]}")
            continue
        kept.add(it["from"])
        if abs(b["amount"] - it["amount"]) >= 0.5:
            bits.append(f"“{b['text']}” {money(b['amount'])} → {money(it['amount'])}")
        if b["kind"] != it["kind"] or b["loss"] != it["loss"]:
            bits.append(f"“{b['text']}” is now {TREATED[it['kind']].split(' (')[0]}")
    bits += [f"removed “{b['text']}”" for n, b in enumerate(base) if n not in kept]
    return "; ".join(bits) or "your figures changed"


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



# ---------------------------------------------------------------- the last estimate, for an explanation that follows it
def estimate_facts(profile: dict | None, question: str) -> str:
    """Lines tying an explanation to the user's last estimate ("how are long-term gains taxed differently from salary?"
    right after it): the figures of theirs the question is about, computed here. '' when there's no estimate or no match."""
    if not profile or not profile.get("items") or profile.get("total_federal") is None:
        return ""
    reading, _ = reading_from(profile["items"], profile.get("filing_status"), profile.get("year"), profile.get("household"))
    if reading is None:
        return ""
    est = T.estimate(reading.inputs, reading.year)
    i, lines, rent = est["inputs"], [], est["rental"]
    if re.search(r"\brent|landlord|schedule e|depreciat", question, re.I) and (rent["income"] or rent["expenses"]):
        costs = [figure_words(it["text"], it["amount"]) for it in profile["items"] if it["kind"] == "rental_expense"]
        lines.append(f"Your rental: {money(rent['income'])} of rent"
                     + (f" minus {money(rent['expenses'])} of expenses ({'; '.join(costs)})" if costs else "")
                     + f" = net rental {'income' if rent['net'] >= 0 else 'loss'} of **{money(rent['net'])}**. "
                     + ("Every one of these expenses is deductible against the rent on Schedule E. " if costs else "")
                     + "The rental's property tax and mortgage interest are rental expenses, not itemized deductions, so the "
                     "SALT cap doesn't limit them and they count even with the standard deduction."
                     + (f" {money(-rent['allowed'])} of the loss offsets other income this year; {money(rent['carried_forward'])} "
                        "carries forward." if rent["net"] < 0 else ""))
    if re.search(r"capital gains?|short[- ]term|stock|shares|ordinary", question, re.I) and est["short_term_taxed"] > 0:
        lines.append(f"Your {money(est['short_term_taxed'])} of short-term gains (shares held a year or less) is taxed as "
                     f"ordinary income, like salary, in your brackets (your top one is {pct(est['marginal_rate'])}), not at "
                     "the lower 0%/15%/20% long-term rates. Like other investment profit, it owes no payroll tax.")
    if re.search(r"capital gains?|long[- ]term|short[- ]term|stock|shares|dividend", question, re.I) and est["preferential_rows"]:
        gain = est["preferential_income"]
        rows = "; ".join(f"{money(b['amount'])} at {pct(b['rate'])} = {money(b['tax'])}" for b in est["preferential_rows"])
        lines.append(f"Your long-term gains and qualified dividends ({money(gain)}) sit on top of {money(est['ordinary_taxable'])} "
                     f"of ordinary taxable income: {rows}. Taxed like salary at your {pct(est['marginal_rate'])} bracket they "
                     f"would have cost about {money(gain * est['marginal_rate'])}, so the lower rate saves about "
                     f"{money(gain * est['marginal_rate'] - est['preferential_tax'])}. The gains owe no payroll tax; your wages "
                     f"owe {money(est['payroll']['total'])} of Social Security and Medicare.")
    if re.search(r"itemi[sz]|standard deduction|deduct", question, re.I):
        lines.append(f"You {'itemize' if est['itemizes'] else 'take the standard deduction'}: itemized {money(est['itemized'])} "
                     f"vs standard {money(est['standard'])}.")
    if re.search(r"bracket|marginal|effective|rate", question, re.I) and not lines:
        lines.append(f"Your top bracket is {pct(est['marginal_rate'])}; income tax is {est['effective_rate'] * 100:.1f}% of "
                     f"total income.")
    if not lines:
        return ""
    return f"**In your estimate ({est['year']} rules, computed by Finnie):**\n" + "\n".join(f"- {x}" for x in lines) + "\n\n"
