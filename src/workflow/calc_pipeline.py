"""Calculator pipeline (mds/calc-pipeline-design.md): 1 understand the question, 2 define what to calculate, 3 find each
standard equation in the knowledge base and on the web and cross-check them, 4 prepare the variables; then Python
validates and computes (src/core/calc_plan.py) and the answer quotes where each equation came from. Each LLM step is its
own call. A question no single equation answers (a simulation) goes to the plan path the caller passes in."""
from __future__ import annotations

import ast
import contextvars
import json
import keyword
import random
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from src.core import calc_plan as PLAN
from src.core import equations as EQ
from src.core.llm import ask_llm
from src.core.tavily import WebSearchUnavailable, web_search, web_search_enabled

from .jsonreply import first_json
from .tools import kb_search

PlanError = PLAN.PlanError
EXAMPLE_CUE = re.compile(r"\b(an? (worked )?example|example (calculation|numbers)|illustrat\w*|sample numbers|hypothetical|"
                         r"(show|walk) me (how|through)|how (do you|do i|to|would you|would i|is) (calculate|work out|compute)|"
                         r"how (is|are) .{1,40} calculated)\b", re.I)


def wants_example(question: str) -> bool:
    """The user asks to see a calculation worked through (with sample numbers), not to calculate their own figures."""
    return bool(EXAMPLE_CUE.search(question or ""))
UNITS = PLAN.UNITS
KINDS = ("formula", "arithmetic", "simulation")
PASSAGE_CHARS = 1500

UNDERSTAND_SYSTEM = (
    "Calculator step 1 of 4: understand the question. Read the user's message (and the conversation, for a follow-up) "
    "and say what they want to know. The message comes first: the conversation only fills in what the message refers "
    "back to or leaves out, so a message that asks a complete question of its own is about that question, not the "
    "earlier topic, and its numbers mean what the message says. Do not calculate anything and do not choose formulas "
    "yet.\n"
    'Reply with ONLY JSON: {"restated": "<one sentence: what the user wants to find out>", "given": [{"value": "<a '
    'number as written>", "means": "<what it is>"}], "find": ["<each quantity to work out>"], "conditions": ["<timing, '
    'compounding, payments or adjustments the message states>"], "ambiguities": ["<a way the question could be read '
    'differently, and the reading you take>"], "example": false}\n'
    "\"example\" is true when the user asks to see how something is calculated or for an example, rather than for a "
    "figure about their own situation.")

DEFINE_SYSTEM = (
    "Calculator step 2 of 4: define what to calculate. From the question and its understanding, list the targets to "
    "compute, in order; a later target may use an earlier one. Targets are only the values that are calculated: the "
    "numbers they are calculated from (given by the user, or sample numbers for an example) are never targets, step 4 "
    "supplies them. Each target is {\"name\": \"<short identifier: a "
    "letter, then letters, digits or _>\", \"label\": \"<what it is, a few words>\", \"unit\": \"money\" | \"rate\" | "
    "\"years\" | \"months\" | \"number\", \"kind\": ...} with kind one of:\n"
    "- \"formula\": a quantity a standard finance equation gives (present value, future value of a lump sum or of "
    "regular deposits, a loan's payment, the number of payments to pay off a loan, the rate needed, real return, APY, "
    "purchasing power, current yield). Add \"concept\": its standard name, \"kb_query\" and \"web_query\": searches "
    "that would find its equation (\"present value of a lump sum formula\").\n"
    "- \"arithmetic\": plain arithmetic on given numbers or earlier targets: a split, a share, a sum or difference "
    "(total interest = payments - amount borrowed, savings = interest before - interest after). Add \"expr\": the "
    "formula over short names, and \"variables\": {name: meaning} for each name in it that isn't an earlier target. A "
    "yes/no question (is it enough? which costs less?) is the difference (cash saved - price) with a label saying what "
    "its sign means (\"left over after buying (negative: short by)\"); never a comparison with < or >.\n"
    "- \"simulation\": only when no equation fits because the amount changes period by period with a condition (a "
    "payment that is a percentage of the remaining balance, withdrawals that rise every year).\n"
    "Add \"assumptions\": the readings you take (\"the monthly payment stays the same after the lump sum\").\n"
    'Reply with ONLY JSON: {"targets": [...], "assumptions": ["..."]}')

EXTRACT_SYSTEM = (
    "Calculator step 3: read a reference for an equation. You get a TARGET (what is being calculated and its standard "
    "name) and numbered SOURCE passages (from a knowledge base or a web search). Find the equation the source states "
    "that computes the target. Copy the passage text that states it into \"quote\" exactly as written, formula "
    "included, from one place in the passage (at most 300 characters). Copy the equation into \"equation\" exactly as "
    "the source writes it too: LaTeX, Greek letters, × and all; don't rewrite it, Python converts it. In \"symbols\" "
    "list every symbol in the equation, written as in the equation, with what the source says it means (from the "
    "passage's definitions; the usual meaning only for one it doesn't define), and say which symbol is the target "
    "(\"for\"). Use only an equation the source states; if it states none for this target, reply {\"found\": false}.\n"
    'Reply with ONLY JSON: {"found": true, "passage": 1, "quote": "...", "equation": "PV = \\\\frac{FV}{(1+i)^{n}}", '
    '"symbols": {"PV": "present value", "FV": "future value", "i": "interest rate per period", "n": "number of '
    'periods"}, "for": "PV"}')

MATCH_SYSTEM = (
    "Calculator step 3: cross-check. Two references were read for the same TARGET of the user's QUESTION and each gave "
    "an equation. Decide three things. \"match\": whether they compute the same quantity the same way (the same model: "
    "compounding, when payments happen, what each variable is), allowing different names and algebraically equivalent "
    "forms; also true when one is a more general form that reduces to the other when its extra terms are zero (WACC "
    "with a preferred-stock term vs equity and debt only). \"use\": \"A\" or \"B\", the one to use for this QUESTION "
    "(the simpler one unless the question involves the extra terms). \"fits\": whether that equation computes what the "
    "QUESTION actually asks for (not a related quantity: what money will be worth in today's dollars is not what goods "
    "will cost later; a monthly payment is not a total). \"misread\": when they don't match because one of them doesn't "
    "compute the TARGET at all (a present-value formula given for a future value, a variable on the wrong side), \"A\" "
    "or \"B\" for that one; null when both are real equations for it that differ.\n"
    'Reply with ONLY JSON: {"reasoning": "<one or two sentences>", "match": true, "use": "B", "fits": true, '
    '"misread": null}')

