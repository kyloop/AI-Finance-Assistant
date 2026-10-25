"""Equations for the Calculator's fallback (calculations none of calculators.py covers): read a formula written in
Wolfram|Alpha's plain-text notation, put the user's numbers into it, and solve an equation for its unknown. All arithmetic
is done here in Python; Wolfram|Alpha only supplies the symbolic formula, and every formula is checked against the
original equation before its value is used."""
from __future__ import annotations

import ast
import math
import operator
import re


class EquationError(ValueError):
    """An expression we can't read or evaluate to a real number, or an equation with no real solution."""


FUNCS = {"log": math.log, "ln": math.log, "exp": math.exp, "sqrt": math.sqrt, "abs": abs,   # Wolfram's log is natural
         "floor": math.floor, "ceil": math.ceil}
FUNCS2 = {"min": min, "max": max}                # two arguments
CONSTS = {"pi": math.pi, "e": math.e}            # a variable of the same name in the values wins
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d*)?|\.\d+)|([A-Za-zπ][A-Za-z0-9_]*)|([-+*/^(),]))")


def _pow(a: float, b: float) -> float:
    r = a ** b
    if isinstance(r, complex):                   # e.g. (-8)^(1/3): not a real number here
        raise EquationError("not a real number")
    return r


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: _pow}


def to_python(expr: str) -> str:
    """Wolfram notation as Python syntax: ^ for powers, implicit multiplication ("10000 (1 + r)^5", "2 r"), π."""
    expr = expr.replace("−", "-").replace("×", "*").replace("·", "*").replace("**", "^").strip()
    out, pos, prev = [], 0, "op"                 # prev: the kind of the last token (num, name, func, ")" or op)
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m:
            raise EquationError(f"can't read {expr[pos:pos + 12]!r}")
        pos = m.end()
        num, name, op = m.groups()
        if (num or name or op == "(") and prev in ("num", "name", ")"):
            out.append("*")
        if num:
            out.append(num)
            prev = "num"
        elif name:
            out.append("pi" if name == "π" else name)
            prev = "func" if name in FUNCS or name in FUNCS2 else "name"
        else:
            out.append("**" if op == "^" else op)
            prev = ")" if op == ")" else "op"
    return " ".join(out)


def compile_expr(expr: str) -> ast.Expression:
    try:
        return ast.parse(to_python(expr), mode="eval")
    except SyntaxError as e:
        raise EquationError(f"can't read {expr!r}") from e


def evaluate(tree: ast.Expression | str, values: dict[str, float]) -> float:
    """The real value of an expression (a compiled tree or Wolfram-notation text) with the given variable values. Only
    numbers, the variables, + - * / ^ and FUNCS are allowed."""
    if isinstance(tree, str):
        tree = compile_expr(tree)

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id in values:
                return float(values[n.id])
            if n.id in CONSTS:
                return CONSTS[n.id]
            raise EquationError(f"no value for {n.id}")
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -ev(n.operand) if isinstance(n.op, ast.USub) else ev(n.operand)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and len(n.args) == 1
                and not n.keywords):
            return float(FUNCS[n.func.id](ev(n.args[0])))
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS2 and len(n.args) == 2
                and not n.keywords):
            return float(FUNCS2[n.func.id](ev(n.args[0]), ev(n.args[1])))
        raise EquationError("unsupported expression")

    try:
        r = ev(tree)
    except (ZeroDivisionError, OverflowError, ValueError, TypeError) as e:
        raise EquationError(str(e) or type(e).__name__) from e
    if not math.isfinite(r):
        raise EquationError("not a finite number")
    return r


def split_equation(equation: str) -> tuple[ast.Expression, ast.Expression]:
    sides = equation.split("=")
    if len(sides) != 2:
        raise EquationError("an equation needs exactly one '='")
    return compile_expr(sides[0]), compile_expr(sides[1])


SOLUTION_SECTIONS = ("Solution over the reals", "Real solution", "Real solutions", "Solution", "Solutions", "Result", "Results")
_NOT_REAL = re.compile(r"\bi\b|c_\d|element|∈|Z\b")


