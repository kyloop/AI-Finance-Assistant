"""A calculation plan the LLM designs (inputs with where each came from, formulas, equations, period-by-period rules and
test cases), validated and executed here in Python: the LLM never writes a result. The guards (no invented numbers,
every number in the question used, self-checks) are described in mds/calc-plan-design.md."""
from __future__ import annotations

import ast
import math
import re
from src.core import equations as EQ

MAX_STEPS, MAX_INPUTS, MAX_CHECKS, MAX_EXPR, MAX_PERIODS, MAX_ROWS = 16, 20, 6, 200, 1200, 50
UNITS = ("money", "rate", "percent", "years", "months", "number")   # rate: a decimal (0.07); percent: as written (7)
STRUCTURAL = {0, 1, 2, 12, 52, 100, 365}             # constants a formula may contain anywhere without an input
EXPONENTS = set(range(13))                           # and, only as an exponent, small whole numbers (year 3 of a cash flow)
LIMIT_STEP = 1e-6         # a check at 0 that can't be evaluated is taken as the limit there: 2·f(h) − f(2h), error ~h²
COUNTS = {1, 2, 4, 12, 52, 365}                      # counts the user may state in words ("compounded monthly")
STEP_KINDS = ("expr", "solve", "simulate", "vary")

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_COMPARE = re.compile(r"<=|>=|<|>")
_SKIP = re.compile(r"\b(?:401|403|457)\s*\(?\s*[kb]\s*\)?|\b529\b|S&P\s*500", re.I)   # numbers that are names
_QNUM = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?:\s*(k|thousand|m|mm|mn|million|b|bn|billion)\b)?", re.I)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}

class PlanError(ValueError):
    """A plan that can't be used; the message says why, for the LLM's one repair round."""


class CheckFailed(PlanError):
    """A plan that ran but disagrees with one of its own checks: either may be wrong, which a judge decides."""

    def __init__(self, message: str, index: int, check: dict, actual: float | None, expected: float | None, rows: list):
        super().__init__(message)
        self.index, self.check, self.actual, self.expected, self.rows = index, check, actual, expected, rows


class NeedsInput(Exception):
    """A valid plan in which no number is the user's: ask for them instead of answering with samples only."""

    def __init__(self, label: str, inputs: list[str]):
        super().__init__(label)
        self.label, self.inputs = label, inputs


# ---------------------------------------------------------------- numbers in text
def question_numbers(text: str) -> list[float]:
    """The numbers a message states, scaled ("$1 million" → 1000000, "50k" → 50000), without ones that are part of a
    name (401(k), 529, S&P 500)."""
    out = []
    for m in _QNUM.finditer(_SKIP.sub(" ", text)):
        x = float(m[1].replace(",", "") or 0)
        out.append(x * _SCALE[m[2].lower()] if m[2] else x)
    return out


def _known(text: str) -> list[float]:
    """Every number in the conversation, both as written and scaled, for checking that a user input is really there."""
    out = []
    for m in _QNUM.finditer(text):
        x = float(m[1].replace(",", "") or 0)
        out += [x, x * _SCALE[m[2].lower()]] if m[2] else [x]
    return out


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def _fmt(x: float | None) -> str:
    return "none (a simulation that never stopped, or an equation with no solution)" if x is None else f"{x:.10g}"


# ---------------------------------------------------------------- parsing
def _name(n, what: str) -> str:
    n = str(n or "").strip()
    if not _NAME.match(n) or n in EQ.FUNCS or n in EQ.FUNCS2 or n in ("pi", "period"):
        raise PlanError(f"{what} {n!r} is not a usable name (a letter, then letters, digits or _; not a function name)")
    return n


COMPARE_HINT = ("a formula can't compare (<, >): for a yes/no question (is it enough? which costs less?) compute the "
                "difference instead (savings - price), whose sign answers it")


def _expr(text, what: str, names: set[str]) -> str:
    """A formula's text checked: short, readable, no comparison, and using only defined names."""
    text = " ".join(str(text or "").split())
    if not text or len(text) > MAX_EXPR:
        raise PlanError(f"{what}: needs a formula of at most {MAX_EXPR} characters")
    if re.search(r"[<>]|==|!=", text):
        raise PlanError(f"{what}: {COMPARE_HINT}")
    try:
        used = EQ.variables(text)
    except EQ.EquationError as e:
        raise PlanError(f"{what}: {e}") from None
    if unknown := sorted(used - names):
        raise PlanError(f"{what}: {', '.join(unknown)} not defined (an input or an earlier step)")
    return text


