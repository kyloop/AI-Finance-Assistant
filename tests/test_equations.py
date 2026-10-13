"""The Calculator's equation solver (src/core/equations.py): reading Wolfram|Alpha notation, safe evaluation, picking a
formula that satisfies the equation, and the numeric fallback."""
import pytest

from src.core import equations as E


@pytest.mark.parametrize("wolfram,python", [
    ("10000 (1 + r)^5", "10000 * ( 1 + r ) ** 5"),
    ("(F/P)^(1/n) - 1", "( F / P ) ** ( 1 / n ) - 1"),
    ("log(F/P)/log(r + 1)", "log ( F / P ) / log ( r + 1 )"),
    ("2 π r", "2 * pi * r"),
    ("(a)(b)", "( a ) * ( b )"),
])
def test_wolfram_notation_becomes_python(wolfram, python):
    assert E.to_python(wolfram) == python


def test_evaluate_uses_the_values_and_natural_log():
    assert E.evaluate("(F/P)^(1/n) - 1", {"F": 15000, "P": 10000, "n": 5}) == pytest.approx(0.0844717712)
    assert E.evaluate("log(e)", {}) == pytest.approx(1.0)
    assert E.evaluate("e + 1", {"e": 2}) == 3.0                             # a variable named e wins over the constant


@pytest.mark.parametrize("expr", ["__import__('os')", "x.real", "[1, 2]", "(-8)^(1/3)", "1/0", "y + 1", "2 ** 3 if 1 else 0"])
def test_evaluate_refuses_anything_but_real_arithmetic(expr):
    with pytest.raises(E.EquationError):
        E.evaluate(expr, {"x": 1})


def test_formulas_skips_conditions_and_complex_branches():
    sections = {"Results": "n = (log(F/P) + 2 i π c_1)/log(r + 1) and P!=0 and c_1 element Z",
                "Solution over the reals": "n>0 and F = 0 and r = -1\n\nn = log(F/P)/log(r + 1) and log(r + 1)!=0 and F>0"}
    assert E.formulas(sections, "n") == ["log(F/P)/log(r + 1)"]


def test_solve_uses_a_formula_only_if_it_satisfies_the_equation():
    v = {"P": 10000, "F": 15000, "n": 5}
    good = E.solve("P*(1+r)^n = F", "r", v, ["F/P - 1", "(F/P)^(1/n) - 1"])
    assert good == {"value": pytest.approx(0.0844717712), "formula": "(F/P)^(1/n) - 1"}
    numeric = E.solve("P*(1+r)^n = F", "r", v, ["F/P - 1"])
    assert numeric["formula"] is None and numeric["value"] == pytest.approx(0.0844717712)


def test_solve_numeric_finds_the_irr_and_the_years():
    irr = E.solve("a + b/(1+r) + c/(1+r)^2 + d/(1+r)^3 = 0", "r", {"a": -10000, "b": 3000, "c": 4000, "d": 5000})
    assert irr["value"] == pytest.approx(0.08896339, abs=1e-7)
    years = E.solve("P*(1+r)^n = F", "n", {"P": 10000, "F": 15000, "r": 0.06})
    assert years["value"] == pytest.approx(6.958516, abs=1e-5)


def test_solve_prefers_a_sensible_root():
    assert E.solve("(x - 3)*(x + 5) = 0", "x", {})["value"] == pytest.approx(3)    # above -1 before smaller in size


def test_solve_reports_missing_values_and_no_solution():
    with pytest.raises(E.EquationError, match="no value for F, n"):
        E.solve("P*(1+r)^n = F", "r", {"P": 1})
    with pytest.raises(E.EquationError, match="no real solution"):
        E.solve("x^2 + 1 = 0", "x", {})