REFINE_SYSTEM = (
    "Calculator step 3: search again. The references didn't give matching equations for the TARGET; you get why. Write "
    "better searches that would find the standard equation for it.\n"
    'Reply with ONLY JSON: {"kb_query": "...", "web_query": "..."}')

VARIABLES_SYSTEM = (
    "Calculator step 4 of 4: prepare the variables. You get the question, its understanding and, for each target, the "
    "equation to use with what each variable means. Give every listed variable a value, as one of:\n"
    "- an input: {\"value\": number, \"from\": \"user\" (stated in the message or the conversation) or \"sample\" (a "
    "typical value you chose because it wasn't given), \"unit\": \"money\" | \"rate\" (a DECIMAL: 0.065 for 6.5%) | "
    "\"percent\" (as written: 6.5) | \"years\" | \"months\" | \"number\" (a count, or a ratio such as a beta "
    "of 1.2), \"means\": \"...\"}. Only numbers that appear in the message may be \"user\". "
    "Words are numbers too: \"monthly\" is 12 a year.\n"
    "- derived: {\"expr\": a formula over inputs and earlier targets, \"unit\": ...}, for a value the equation needs in "
    "another form: a monthly rate \"r_year/12\" from the yearly rate, a number of months \"12*t\", a balance \"B - L\", "
    "or an earlier target's name.\n"
    "Each variable must mean exactly what the source says it means: a rate per period is the yearly rate divided by "
    "the periods a year, a nominal annual rate stays annual, a number of periods counts periods, not years. If the "
    "source's formula takes a rate as a percentage (the Rule of 72: 72 divided by 7 for 7%), give it with unit "
    "\"percent\" (7), not as a decimal.\n"
    "Put the user's numbers in as inputs under their own short names (\"r_year\": 0.065, \"t\": 10) and derive the "
    "equation's variables from them, so every number in the message the calculation needs is an input. A number the "
    "calculation doesn't need (background, such as the terms of an alternative the question only mentions) goes in "
    "\"ignored\" with why. Don't give values for the targets.\n"
    'Reply with ONLY JSON: {"inputs": {"name": {...}}, "derived": {"name": {"expr": "...", "unit": "..."}}, '
    '"ignored": [{"number": 5, "why": "the loan term; the question asks about saving instead"}]}')


MODEL_NOTE = ("No single standard equation covers this question, so Finnie built a step-by-step model of it; the model "
              "isn't quoted from a source, so check its rules and assumptions above.")
OWN_NOTE = ("Finnie couldn't use a quoted equation for this one, so the formulas above are Finnie's own, not quoted from a "
            "source: check them against the steps shown.")

BUILT_ON_NOTE = ("Finnie set up this calculation itself around the quoted equations below; check that its steps use "
                 "them as the sources state.")
SOURCED_HINT = ("\nThese equations were found in the sources and cross-checked. Where one computes something the "
                "question asks for, build on it with its variables (you may rename them and add steps around them), "
                "never a different formula for the same quantity; leave out one that doesn't (a future value when the "
                "question asks for today's value):\n")

CONFIRM_SYSTEM = (
    "A finance calculator couldn't complete the user's calculation, so before trying again it asks the user to confirm "
    "what they want. You get the user's MESSAGE, how the calculator UNDERSTOOD it (may be missing or wrong) and WHY it "
    "couldn't finish (internal errors: never quote them, never mention variable names, units or plans). Write a short "
    "reply to the user: one sentence saying what you think they want to work out, with the numbers you read from their "
    "message; then what is missing or unclear, as one or two short questions (a value the calculation needs that they "
    "didn't give, or two ways the question could be read). Don't calculate anything and don't invent their numbers.\n"
    "Also give 2 or 3 \"readings\": the user's whole question rewritten so it can be calculated, each a different "
    "likely meaning or a different value for what's missing, in the user's own voice, with every number of theirs and "
    "the added value stated, under 30 words. Not a question about the missing value alone: for \"expected return with "
    "a beta of 1.2 and an 8% market return\", \"What is the expected return with a beta of 1.2, an 8% market return "
    "and a 3% risk-free rate?\", not \"What is the risk-free rate?\".\n"
    'Reply with ONLY JSON: {"message": "...", "readings": ["...", "..."]}')


@dataclass
class Outcome:
    """What the calculator concluded: an executed plan ("answer"); a question for the user ("ask", with `text`, or
    empty when nothing worked: `confirm` then asks what they meant); or no number of the user's in the plan ("needs",
    with `needs`). `trace`: one line per step; `note`: the plan path's own trace line; `understood`: step 1's reply."""
    kind: str
    result: dict | None = None
    text: str = ""
    needs: PLAN.NeedsInput | None = None
    trace: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    note: str = ""
    understood: dict | None = None


def _parallel(*calls):
    """Run the calls at the same time, each in a copy of the current context so tracing callbacks follow them."""
    with ThreadPoolExecutor(len(calls)) as pool:
        futures = [pool.submit(contextvars.copy_context().run, fn) for fn in calls]
        return [f.result() for f in futures]


def _norm(text: str) -> str:
    """Text compared for quoting: no whitespace, backslashes, braces or dollar signs (LaTeX spacing differs)."""
    return re.sub(r"[\s\\{}$]", "", text or "").lower()


# ---------------------------------------------------------------- step 3: sources
def _kb(query: str) -> list[dict]:
    try:
        chunks = kb_search(query, 4)
    except Exception:                                       # Qdrant down: no knowledge-base passages
        return []
    return [{"where": "knowledge base", "title": " › ".join(x for x in (c.get("doc_title"), c.get("section")) if x)
             or "Knowledge base", "url": c.get("source_url"), "text": c.get("text") or ""} for c in chunks]