def _condition(text, what: str, names: set[str]) -> tuple[str, str, str]:
    text = " ".join(str(text or "").split())
    parts = _COMPARE.split(text)
    ops = _COMPARE.findall(text)
    if len(ops) != 1:
        raise PlanError(f"{what}: a condition needs exactly one of < <= > >=")
    return _expr(parts[0], what, names), ops[0], _expr(parts[1], what, names)


def _number(v, what: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise PlanError(f"{what}: {v!r} is not a number") from None
    if not math.isfinite(x):
        raise PlanError(f"{what}: not a finite number")
    return x


def parse(plan) -> dict:
    """The LLM's plan checked for shape, names and limits, and normalised. Raises PlanError."""
    if not isinstance(plan, dict):
        raise PlanError("the reply is not a JSON plan")
    raw_inputs, raw_steps = plan.get("inputs"), plan.get("steps")
    if isinstance(raw_inputs, list):                     # [{"name": "P", "value": ...}] is accepted too
        raw_inputs = {i.get("name"): i for i in raw_inputs if isinstance(i, dict)}
    if not isinstance(raw_inputs, dict) or not 0 < len(raw_inputs) <= MAX_INPUTS:
        raise PlanError(f"\"inputs\" must be an object with 1 to {MAX_INPUTS} inputs")
    if not isinstance(raw_steps, list) or not 0 < len(raw_steps) <= MAX_STEPS:
        raise PlanError(f"\"steps\" must be a list of 1 to {MAX_STEPS} steps")
    inputs = {}
    for k, spec in raw_inputs.items():
        k = _name(k, "input")
        spec = spec if isinstance(spec, dict) else {"value": spec}
        unit = spec.get("unit") if spec.get("unit") in UNITS else "number"
        value = _number(spec.get("value"), f"input {k}")
        if unit == "rate" and abs(value) > 1:
            raise PlanError(f"input {k}: rates are decimals (0.08 for 8%), got {value:g}; if {k} isn't a percentage (a "
                            f"beta, a ratio, a multiplier), keep {value:g} and make its unit \"number\"")
        inputs[k] = {"value": value, "from": "sample" if spec.get("from") == "sample" else "user", "unit": unit,
                     "means": " ".join(str(spec.get("means") or k).split())[:60]}

    defined, steps, simple = set(inputs), [], set(inputs)       # simple: names a check or a vary may refer to
    for i, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict):
            raise PlanError(f"step {i} is not an object")
        kinds = [k for k in STEP_KINDS if raw.get(k) not in (None, "", {}, [])]
        if len(kinds) != 1:
            raise PlanError(f"step {i} needs exactly one of {', '.join(STEP_KINDS)}")
        name = _name(raw.get("name") or f"step{i}", f"step {i} name")
        if name in defined:
            raise PlanError(f"step {i}: the name {name!r} is already used")
        step = {"name": name, "kind": kinds[0], "label": " ".join(str(raw.get("label") or name).split())[:80],
                "unit": raw.get("unit") if raw.get("unit") in UNITS else "number",
                "sourced": raw.get("sourced") is True}      # an equation quoted from a source: its constants are the source's
        what = f"step {name}"
        if kinds[0] == "expr":
            step["expr"] = _expr(raw["expr"], what, defined)
            if raw.get("satisfies"):                         # the equation this formula was rearranged from
                eq = " ".join(str(raw["satisfies"]).split())
                if eq.count("=") != 1 or len(eq) > MAX_EXPR:
                    raise PlanError(f"{what}: \"satisfies\" needs one equation with a single '='")
                for side in eq.split("="):
                    _expr(side, what, defined | {name})
                if name not in EQ.variables(eq):
                    raise PlanError(f"{what}: \"satisfies\" must contain {name!r}, the value it is solved for")
                step["satisfies"] = eq
        elif kinds[0] == "solve":
            if not raw.get("for"):
                raise PlanError(f"{what}: a solve step needs \"for\": the unknown to solve for")
            eq, unknown = " ".join(str(raw["solve"]).split()), _name(raw.get("for"), f"{what} unknown")
            if eq.count("=") != 1 or len(eq) > MAX_EXPR:
                raise PlanError(f"{what}: \"solve\" needs one equation with a single '='")
            if unknown in defined:
                raise PlanError(f"{what}: the unknown {unknown!r} is already defined")
            for side in eq.split("="):
                _expr(side, what, defined | {unknown})
            if unknown not in EQ.variables(eq):
                raise PlanError(f"{what}: the unknown {unknown!r} is not in the equation")
            step.update(solve=eq, unknown=unknown)
        elif kinds[0] == "simulate":
            sim = raw["simulate"] if isinstance(raw["simulate"], dict) else {}
            start = sim.get("start") if isinstance(sim.get("start"), dict) else {}
            if not start:
                raise PlanError(f"{what}: \"simulate\" needs \"start\" values for its state")
            state = {_name(k, f"{what} state"): v for k, v in start.items()}
            if clash := sorted(set(state) & defined):
                raise PlanError(f"{what}: state {', '.join(clash)} clashes with an input or step name")
            each = sim.get("each") if isinstance(sim.get("each"), dict) else {}
            if not each or not set(each) & set(state):
                raise PlanError(f"{what}: \"each\" must update the state variables ({', '.join(state)})")
            helpers = [_name(k, f"{what} helper") for k in each if k not in state]   # per-period values, computed first
            if clash := sorted(set(helpers) & defined):
                raise PlanError(f"{what}: helper {', '.join(clash)} clashes with an input or step name")
            scope, helper_exprs = defined | set(state), {}
            for h in helpers:                                    # each helper may use the state and earlier helpers
                helper_exprs[h] = _expr(each[h], what, scope)
                scope = scope | {h}
            if (sim.get("until") is None) == (sim.get("periods") is None):
                raise PlanError(f"{what}: give exactly one of \"until\" (a stop condition) or \"periods\" (a count)")
            result = str(raw.get("result") or sim.get("result") or ("periods" if sim.get("until") else "")).strip()
            if result != "periods" and result not in state:
                raise PlanError(f"{what}: \"result\" must be \"periods\" or a state variable")
            if result == "periods" and not sim.get("until"):
                raise PlanError(f"{what}: \"result\": \"periods\" needs an \"until\" condition")
            period = "month" if sim.get("period") == "month" else "year"
            step.update(start={k: _expr(v, what, defined) for k, v in state.items()},
                        helpers=helper_exprs,
                        each={k: _expr(v, what, scope) for k, v in each.items() if k in state},
                        until=_condition(sim["until"], what, scope) if sim.get("until") else None,
                        periods=_expr(sim["periods"], what, defined) if sim.get("periods") is not None else None,
                        max=int(min(max(_number(sim.get("max", 100), f"{what} max"), 1), MAX_PERIODS)),
                        result=result, period=period)
            if result == "periods" and step["unit"] not in ("years", "months"):
                step["unit"] = period + "s"
        else:
            vary = raw["vary"] if isinstance(raw["vary"], dict) else {}
            inp = str(vary.get("input") or "").strip()
            if inp not in inputs:
                raise PlanError(f"{what}: \"vary\" needs \"input\", one of the inputs")
            if isinstance(vary.get("values"), list):
                values = [_number(v, what) for v in vary["values"]]
            else:
                lo, hi = _number(vary.get("from"), f"{what} from"), _number(vary.get("to"), f"{what} to")
                by = _number(vary.get("step", 1), f"{what} step")
                if by <= 0 or (hi - lo) / by + 1 > MAX_ROWS:
                    raise PlanError(f"{what}: from/to/step must give 1 to {MAX_ROWS} values")
                values = [lo + j * by for j in range(int(math.floor((hi - lo) / by + 1e-9)) + 1)]
            of = raw.get("of") if isinstance(raw.get("of"), list) else [raw.get("of")]
            of = [str(o).strip() for o in of if o]
            if not 0 < len(values) <= MAX_ROWS or not of or set(of) - (simple - set(inputs)):
                raise PlanError(f"{what}: needs 1 to {MAX_ROWS} values and \"of\": earlier steps (not inputs or vary steps)")
            step.update(input=inp, values=values, of=of)
        steps.append(step)
        defined.add(name)
        if step["kind"] != "vary":
            simple.add(name)

    checks = []
    for j, c in enumerate(plan.get("checks") or [], 1):
        if j > MAX_CHECKS or not isinstance(c, dict):
            raise PlanError(f"at most {MAX_CHECKS} checks, each an object")
        when = c.get("when") if isinstance(c.get("when"), dict) else {}
        if not when or set(when) - set(inputs):
            raise PlanError(f"check {j}: \"when\" must set one or more inputs")
        of = str(c.get("of") or "").strip()
        if of not in simple - set(inputs):
            raise PlanError(f"check {j}: \"of\" must be a step (not a vary step)")
        checks.append({"when": {k: _number(v, f"check {j}") for k, v in when.items()}, "of": of,
                       "expect": _expr(c.get("expect"), f"check {j}", simple)})
    ignored = []
    for g in plan.get("ignored") or []:
        if isinstance(g, dict) and str(g.get("why") or "").strip():
            ignored.append({"number": _number(g.get("number"), "ignored number"), "why": " ".join(str(g["why"]).split())[:100]})
    assumptions = [" ".join(str(a).split())[:160] for a in (plan.get("assumptions") or [])[:5] if str(a).strip()]
    return {"label": " ".join(str(plan.get("label") or "the calculation").split())[:80], "inputs": inputs,
            "steps": steps, "checks": checks, "ignored": ignored, "assumptions": assumptions}