def formulas(sections: dict[str, str], unknown: str) -> list[str]:
    """The formulas for `unknown` in a Wolfram|Alpha solve result ("r = (F/P)^(1/n) - 1"), real-valued ones first. Conditions
    joined with "and" are dropped (each formula is checked against the equation anyway), complex branches skipped."""
    found = []
    for key in SOLUTION_SECTIONS:
        for line in (sections.get(key) or "").splitlines():
            for piece in re.split(r"\s+and\s+", line):
                m = re.fullmatch(rf"\s*{re.escape(unknown)}\s*=\s*(.+?)\s*", piece)
                if m and not _NOT_REAL.search(m[1]) and m[1] not in found:
                    found.append(m[1])
    return found


def variables(equation: str) -> set[str]:
    """The variable names in an equation (or expression), without functions; constants count if used as variables."""
    names = set()
    for side in equation.split("="):
        names |= {n.id for n in ast.walk(compile_expr(side)) if isinstance(n, ast.Name)}
    return names - set(FUNCS) - set(FUNCS2) - {"pi"}


def _residual(equation: str, unknown: str, values: dict[str, float]):
    lhs, rhs = split_equation(equation)
    return lambda x: evaluate(lhs, {**values, unknown: x}) - evaluate(rhs, {**values, unknown: x})


def _tolerance(values: dict[str, float]) -> float:
    return 1e-7 * (1 + max((abs(v) for v in values.values()), default=0))


def _preferred(roots: list[float]) -> float:
    """Of several real solutions, the one a finance question means: above -1 (a rate above -100%, a positive time),
    then the smallest in size."""
    return min(roots, key=lambda x: (x <= -1, abs(x)))


def solve_numeric(equation: str, unknown: str, values: dict[str, float]) -> float:
    """A real root of the equation by scanning for a sign change from -1e9 to 1e9 and bisecting it."""
    f, tol = _residual(equation, unknown, values), _tolerance(values)
    grid = sorted({0.0} | {s * 10 ** (k / 100) for k in range(-600, 901) for s in (1.0, -1.0)})
    points = []
    for x in grid:
        try:
            points.append((x, f(x)))
        except EquationError:
            points.append((x, None))
    roots = []
    for (a, fa), (b, fb) in zip(points, points[1:]):
        if fa is None or fb is None:
            continue
        if fa == 0:
            roots.append(a)
            continue
        if (fa < 0) == (fb < 0):
            continue
        try:
            for _ in range(200):
                mid = (a + b) / 2
                fm = f(mid)
                if (fm < 0) == (fa < 0):
                    a, fa = mid, fm
                else:
                    b = mid
                if b - a <= 1e-13 * max(1.0, abs(a)):
                    break
            x = (a + b) / 2
            if abs(f(x)) <= tol:                 # a sign change across a pole isn't a root
                roots.append(x)
        except EquationError:                    # hit a point where the equation is undefined: not a root here
            continue
    if not roots:
        raise EquationError("no real solution found")
    return _preferred(roots)


def solve(equation: str, unknown: str, values: dict[str, float], candidates: list[str] = ()) -> dict:
    """Solve `equation` for `unknown`: each candidate formula (from Wolfram|Alpha) is evaluated with the values and kept
    only if it satisfies the equation; without one that does, the equation is solved numerically.
    Returns {"value", "formula"} (formula None when solved numerically). Raises EquationError."""
    missing = sorted(variables(equation) - set(values) - {unknown})
    if missing:
        raise EquationError(f"no value for {', '.join(missing)}")
    f, tol = _residual(equation, unknown, values), _tolerance(values)
    good = []
    for formula in candidates:
        try:
            x = evaluate(formula, values)
            if abs(f(x)) <= tol:
                good.append((x, formula))
        except EquationError:
            continue
    if good:
        x = _preferred([x for x, _ in good])
        return {"value": x, "formula": next(fm for v, fm in good if v == x)}
    return {"value": solve_numeric(equation, unknown, values), "formula": None}