def _web(query: str) -> list[dict] | None:
    """Web passages, or None when web search isn't configured or fails (then one source is all there is)."""
    if not web_search_enabled():
        return None
    try:
        results = web_search(query)
    except WebSearchUnavailable:
        return None
    return [{"where": "web", "title": r["title"], "url": r["url"], "text": r["content"][:PASSAGE_CHARS]} for r in results]


def _target_text(t: dict) -> str:
    return f"TARGET: {t['label']}" + (f" (standard name: {t['concept']})" if t.get("concept") else "") + f", unit {t['unit']}"


def _check_formula(equation: str, unknown: str, formula: str) -> bool:
    """Whether a rearranged formula solves the equation, tried at random positive values (Python, not the LLM)."""
    names = EQ.variables(equation) - {unknown}
    rng = random.Random(7)
    tried = 0
    for _ in range(20):
        values = {n: rng.uniform(0.05, 3) for n in names}
        try:
            x = EQ.evaluate(formula, values)
            lhs, rhs = (EQ.evaluate(side, {**values, unknown: x}) for side in equation.split("="))
        except EQ.EquationError:
            continue
        tried += 1
        if abs(lhs - rhs) > 1e-7 * max(1.0, abs(lhs), abs(rhs)):
            return False
        if tried >= 3:
            return True
    return False


# ---------------------------------------------------------------- step 3b: the source's equation in Python's notation
GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "Δ": "Delta", "ε": "epsilon", "θ": "theta", "λ": "lam",
         "μ": "mu", "ρ": "rho", "σ": "sigma", "Σ": "Sigma", "τ": "tau", "φ": "phi", "ω": "omega", "ß": "beta"}
LATEX_GREEK = {f"\\{v}": v for v in ("alpha", "beta", "gamma", "delta", "Delta", "epsilon", "theta", "mu", "rho",
                                     "sigma", "Sigma", "tau", "phi", "omega")} | {"\\lambda": "lam"}
LATEX_DROP = re.compile(r"\\(left|right|displaystyle|textstyle|,|;|!|quad)|\$")
LATEX_TEXT = re.compile(r"\\(?:text|mathrm|mathit|mathbf|operatorname)\s*\{([^{}]*)\}")
FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
SQRT = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
EXPECTED = re.compile(r"\bE\s*[(\[]\s*([A-Za-z][A-Za-z0-9_]*)\s*[)\]]")     # E(Rm): the expected value, one name

TRANSLATE_SYSTEM = (
    "Calculator step 3b: rewrite an equation a source states in plain notation a calculator reads. You get the "
    "EQUATION as the source writes it (LaTeX, Unicode or prose symbols), what each SYMBOL means, the TARGET symbol, "
    "Python's attempt and why Python can't use it. Give each symbol a short name (a letter, then letters, digits or _: "
    "\"beta\" for β, \"r_f\" for r_{f}, \"E_Rm\" for E(Rm)) and write the equation with those names and only "
    "+ - * / ^ ( ) and log, ln, exp, sqrt. Keep the equation exactly as stated: don't simplify, add or drop terms.\n"
    'Reply with ONLY JSON: {"names": {"<symbol as given>": "<short name>"}, "equation": "r_e = r_f + beta*(r_m - r_f)"}')


def _ascii_name(symbol: str) -> str:
    """A source's symbol as a name the parser reads: βi -> beta_i, r_{f} -> r_f, E(Rm) -> E_Rm, λ -> lam."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", plain(symbol).replace(" ", ""))
    name = re.sub(r"_+", "_", name).strip("_")
    if name and not name[0].isalpha():
        name = "v_" + name
    return name + "_" if keyword.iskeyword(name) or name in EQ.FUNCS or name in EQ.FUNCS2 or name == "pi" else name


def plain(equation: str) -> str:
    """Python's rewrite of common LaTeX and Unicode notation (no LLM): \\frac{a}{b} -> ((a)/(b)), r_{f} -> r_f,
    β -> beta, E(Rm) -> E_Rm, × · and a spaced x -> *, – and − -> -, [ ] -> ( ). What it can't rewrite is left for
    the LLM."""
    text = LATEX_DROP.sub(" ", equation)
    text = LATEX_TEXT.sub(lambda m: m[1].replace(" ", "_"), text)
    for k, v in sorted(LATEX_GREEK.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(re.escape(k) + r"(?![A-Za-z])", v, text)
    for k, v in GREEK.items():                          # βi -> beta_i: the letter after it is a subscript
        text = re.sub(re.escape(k) + r"(?=[A-Za-z0-9])", v + "_", text).replace(k, v)
    text = re.sub(r"\s+(?=[_^])", "", text)            # "\mu _{i}": LaTeX allows a space before a subscript
    for _ in range(5):                                  # innermost braces first, so nested ones unwrap
        text = re.sub(r"_\{([^{}]*)\}", lambda m: "_" + re.sub(r"\W+", "_", m[1]).strip("_"), text)
        text = re.sub(r"\^\{([^{}]*)\}", r"^(\1)", text)
        text = SQRT.sub(r"sqrt(\1)", FRAC.sub(r"((\1)/(\2))", text))
    text = re.sub(r"\\(cdot|times|ast)(?![A-Za-z])", "*", text)
    text = EXPECTED.sub(r"E_\1", text)
    text = re.sub(r"(?<=[\w)\]])\s+[x×]\s+(?=[\w(\[])", " * ", text)
    text = text.translate(str.maketrans({"×": "*", "·": "*", "⋅": "*", "÷": "/", "−": "-", "–": "-", "—": "-",
                                         "[": "(", "]": ")", "{": "(", "}": ")"}))
    for _ in range(5):                                  # (C) -> C, ^(n) -> ^n; sqrt(x) and 2(x) keep theirs
        text = re.sub(r"(?<![A-Za-z0-9_])\(\s*([A-Za-z0-9_.]+)\s*\)", r"\1", text)
    return " ".join(text.split())


def _reads(equation: str, names: set[str], unknown: str) -> str:
    """Why Python can't use a translated equation, or "" when it can: one "=", it parses, every name in it is one of
    the source's symbols, and the target is among them."""
    if equation.count("=") != 1:
        return "it needs exactly one \"=\""
    try:
        used = EQ.variables(equation)
    except EQ.EquationError as e:
        return f"the parser can't read it: {e}"
    if extra := used - names:
        return f"it uses {', '.join(sorted(extra))}, which isn't one of the source's symbols"
    if unknown not in used:
        return f"the target {unknown} isn't in it"
    return ""