# ---------------------------------------------------------------- guards
def _formulas_of(step: dict) -> list[str]:
    if step["kind"] == "expr":
        return [step["expr"]]
    if step["kind"] == "solve":
        return step["solve"].split("=")
    if step["kind"] == "simulate":
        return [*step["start"].values(), *step["helpers"].values(), *step["each"].values(),
                *(step["until"][::2] if step["until"] else []),
                *([step["periods"]] if step["periods"] else [])]
    return []


def _checked_formulas(step: dict) -> list[str]:
    """Every formula whose numbers guard 1 covers: the step's own and the equation it satisfies."""
    return _formulas_of(step) + (step["satisfies"].split("=") if step.get("satisfies") else [])


def _used_names(p: dict) -> set[str]:
    names = set()
    for s in p["steps"]:
        for f in _formulas_of(s):
            names |= EQ.variables(f)
        if s["kind"] == "vary":
            names.add(s["input"])
    return names


def check_numbers(p: dict, question: str, known_text: str) -> None:
    """Guard 1, no invented numbers: user inputs are in the conversation, formulas contain only structural constants.
    Also that every input is used by a step. Raises PlanError."""
    known = _known(known_text)
    for k, i in p["inputs"].items():
        v = i["value"]
        if i["from"] != "user" or v == 0 or any(_close(abs(v), x) for x in known):     # money paid out may be negative
            continue
        if i["unit"] == "rate" and any(_close(abs(v) * 100, x) for x in known):
            continue
        if i["unit"] in ("number", "years") and v in COUNTS:
            continue
        raise PlanError(f"input {k} = {v:g} is marked \"user\" but isn't in the question or the conversation; "
                        "mark it \"sample\" if it's an assumption")
    constants = set()
    for s in p["steps"]:
        for f in _checked_formulas(s):
            for n, exponent in _constants(f):
                if s["sourced"]:                          # e.g. the 72 of the Rule of 72, stated by the source
                    constants.add(n)
                    continue
                if n not in STRUCTURAL and not (exponent and n in EXPONENTS):
                    raise PlanError(f"step {s['name']}: the number {n:g} in a formula must be an input, marked \"sample\" "
                                    "if it's an assumption (formulas may only contain 0, 1, 2, 12, 52, 100 and 365, and "
                                    "whole numbers up to 12 as exponents)")
                constants.add(n)
    percents = {k for k, i in p["inputs"].items() if i["unit"] == "percent"}
    for s in p["steps"]:                                # (1 + r) needs r as a decimal: 1 + 7 is a unit error
        for f in _checked_formulas(s):
            if bad := [k for k in percents if re.search(rf"\b1\s*[-+]\s*{re.escape(k)}\b|\b{re.escape(k)}\s*[-+]\s*1\b", f)]:
                raise PlanError(f"step {s['name']}: {', '.join(bad)} is a percentage (unit \"percent\") added to 1 in "
                                f"{f.strip()!r}; give it as a rate, a decimal (0.07 for 7%)")
    rates = {k for k, i in p["inputs"].items() if i["unit"] == "rate"} | {s["name"] for s in p["steps"] if s["unit"] == "rate"}
    for s in p["steps"]:                                # rm - rf with rm = 8 and rf = 0.03: 8 - 0.03 is a unit error
        for f in _checked_formulas(s):
            if bad := sorted({k for k in percents for r in rates if re.search(
                    rf"\b{re.escape(k)}\s*[-+]\s*{re.escape(r)}\b|\b{re.escape(r)}\s*[-+]\s*{re.escape(k)}\b", f)}):
                raise PlanError(f"step {s['name']}: {', '.join(bad)} is a percentage (unit \"percent\") added to or "
                                f"subtracted from a rate (a decimal) in {f.strip()!r}; give it as a rate too, a decimal "
                                "(0.08 for 8%)")
    percents |= {s["name"] for s in p["steps"] if s["unit"] == "percent"}
    for s in p["steps"]:                                # 2 + 1.2*(8 - 2) = 9.2 is 9.2%, not a rate of 920%
        text = " ".join(_checked_formulas(s))
        names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
        if s["unit"] not in ("rate", "percent") or re.search(r"\b100\b", text):
            continue
        if s["unit"] == "rate" and names & percents and not names & rates:
            raise PlanError(f"step {s['name']}: its unit is \"rate\" (a decimal) but it's computed from percentages "
                            f"({', '.join(sorted(names & percents))}); make its unit \"percent\", or give the inputs "
                            "as decimals")
        if s["unit"] == "percent" and names & rates and not names & percents:
            raise PlanError(f"step {s['name']}: its unit is \"percent\" but it's computed from rates (decimals: "
                            f"{', '.join(sorted(names & rates))}); make its unit \"rate\"")
    used = _used_names(p)
    if unused := [k for k in p["inputs"] if k not in used]:
        raise PlanError(f"input(s) {', '.join(unused)} not used by any step")
    p["constants"] = constants


def check_all_used(p: dict, question: str, values: dict) -> None:
    """Guard 2: every number in the question is a user input that a step uses, a constant in a formula, a value the plan
    computes (15,000 − 5,000 reproduces "drops to $10,000"), or listed as ignored with why. Raises PlanError."""
    candidates = [g["number"] for g in p["ignored"]] + list(p["constants"])
    for k, i in p["inputs"].items():
        if i["from"] == "user":
            v = abs(i["value"])
            candidates += [v, v * 100] if i["unit"] == "rate" else [v]
    for s in p["steps"]:
        v = values.get(s["name"])
        if v is not None and s["kind"] != "vary":
            candidates += [abs(v), abs(v) * 100] if s["unit"] == "rate" else [abs(v)]
    for q in question_numbers(question):
        if not any(_close(q, c) for c in candidates):
            raise PlanError(f"the question's number {q:g} isn't used: make it a \"user\" input that a step uses, "
                            "compute it in a step, or list it in \"ignored\" with why")


def _constants(formula: str) -> list[tuple[float, bool]]:
    """Each number in a formula, and whether it is (part of) an exponent."""
    out = []

    def walk(node, exponent):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            out.append((float(node.value), exponent))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            walk(node.left, exponent)
            walk(node.right, True)
        else:
            for child in ast.iter_child_nodes(node):
                walk(child, exponent)

    try:
        walk(EQ.compile_expr(formula), False)
    except EQ.EquationError as e:
        raise PlanError(f"{formula!r}: {e}") from None
    return out