def _tidy(equation: str) -> str:
    """A rewritten equation without the brackets the rewrite left (PV=((C/((1+i)^n))) -> PV = C/(1 + i)^n)."""
    def side(text: str) -> str:
        out = ast.unparse(ast.parse(EQ.to_python(text), mode="eval"))
        return out.replace(" ** ", "^").replace("**", "^").replace(" * ", "*").replace(" / ", "/")
    try:
        return " = ".join(side(s) for s in equation.split("="))
    except (SyntaxError, EQ.EquationError):
        return equation


def _isolated(equation: str, unknown: str) -> str | None:
    """The formula for the unknown when the equation has it alone on one side (r_e = ...), else None (step 5 then
    solves the equation numerically)."""
    left, right = (s.strip() for s in equation.split("="))
    if left == unknown and unknown not in EQ.variables(right):
        return right
    if right == unknown and unknown not in EQ.variables(left):
        return left
    return None


def translate(equation: str, symbols: dict[str, str], target: str) -> tuple[dict | None, str]:
    """Step 3b: an equation as the source writes it, with its symbols' meanings, in the parser's notation. Python's
    rewrite first; if that doesn't read, the LLM translates, with Python's reason fed back for one repair round.
    Returns ({"equation", "for", "names": {symbol: name}, "variables": {name: meaning}} or None, why not)."""
    names = {s: _ascii_name(s) for s in symbols}
    unknown = names.get(target) or _ascii_name(target)
    joined = equation
    for s in sorted({*symbols, target}, key=len, reverse=True):
        if re.search(r"[A-Za-z0-9]\s+[A-Za-z0-9]", s):  # "R i" from a PDF is one symbol, not R times i
            joined = joined.replace(s, re.sub(r"\s+", "", s))
    written = plain(joined)
    why = _reads(written, set(names.values()) | {unknown}, unknown)
    for _ in range(2):
        if not why:
            break
        reply = first_json(ask_llm(TRANSLATE_SYSTEM, (
            f"EQUATION: {equation}\nSYMBOLS:\n" + "\n".join(f"- {s}: {m}" for s, m in symbols.items())
            + f"\nTARGET: {target}\nPython's attempt: {written}\nWhy Python can't use it: {why}"))) or {}
        given = reply.get("names") if isinstance(reply.get("names"), dict) else {}
        names = {s: _ascii_name(str(given.get(s) or names[s])) for s in symbols}   # every symbol keeps a name
        unknown = names.get(target) or _ascii_name(str(given.get(target) or target))
        written = " ".join(str(reply.get("equation") or "").split())
        why = _reads(written, set(names.values()) | {unknown}, unknown)
    if why:
        return None, f"unreadable equation {equation!r} ({why})"
    if written != " ".join(equation.split()):            # rewritten: drop the brackets the rewrite left
        written = _tidy(written)
    used = EQ.variables(written)
    return {"equation": written, "for": unknown, "names": names,
            "variables": {n: symbols.get(s) or n for s, n in names.items() if n in used and n != unknown}}, ""


def extract(target: dict, passages: list[dict] | None) -> tuple[dict | None, str]:
    """Step 3, one source: the equation it states for the target, read as the source writes it (3a) and put in the
    parser's notation (3b), checked by Python (the quote, or at least the equation, is really in the passage; the
    equation reads; a rearranged formula solves it). Returns (equation or None, why not)."""
    if not passages:
        return None, "no passages" if passages is not None else "web search off"
    numbered = "\n\n".join(f"[{j}] {p['title']}\n{p['text'][:PASSAGE_CHARS]}" for j, p in enumerate(passages, 1))
    reply = first_json(ask_llm(EXTRACT_SYSTEM, f"{_target_text(target)}\n\nSOURCE:\n{numbered}")) or {}
    if not reply.get("found"):
        return None, "no equation in it"
    quote = " ".join(str(reply.get("quote") or "").split())[:400]
    raw = " ".join(str(reply.get("equation") or "").split())
    hit = next((p for p in passages if quote and _norm(quote) in _norm(p["text"])), None)
    if hit is None and raw:                             # the quote joined two places: the equation alone will do
        hit = next((p for p in passages if _norm(raw) in _norm(p["text"])), None)
        quote = raw if hit else quote
    if hit is None:
        return None, "its quote isn't in the source"
    given = reply.get("symbols") if isinstance(reply.get("symbols"), dict) else reply.get("variables")
    symbols = {str(k).strip(): " ".join(str(v).split())[:60] for k, v in (given or {}).items() if str(k).strip()}
    read, why = translate(raw, symbols, str(reply.get("for") or "").strip())
    if read is None:
        return None, why
    equation, unknown = read["equation"], read["for"]
    stated = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", quote)}
    if extra := sorted({f"{n:g}" for n, _ in PLAN._constants(equation.replace("=", "-(") + ")")
                        if n not in PLAN.STRUCTURAL and n not in stated}):
        return None, f"its equation has {', '.join(extra)}, which the quote doesn't state"
    formula = plain(" ".join(str(reply.get("formula") or "").split())) or None     # older replies give one
    names = EQ.variables(equation)
    try:
        if formula and (EQ.variables(formula) - names or not _check_formula(equation, unknown, formula)):
            formula = None                                  # a wrong rearrangement: solve the equation instead
    except EQ.EquationError:
        formula = None
    formula = formula or _isolated(equation, unknown)
    return {"where": hit["where"], "title": hit["title"], "url": hit["url"], "quote": quote, "equation": equation,
            "for": unknown, "formula": formula,
            "variables": {n: read["variables"].get(n, n) for n in sorted(names) if n != unknown}}, ""


def _match(question: str, target: dict, a: dict, b: dict) -> tuple[bool, str, dict, dict | None]:
    """(match?, the judge's reasoning, the equation to use, the one misread from its source when they don't match)."""
    def show(e):
        return f"{e['where']} ({e['title']}): {e['equation']}, where " + "; ".join(f"{k} = {v}" for k, v in e["variables"].items())
    reply = first_json(ask_llm(MATCH_SYSTEM, f"QUESTION: {question}\n{_target_text(target)}\n\nA, {show(a)}\nB, {show(b)}")) or {}
    why = " ".join(str(reply.get("reasoning") or "").split())[:300]
    if reply.get("match") is True and reply.get("fits") is False:
        return False, f"they agree, but don't compute what the question asks: {why}", a, None
    same = reply.get("match") is True
    misread = None if same else {"A": a, "B": b}.get(str(reply.get("misread") or "").strip().upper())
    return same, why, b if reply.get("use") == "B" else a, misread


DIFFER = "the sources give different equations"


def _differ(a: dict, b: dict, reason: str) -> str:
    """Why step 3 stops: the two equations, each with its source, for the question to the user."""
    return (f"{DIFFER}:\n- `{a['equation']}` ({a['where']}: {a['title']})\n- `{b['equation']}` ({b['where']}: "
            f"{b['title']})\n({reason})")


def find_equation(question: str, target: dict, trace: list[str]) -> tuple[dict | None, str]:
    """Step 3 for one target: knowledge base and web searched together, an equation read from each, cross-checked by a
    judge; on a mismatch, better searches and one more round. Returns ({"eq", "sources", "status"} or None, why)."""
    queries = (target.get("kb_query") or target.get("concept") or target["label"],
               target.get("web_query") or target.get("concept") or target["label"])
    singles, why = [], ""
    for attempt in (1, 2):
        kb, web = _parallel(lambda: _kb(queries[0]), lambda: _web(queries[1]))
        (e_kb, why_kb), (e_web, why_web) = _parallel(lambda: extract(target, kb), lambda: extract(target, web))
        trace.append(f"3 equation for {target['name']} (round {attempt}): knowledge base "
                     + (f"`{e_kb['equation']}`" if e_kb else why_kb) + "; web " + (f"`{e_web['equation']}`" if e_web else why_web))
        if e_kb and e_web:
            same, reason, use, misread = _match(question, target, e_kb, e_web)
            trace.append(f"3 cross-check {target['name']}: {'match' if same else 'no match'}"
                         + (f", using the {use['where']}'s" if same else "")
                         + (f", the {misread['where']}'s misread" if misread else "") + f" ({reason})")
            if same:
                return {"eq": use, "sources": [e_kb, e_web], "status": "matched"}, ""
            if misread:                                 # not two equations that differ: one source read wrongly
                kept = e_web if misread is e_kb else e_kb
                singles += [kept] if all(kept["url"] != s["url"] or kept["quote"] != s["quote"] for s in singles) else []
                why = f"the {misread['where']}'s equation doesn't compute it: {reason}"
            elif attempt == 2:
                return None, _differ(e_kb, e_web, reason)
            else:
                why = f"the two equations differ: {reason}"
        else:
            singles += [e for e in (e_kb, e_web) if e and all(e["url"] != s["url"] or e["quote"] != s["quote"] for s in singles)]
            if web is None and e_kb:                        # web search isn't available: one source is all there is
                return {"eq": e_kb, "sources": [e_kb], "status": "one source (web search unavailable)"}, ""
            why = f"knowledge base: {e_kb['equation'] if e_kb else why_kb}; web: {e_web['equation'] if e_web else why_web}"
        if attempt == 1:
            q = first_json(ask_llm(REFINE_SYSTEM, f"{_target_text(target)}\nWhy: {why}")) or {}
            queries = (str(q.get("kb_query") or queries[0]), str(q.get("web_query") or queries[1]))
            trace.append(f"3 searching again for {target['name']}: {queries[0]!r} / {queries[1]!r}")
    if len(singles) >= 2:                               # one source per search: cross-check them with each other
        same, reason, use, misread = _match(question, target, singles[0], singles[-1])
        trace.append(f"3 cross-check {target['name']} across searches: {'match' if same else 'no match'} ({reason})")
        if same:
            return {"eq": use, "sources": [singles[0], singles[-1]], "status": "matched"}, ""
        if not misread:
            return None, _differ(singles[0], singles[-1], reason)
        singles = [singles[-1] if misread is singles[0] else singles[0]]
    if singles:
        return {"eq": singles[0], "sources": singles[:1], "status": "one source"}, ""
    return None, "no source states an equation for it"


# ---------------------------------------------------------------- step 4 and the plan
def _usable(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name)) and name not in EQ.FUNCS and name not in EQ.FUNCS2 \
        and name not in ("pi", "period")


def _rename(text: str, mapping: dict[str, str]) -> str:
    return re.sub(r"[A-Za-z][A-Za-z0-9_]*", lambda m: mapping.get(m[0], m[0]), text)


def name_equations(targets: list[dict], found: dict[str, dict]) -> dict[str, dict]:
    """Each formula target's equation with its unknown named after the target and its other variables given names
    unique across the calculation (i, i_2), so one value per name."""
    taken = {t["name"] for t in targets} | {v for t in targets if t["kind"] == "arithmetic" for v in t["variables"]}
    out = {}
    for t in targets:
        if t["kind"] != "formula":
            continue
        e = found[t["name"]]["eq"]
        mapping = {e["for"]: t["name"]}
        for v in sorted(EQ.variables(e["equation"]) - {e["for"]}):
            new, k = (v if _usable(v) else f"{v}_"), 2
            while new in taken:
                new, k = f"{v}_{k}", k + 1
            mapping[v] = new
            taken.add(new)
        out[t["name"]] = {"quote": e["quote"], "equation": _rename(e["equation"], mapping),
                          "formula": _rename(e["formula"], mapping) if e["formula"] else None,
                          "variables": {mapping[v]: e["variables"].get(v, v) for v in mapping if v != e["for"]}}
    return out