def _needs_checks(p: dict) -> bool:
    return any(s["kind"] in ("solve", "simulate") or any(re.search(r"\^|\bexp\b|\blog\b|\bln\b", f) for f in _formulas_of(s))
               for s in p["steps"])


# ---------------------------------------------------------------- execution
class _Executor:
    def __init__(self, p: dict):
        self.p = p

    def _ev(self, text: str, values: dict) -> float | None:
        if any(values.get(n, 0) is None for n in EQ.variables(text)):
            return None                                  # depends on a result that doesn't exist (never runs out)
        try:
            return EQ.evaluate(text, values)
        except EQ.EquationError as e:
            raise PlanError(f"{text!r}: {e}") from None

    def run(self, overrides: dict | None = None, top: bool = False) -> tuple[dict, dict]:
        """Every step in order (vary steps only at the top level): {name: value or None}, {name: details}."""
        values = {k: (overrides or {}).get(k, i["value"]) for k, i in self.p["inputs"].items()}
        details = {}
        for s in self.p["steps"]:
            name, what = s["name"], f"step {s['name']}"
            if s["kind"] == "expr":
                values[name] = self._ev(s["expr"], values)
                if top and s.get("satisfies") and values[name] is not None:
                    self._satisfies(s, values)
            elif s["kind"] == "solve":
                values[name], details[name] = self._solve(s, values)
            elif s["kind"] == "simulate":
                values[name], details[name] = self._simulate(s, values)
                if top and values[name] is None and s["result"] != "periods":
                    raise PlanError(f"step {name}: the simulation ran {s['max']} {s['period']}s without reaching "
                                    f"`{' '.join(s['until'])}`, so `{s['result']}` has no final value: check the "
                                    "payment and the stop condition (a debt should be paid off well before then)")
            elif top:
                details[name] = self._vary(s)
            if s["kind"] != "vary" and values[name] is not None and not math.isfinite(values[name]):
                raise PlanError(f"{what}: not a finite number")
        return values, details

    def _satisfies(self, s: dict, values: dict) -> None:
        """A formula the LLM rearranged itself: its result must solve the equation it came from."""
        lhs, rhs = (self._ev(side, values) for side in s["satisfies"].split("="))
        if lhs is None or rhs is None or abs(lhs - rhs) > 1e-9 * max(1.0, abs(lhs), abs(rhs)):
            raise PlanError(f"step {s['name']}: {s['name']} = {_fmt(values[s['name']])} doesn't satisfy "
                            f"{s['satisfies']} ({_fmt(lhs)} vs {_fmt(rhs)}), so the rearranged formula is wrong")

    def _solve(self, s: dict, values: dict) -> tuple[float | None, dict]:
        known = {k: v for k, v in values.items() if v is not None}
        try:
            return EQ.solve(s["solve"], s["unknown"], known)["value"], {}
        except EQ.EquationError as e:
            if "no real solution" in str(e):
                return None, {}
            raise PlanError(f"step {s['name']}: {e}") from None

    def _simulate(self, s: dict, values: dict) -> tuple[float | None, dict]:
        state = {k: self._ev(f, values) for k, f in s["start"].items()}
        if any(v is None for v in state.values()):
            return None, {"rows": [], "stopped": False}
        limit = s["max"]
        if s["periods"]:
            n = self._ev(s["periods"], values)
            if n is None or not 0 <= n <= MAX_PERIODS or abs(n - round(n)) > 1e-9:
                raise PlanError(f"step {s['name']}: \"periods\" must be a whole number from 0 to {MAX_PERIODS}")
            limit = int(round(n))
        rows, done, stopped = [(0, dict(state))], 0, False
        while True:
            scope = {**values, **state}
            for h, f in s["helpers"].items():                # this period's helpers, from the state before it
                scope[h] = self._ev(f, scope)
            if s["until"]:
                lhs, op, rhs = self._ev(s["until"][0], scope), s["until"][1], self._ev(s["until"][2], scope)
                if {"<": lhs < rhs, "<=": lhs <= rhs, ">": lhs > rhs, ">=": lhs >= rhs}[op]:
                    stopped = True
                    break
            if done >= limit:
                break
            state = {k: self._ev(s["each"][k], scope) if k in s["each"] else v for k, v in state.items()}
            if any(v is None or not math.isfinite(v) for v in state.values()):
                raise PlanError(f"step {s['name']}: the state stopped being a finite number in period {done + 1}")
            done += 1
            rows.append((done, dict(state)))
        if s["until"] and not stopped:
            result = None                                # the condition never came within the limit
        else:
            result = done if s["result"] == "periods" else state[s["result"]]
        return result, {"rows": rows, "stopped": stopped, "limit": limit}

    def _vary(self, s: dict) -> dict:
        rows = []
        for v in s["values"]:
            try:
                values, _ = self.run({s["input"]: v})
                rows.append((v, {o: values[o] for o in s["of"]}))
            except PlanError:
                rows.append((v, {o: None for o in s["of"]}))
        return {"rows": rows}

    def checks(self, skip: frozenset[int] = frozenset()) -> list[dict]:
        """Guard 3: each check (except those a judge set aside) reruns the plan with its inputs and compares. Raises
        CheckFailed on a mismatch, PlanError when a check can't run."""
        done = []
        for j, c in enumerate(self.p["checks"]):
            if j in skip:
                continue
            when = ", ".join(f"{k} = {v:g}" for k, v in c["when"].items())
            tolerance = 1e-6
            try:
                values, details = self.run(c["when"])
                expected = self._ev(c["expect"], values)
                if values[c["of"]] is None and expected is not None and any(v == 0 for v in c["when"].values()):
                    raise PlanError("no result at 0")             # a solve dividing by the rate finds no root at 0
            except PlanError as e:
                if not any(v == 0 for v in c["when"].values()):
                    raise PlanError(f"check with {when} could not run ({e}); choose inputs where the formulas work") from None
                # a formula that divides by a rate can't be evaluated at 0: take the limit there (rate → 0),
                # extrapolated from two small values so that neither precision nor the step size spoils it
                pairs = []
                for h in (LIMIT_STEP, 2 * LIMIT_STEP):
                    try:
                        vals, details = self.run({k: (h if v == 0 else v) for k, v in c["when"].items()})
                        pairs.append((vals[c["of"]], self._ev(c["expect"], vals)))
                    except PlanError as e2:
                        raise PlanError(f"check with {when} could not run ({e2}); choose inputs where the formulas "
                                        "work") from None
                (a1, e1), (a2, e2_) = pairs
                values = {c["of"]: None if a1 is None or a2 is None else 2 * a1 - a2}
                expected = None if e1 is None or e2_ is None else 2 * e1 - e2_
                tolerance = 1e-4
            actual = values[c["of"]]
            same = (actual is None and expected is None) or (
                actual is not None and expected is not None
                and abs(actual - expected) <= tolerance * max(1.0, abs(expected)))
            if not same:
                step = next(s for s in self.p["steps"] if s["name"] == c["of"])
                hint = (f" (the simulation ran {step['max']} {step['period']}s without reaching `{' '.join(step['until'])}`: "
                        "is the stop condition reachable?)" if actual is None and step["kind"] == "simulate" else "")
                if expected is not None and expected < 0 and step["unit"] in ("years", "months"):
                    hint += f"; a negative number of {step['unit']} is impossible, so the check's expect is wrong"
                rows = details.get(c["of"], {}).get("rows") or []
                raise CheckFailed(f"check failed: with {when}, {c['of']} = {_fmt(actual)}{hint} but {c['expect']} = "
                                  f"{_fmt(expected)}; the formula or the check is wrong", j, c, actual, expected,
                                  rows[:4] + rows[-2:] if len(rows) > 6 else rows)
            done.append({**c, "value": actual})
        return done