def _needed(targets: list[dict], eqs: dict[str, dict]) -> dict[str, str]:
    """Every variable step 4 must fill, with what it means."""
    names = {t["name"] for t in targets}
    need = {}
    for t in targets:
        pairs = eqs[t["name"]]["variables"].items() if t["kind"] == "formula" else t["variables"].items()
        need.update({v: m for v, m in pairs if v not in names})
    return need


def _variables_prompt(prompt: str, understanding: dict, targets: list[dict], eqs: dict[str, dict]) -> str:
    lines = [prompt, "", "Understanding: " + json.dumps(understanding)[:1500], "", "Targets, in order:"]
    for t in targets:
        if t["kind"] == "formula":
            e = eqs[t["name"]]
            lines.append(f"- {t['name']} ({t['label']}): equation `{e['equation']}`, variables as the source defines "
                         "them: " + "; ".join(f"{v} = {m}" for v, m in e["variables"].items())
                         + f"\n  The source says: \"{e['quote'][:400]}\"")
        else:
            lines.append(f"- {t['name']} ({t['label']}) = {t['expr']}, variables: "
                         + "; ".join(f"{v} = {m}" for v, m in t["variables"].items()))
    lines.append("Variables to give values: " + ", ".join(_needed(targets, eqs)))
    return "\n".join(lines)


_KINDS = {"rate": r"\b(rate|return|yield|growth|inflation|apr|apy)\b|%",
          "time": r"\b(periods?|years?|months?|term|duration|time|horizon)\b",
          "money": r"\b(amount|value|principal|payment|price|cost|balance|investment|deposit|savings|loan)\b"}
_UNIT_KINDS = {"rate": "rate", "percent": "rate", "years": "time", "months": "time", "money": "money"}


def _kind(meaning: str) -> str | None:
    """What a variable's meaning says it is: a rate, an amount of money or a time. A rate or an amount "per period" is
    still a rate or an amount; one that reads as both a rate and an amount is unclear (None)."""
    kinds = {k for k, pattern in _KINDS.items() if re.search(pattern, str(meaning or "").lower())}
    if {"rate", "money"} <= kinds:
        return None
    return next((k for k in ("rate", "money", "time") if k in kinds), None)


def _paired(missing: list[str], need: dict[str, str], inputs: dict, derived: dict) -> dict[str, dict]:
    """Step 4 gave the user's number under its own name (r_year: 0.07) and no value for the equation's (r): each such
    variable becomes that input when exactly one unused input is of the same kind (a rate for a rate, years for a
    number of periods). The renamed input keeps its value, unit and "from"; nothing is guessed otherwise."""
    used = " ".join(str((d.get("expr") if isinstance(d, dict) else d) or "") for d in derived.values())
    spare = [k for k in inputs if k not in need and not re.search(rf"\b{re.escape(k)}\b", used)]
    pairs = {}
    for v in missing:
        kind = _kind(need[v])
        fits = [k for k in spare if kind and _UNIT_KINDS.get(str(inputs[k].get("unit"))) == kind and k not in pairs.values()]
        if len(fits) == 1:
            pairs[v] = fits[0]
    return {v: {"expr": k} for v, k in pairs.items()}


def build_plan(targets: list[dict], eqs: dict[str, dict], filled: dict | None, assumptions: list[str]) -> dict:
    """The executable plan: step 4's inputs, its derived values and the targets as steps, in dependency order. Raises
    PlanError when a variable has no value or the steps can't be ordered."""
    filled = filled or {}
    inputs = {k: v for k, v in (filled.get("inputs") or {}).items() if isinstance(v, dict)}
    derived = filled.get("derived") if isinstance(filled.get("derived"), dict) else {}
    need = _needed(targets, eqs)
    names = {t["name"] for t in targets}
    derived = {k: d for k, d in derived.items() if k not in names}    # a target is computed by its own step
    derived |= _paired(sorted(set(need) - set(inputs) - set(derived)), need, inputs, derived)
    if missing := sorted(set(need) - set(inputs) - set(derived)):
        used = " ".join(str((d.get("expr") if isinstance(d, dict) else d) or "") for d in derived.values())
        spare = [k for k in inputs if k not in need and not re.search(rf"\b{re.escape(k)}\b", used)]
        hint = (f"; inputs no variable uses yet: {', '.join(spare)} (derive from one, e.g. "
                f"\"{missing[0]}\": {{\"expr\": \"{spare[0]}\"}}, if it means what {missing[0]} means)" if spare else "")
        if copies := [v for v in missing if (base := re.sub(r"_\d+$", "", v)) != v and base in inputs]:
            hint += (f"; {', '.join(copies)} belong to a second target with the same equation: give each its own value, "
                     f"or derive it (\"{copies[0]}\": {{\"expr\": \"{re.sub(r'_[0-9]+$', '', copies[0])}\"}}) if it's the same")
        raise PlanError(f"no value for {', '.join(f'{v} ({need[v]})' for v in missing)}: give each an input or a "
                        f"derived formula, using the equation's own names{hint}; don't give the targets "
                        f"({', '.join(sorted(names))})")
    steps = []
    for k, d in list(derived.items()):                  # "i": "r_year" only renames an input: make it that input
        expr = str((d.get("expr") if isinstance(d, dict) else d) or "").strip()
        if expr in inputs and k not in inputs and sum(
                str((x.get("expr") if isinstance(x, dict) else x) or "").strip() == expr for x in derived.values()) == 1:
            inputs[k] = {**inputs.pop(expr), "means": need.get(k) or inputs[expr].get("means")}
            del derived[k]
    for k, d in derived.items():
        d = d if isinstance(d, dict) else {"expr": d}
        steps.append({"name": k, "label": need.get(k, k), "expr": str(d.get("expr") or ""),
                      "unit": d.get("unit") if d.get("unit") in UNITS else "number"})
    for t in targets:
        step = {"name": t["name"], "label": t["label"], "unit": t["unit"]}
        if t["kind"] == "arithmetic":
            step["expr"] = t["expr"]
        elif eqs[t["name"]]["formula"]:
            step.update(expr=eqs[t["name"]]["formula"], satisfies=eqs[t["name"]]["equation"], sourced=True)
        else:
            step.update(solve=eqs[t["name"]]["equation"], sourced=True, **{"for": t["name"]})
        steps.append(step)

    def deps(s: dict) -> set[str]:
        text = " ".join(str(s.get(k) or "") for k in ("expr", "satisfies", "solve"))
        return set(re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)) - set(EQ.FUNCS) - set(EQ.FUNCS2) - {s["name"]}

    ordered, defined, pending = [], set(inputs), steps
    while pending:
        ready = next((s for s in pending if deps(s) <= defined | {s["name"]}), None)
        if ready is None:
            raise PlanError("these can't be computed from the inputs: " + "; ".join(
                f"{s['name']} needs {', '.join(sorted(deps(s) - defined))}" for s in pending))
        ordered.append(ready)
        defined.add(ready["name"])
        pending = [s for s in pending if s is not ready]
    label = " and ".join(t["label"] for t in targets)
    if len(label) > 80:                                 # cut at a word, not mid-word
        label = label[:79].rsplit(" ", 1)[0] + "…"
    return {"label": label, "inputs": inputs, "steps": ordered,
            "assumptions": assumptions, "ignored": filled.get("ignored") if isinstance(filled.get("ignored"), list) else []}


def _targets(defined: dict | None) -> tuple[list[dict] | None, str]:
    """Step 2's targets checked by Python (names usable, kinds known, arithmetic readable and without comparisons).
    Returns (targets, "") or (None, why) for the repair round."""
    raw = (defined or {}).get("targets")
    if not isinstance(raw, list) or not raw:
        return None, "no \"targets\" list"
    out, inputs = [], {}
    raw = [t for t in raw if not (isinstance(t, dict) and t.get("kind") in ("given", "input", "sample", "inputs"))]
    if not raw:                                         # only inputs listed: step 4 supplies those, nothing to compute
        return None, "the targets are only inputs; list what is calculated from them"
    for t in raw:
        if not isinstance(t, dict) or t.get("kind") not in KINDS or not _usable(str(t.get("name") or "")):
            return None, f"target {json.dumps(t)[:120]} needs a usable \"name\" and a \"kind\" of {', '.join(KINDS)}"
        t = {**t, "name": str(t["name"]), "label": " ".join(str(t.get("label") or t["name"]).split())[:80],
             "unit": t.get("unit") if t.get("unit") in UNITS else "number"}
        if t["kind"] == "arithmetic":
            expr = str(t.get("expr") or "")
            if re.search(r"[<>]|==|!=", expr):
                return None, f"target {t['name']}: {PLAN.COMPARE_HINT}"
            try:
                EQ.variables(expr)
            except EQ.EquationError as e:
                return None, f"target {t['name']}: can't read {expr!r} ({e})"
            if not expr.strip():
                return None, f"target {t['name']}: an arithmetic target needs \"expr\""
            if re.fullmatch(r"\s*(?:[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?)\s*", expr):
                inputs[t["name"]] = t["label"]              # "beta = given_beta" computes nothing: an input
                continue
            t["variables"] = {str(k): str(v) for k, v in (t.get("variables") or {}).items() if isinstance(t.get("variables"), dict)}
        out.append(t)
    if not out:
        return None, "the targets are only inputs; list what is calculated from them"
    for t in out:                                       # a later target using such an input: step 4 gives its value
        if t["kind"] == "arithmetic":
            t["variables"].update({v: inputs[v] for v in EQ.variables(t["expr"]) if v in inputs and v not in t["variables"]})
    return out, ""


_FILLER = {"the", "a", "an", "of", "my", "your", "their", "its", "in", "to", "for", "per", "amount"}


def _words(text) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower())) - _FILLER


def _is_given(target: dict, understanding: dict) -> bool:
    """A target that is one of the numbers step 1 read from the message ("initial investment" when $5,000 is "the
    initial investment amount"), and not something it said to work out."""
    label = _words(target["label"])
    given = [_words(g.get("means")) for g in understanding.get("given") or [] if isinstance(g, dict)]
    find = [_words(f) for f in understanding.get("find") or []]
    return bool(label) and any(label <= g for g in given) and not any(label <= f or f and f <= label for f in find)


EXAMPLE_NOTE = ("\nThe user asked for a worked example and may give no numbers of their own: choose typical, round sample "
                "numbers for every value they didn't give (\"from\": \"sample\").")