def run(plan, question: str, known_text: str, skip: frozenset[int] = frozenset(), require_checks: bool = True,
        example: bool = False) -> dict:
    """Validate and execute a plan; `skip`: indexes of checks a judge set aside; `require_checks` False for a plan built
    from sourced equations (the calculator pipeline), whose formulas come from references, not the LLM; `example`: the
    user asked for a worked example, so a plan whose numbers are all samples is answered instead of asking. Returns the
    parsed plan with "values"
    (each step's result), "details" (simulation and vary tables) and "checks" (passed).
    Raises PlanError (fix the plan; CheckFailed when only a check disagrees) or NeedsInput (ask the user)."""
    p = parse(plan)
    check_numbers(p, question, known_text)
    # a 0 marked "user" isn't a number of theirs (check_numbers accepts any 0: "no more money")
    if not example and not any(i["from"] == "user" and i["value"] != 0 for i in p["inputs"].values()):
        raise NeedsInput(p["label"], [i["means"] for i in p["inputs"].values()])
    if require_checks and _needs_checks(p) and not p["checks"]:
        raise PlanError("this plan uses a power, a solve or a simulation: add at least one check (for example with a "
                        "rate of 0 or a time of 0) whose expected value you know")
    ex = _Executor(p)
    values, details = ex.run(top=True)
    check_all_used(p, question, values)
    checks = ex.checks(skip)
    if skip and not checks and require_checks and _needs_checks(p):
        raise PlanError("every check was set aside as wrong, so nothing verifies the plan: add a check you are sure of "
                        "(for example one where nothing happens: no time, no payments, or the whole amount at once)")
    return {**p, "values": values, "details": details, "checks": checks, "example": example}