def calculate(question: str, prompt: str, known_text: str, fallback: Callable[[bool, str], Outcome]) -> Outcome:
    """Steps 1 to 7. `prompt`: the conversation and the message, as the LLM steps see them; `fallback(example, hint)`:
    the plan path, for a question with a simulation or one the steps can't handle (`hint`: the sourced equations it
    must build on, when step 3 found them)."""
    trace, example = [], wants_example(question)
    understanding = first_json(ask_llm(UNDERSTAND_SYSTEM, prompt))
    if not understanding:
        return _fallback(fallback, trace, "step 1 gave no usable reply", example, None)
    example = example or understanding.get("example") is True
    if example:
        trace.append("1 worked example: sample numbers allowed")
    trace.append(f"1 understood: {str(understanding.get('restated') or '')[:200]}")
    # the targets come from the message as step 1 understood it (a follow-up's figures included), not from the
    # conversation: an earlier answer's calculations would come back as extra targets
    define = f"Message: {question}\n\nUnderstanding: {json.dumps(understanding)[:2000]}"
    defined = first_json(ask_llm(DEFINE_SYSTEM, define))
    targets, why = _targets(defined)
    if targets is None:                                  # one repair round, with Python's reason
        trace.append(f"2 targets rejected: {why}")
        defined = first_json(ask_llm(DEFINE_SYSTEM, f"{define}\n\nYour previous targets were rejected: {why}\n"
                                                    f"Previous reply: {json.dumps(defined)[:3000]}\n"
                                                    "Reply with ONLY corrected JSON."))
        targets, why = _targets(defined)
    if targets is None:
        return _fallback(fallback, trace, f"step 2 gave no usable targets ({why})", example, understanding)
    if given := [t for t in targets if _is_given(t, understanding)]:
        if len(given) < len(targets):                   # the user's own number, defined as something to calculate
            targets = [t for t in targets if t not in given]
            trace.append("2 dropped targets the message gives: "
                         + ", ".join(f"{t['name']} ({t['label']})" for t in given))
    trace.append("2 targets: " + "; ".join(f"{t['name']} ({t['kind']}: {t['label']})" for t in targets))
    if any(t["kind"] == "simulation" for t in targets):
        return _fallback(fallback, trace, "a target changes period by period (simulation)", example, understanding)
    formula_targets = [t for t in targets if t["kind"] == "formula"]
    found = {}
    for t in formula_targets:
        hit, why = find_equation(question, t, trace)
        if hit is None and why.startswith(DIFFER):
            options = why.split("\n(")[0].split(":\n", 1)[1]
            return Outcome("ask", text=f"I found two different equations for {t['label']} and couldn't tell which one "
                                       f"your question needs:\n\n{options}\n\nWhich fits your case, or what does your "
                                       "situation include?", trace=trace + [f"3 {t['name']}: {why} → ask"])
        if hit is None:
            return _fallback(fallback, trace, f"3 {t['name']}: {why}", example, understanding)
        found[t["name"]] = hit
    eqs = name_equations(targets, found)
    assumptions = [" ".join(str(a).split())[:160] for a in ((defined or {}).get("assumptions") or [])[:4] if str(a).strip()]
    ask = _variables_prompt(prompt, understanding, targets, eqs) + (EXAMPLE_NOTE if example else "")
    errors = []
    for attempt in (1, 2):
        filled = first_json(ask_llm(VARIABLES_SYSTEM, ask if attempt == 1 else
                                    f"{ask}\n\nYour previous values were rejected: {errors[-1]}\nPrevious reply: "
                                    f"{json.dumps(filled)[:3000]}\nReply with ONLY corrected JSON."))
        try:
            plan = build_plan(targets, eqs, filled, assumptions)
            result = PLAN.run(plan, question, known_text, require_checks=False, example=example)
        except PLAN.NeedsInput as e:
            return Outcome("needs", needs=e, trace=trace + ["4 no number is the user's → ask"])
        except PLAN.PlanError as e:
            errors.append(str(e))
            trace.append(f"4 variables rejected: {e}")
            continue
        result["quotes"] = [{"label": t["label"], "equation": eqs[t["name"]]["equation"],
                             "status": found[t["name"]]["status"], "sources": found[t["name"]]["sources"]}
                            for t in formula_targets]
        trace.append("5 computed: " + "; ".join(f"{s['name']} = {result['values'][s['name']]:.6g}" for s in result["steps"]
                                                if result["values"].get(s["name"]) is not None))
        return Outcome("answer", result=result, trace=trace, errors=errors)
    # the sourced equation couldn't be filled in (a sum over cash flows, say): the plan path models it, built on it
    hint = SOURCED_HINT + "\n".join(
        f"- {t['label']}: `{eqs[t['name']]['equation']}`, where "
        + "; ".join(f"{v} = {m}" for v, m in eqs[t["name"]]["variables"].items()) for t in formula_targets)
    quotes = [{"label": t["label"], "equation": eqs[t["name"]]["equation"], "status": found[t["name"]]["status"],
               "sources": found[t["name"]]["sources"]} for t in formula_targets]
    return _fallback(fallback, trace, "step 4 couldn't fill the sourced equation: " + errors[-1][:200], example,
                     understanding, hint, quotes)


def _fallback(fallback: Callable[[bool, str], Outcome], trace: list[str], why: str, example: bool,
              understood: dict | None, hint: str = "", quotes: list[dict] | None = None) -> Outcome:
    out = fallback(example, hint)
    out.trace, out.understood = trace + [f"plan path: {why}"] + out.trace, understood
    if out.result is not None and quotes:               # built on the quoted equations: show where they come from
        out.result["quotes"], out.result["model_note"] = quotes, BUILT_ON_NOTE
    elif out.result is not None:
        out.result["model_note"] = MODEL_NOTE if "simulation" in why else OWN_NOTE
    return out


def confirm(question: str, understood: dict | None, errors: list[str]) -> tuple[str, list[str]]:
    """When nothing could compute the question: ask the user to confirm what they want, from what step 1 understood
    and why it failed, with complete questions they can send back. Returns (message, readings); without a usable
    reply, the message is built from step 1's understanding (or asks plainly what to work out) and readings is empty."""
    seen = json.dumps({k: (understood or {}).get(k) for k in ("restated", "given", "find", "ambiguities")})[:1500]
    reply = first_json(ask_llm(CONFIRM_SYSTEM, f"MESSAGE: {question}\n\nUNDERSTOOD: {seen if understood else '(nothing)'}"
                                               f"\n\nWHY: {' | '.join(errors)[:800] or '(no reason given)'}")) or {}
    message = " ".join(str(reply.get("message") or "").split())
    readings = [" ".join(r.split()) for r in reply.get("readings") or [] if isinstance(r, str) and r.strip()][:3]
    if message:
        return message, readings
    restated = " ".join(str((understood or {}).get("restated") or "").split())
    restated = re.sub(r"^the user (wants|would like|is asking|asks)\b", lambda m: "you " + {"wants": "want",
                      "asks": "ask", "is asking": "are asking"}.get(m[1].lower(), m[1]), restated, flags=re.I)
    if not restated:
        return ("I couldn't work out which calculation you're after. What would you like to find, and which numbers "
                "do you have?"), []
    given = [f"{g.get('value')} ({g.get('means')})" for g in (understood or {}).get("given") or []
             if isinstance(g, dict) and g.get("value") is not None]
    return (f"I couldn't complete this calculation. I read your question as: {restated.rstrip('.')}"
            + (f", using {', '.join(given)}" if given else "") + ". Is that right? If so, which numbers am I "
            "missing; if not, what would you like to work out?"), []
