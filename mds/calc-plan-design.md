# Calculator: the LLM designs the calculation, Python executes it

Status: adopted (replaces the calculator's fixed function menu, arithmetic route, steps route, named-formula lookup and
equation route).

## Why

The Calculator used to give the LLM a menu: nine library functions (`future_value`, `loan_payment`, ...), plus special
routes for arithmetic, multi-step requests, Wolfram|Alpha formula names and one-off equations, plus a `"missing"` escape.
Each new kind of question needed another route, and the prompt had grown to ~6,400 characters of special cases. The
failures seen in Langfuse all came from the menu:

| Question | What happened |
|---|---|
| "$1,000 in 5 stocks, how much in each?" | No function divides; the LLM picked `percent_change` and asked for a rate |
| "$10,000 split 50/30/20, how much in each?" | Same; asked for "the interest rate" |
| "Split $600/month into 3 accounts, and the growth at x%?" | One calculation per question: the growth part was dropped |
| "$1M, withdraw $45k rising 3%/yr for inflation" | Matched to a level annuity: the 3% inflation was silently ignored, the missing return filled with Wolfram's 8% example |

## The design

The LLM writes a **plan**: the inputs (each with where it came from), the formulas, equations or period-by-period rules
that compute the answer, and test cases the formulas must pass. It never writes a result. Python validates the plan,
executes it and renders the answer with a generic layout. There is no library of finance functions at runtime;
`src/core/calculators.py` stays only for basic mode (no LLM, keyword extraction), the `illustrate` node's worked
examples, and as the reference answers of the eval set.

```
question ─► LLM writes plan (JSON) ─► Python validates ─┬─► Python executes ─► Python renders ─► answer (verbatim)
                 ▲                                       │
                 └──── one repair round, with the error ─┘  (still invalid → ask the user for the numbers)
```

### Plan schema

```json
{"label": "how long the savings last",
 "inputs": {"B": {"value": 1000000, "from": "user",   "means": "savings at retirement", "unit": "money"},
            "W": {"value": 45000,   "from": "user",   "means": "first-year withdrawal", "unit": "money"},
            "g": {"value": 0.03,    "from": "user",   "means": "yearly inflation",      "unit": "rate"},
            "r": {"value": 0.05,    "from": "sample", "means": "yearly return",         "unit": "rate"}},
 "steps": [{"name": "years", "label": "years of full withdrawals", "unit": "years",
            "simulate": {"start": {"balance": "B", "withdrawal": "W"},
                         "each": {"balance": "(balance - withdrawal)*(1 + r)", "withdrawal": "withdrawal*(1 + g)"},
                         "until": "balance < withdrawal", "max": 100}},
           {"name": "by_return", "label": "depending on the return",
            "vary": {"input": "r", "values": [0.03, 0.04, 0.05, 0.06, 0.07, 0.08]}, "of": ["years"]}],
 "checks": [{"when": {"r": 0, "g": 0}, "of": "years", "expect": "floor(B/W)"}],
 "assumptions": ["withdrawals are taken at the start of each year"],
 "ignored": [{"number": 4.5, "why": "the same as 45,000 ÷ 1,000,000"}]}
```

| Block | Fields | Python does |
|---|---|---|
| input | `value`, `from` (`user` / `sample`), `means`, `unit` (`money`, `rate` as a decimal, `years`, `months`, `number`) | checks a `user` value is in the question or conversation |
| `expr` step | a formula over inputs and earlier steps; optional `satisfies`: the equation it was rearranged from (`P*(1+r)^t = F` for `P = F/(1+r)^t`) | evaluates it (`src/core/equations.py`: numbers, names, + − × ÷ ^, `log` `exp` `sqrt` `abs` `floor` `ceil` `min` `max`); with `satisfies`, puts the result back into the equation and rejects the plan if the two sides differ |
| `solve` step | an equation and `for` (the unknown), only when the unknown can't be isolated (an IRR over several cash flows, a rate inside a loan formula) | solves it numerically (`equations.solve`) |
| `simulate` step | `start`, `each` (simultaneous updates per period; a name in `each` that isn't in `start` is a per-period helper, computed first in the order given, before the stop condition), then `until` (a condition checked before each period, max `max` periods) or `periods` (a fixed count), `result` (`periods` or a state variable), `period` (`year` / `month`) | runs the loop, keeps the per-period table |
| `vary` step | `input`, `values` or `from`/`to`/`step`, `of` (earlier steps) | reruns the plan with that input changed, one row per value |
| `checks` | `when` (input overrides), `of` (a step), `expect` (an expression) | reruns the plan with the overrides and compares |
| `assumptions`, `ignored` | text; numbers in the question deliberately not used, with why | shown in the answer |

### The guards

1. **No invented numbers.** A `user` input must appear in the question or the conversation (a `rate` may be written as
   its percentage: 0.08 ↔ "8%"; money paid out may be negative, -10000 for "invest $10,000"; 1, 2, 4, 12, 52 and 365 are
   accepted for counts such as "compounded monthly"). Formulas may contain only 0, 1, 2, 12, 52, 100 and 365, plus whole
   numbers up to 12 as exponents (year 3 of a cash flow); every other number must be an input, so an assumption such as
   a $10 minimum payment shows up as a (sample) input instead of hiding in a formula.
2. **Every number in the question is used.** Each number in the current message (with "$1 million", "50k" scaled; account
   and index names such as 401(k), 403(b), 529, S&P 500 skipped) must be a `user` input that a step uses, a structural
   constant in a formula, or listed in `ignored` with a reason. This catches a dropped condition (the 3% inflation).
3. **Self-checks.** A plan with a `solve`, a `simulate`, or a formula with `^`, `exp` or `log` must include at least one
   check; Python reruns the plan with the check's inputs and the result must match `expect` (relative tolerance 1e-6).
   A wrong formula usually fails one of: rate 0, time 0, one period. A check at 0 that can't be evaluated (a loan or
   annuity formula divides by the rate) is evaluated as the limit, with the zero inputs at 1e-10 and a tolerance of 1e-4.
4. **The formula is shown.** Every answer shows the inputs (marked `(sample)` when not the user's), the formula or rules,
   the working with the numbers substituted, the checks that passed, the assumptions and any ignored numbers.
5. **A judge for disagreements.** When a plan runs but one of its own checks disagrees, either may be wrong. A separate
   LLM call gets the question, the plan, the check, both values (and the simulation's first and last periods) and works
   the check's case out by hand: a wrong check is set aside and shown in the answer with the judge's reasoning, a wrong
   plan goes to the repair round with that reasoning, "unsure" goes to the repair round as is. At most 2 judge calls per
   question, and at least one check must still pass when a plan needs checks.
6. **One repair round.** A plan that fails validation or execution goes back to the LLM once with the exact error (first
   in the prompt, then the rejected plan, then the question). If the LLM sends the identical plan back, it is asked once
   more, told so. If the repaired plan fails too, the agent asks the user for the numbers (`need_info`) and the trace
   records both errors.
7. **Eval set.** `tests/data/calc_eval.yaml` holds questions with reference answers (computed with `calculators.py` or by
   hand); `python -m scripts.eval_calc` runs them against the live LLM and writes [calc-eval.md](calc-eval.md).

### Samples and asking

Option B from the review: a number the user didn't give is filled with a typical value marked `(sample)`, and the
answer invites the user to send their own. If **no** input comes from the user (the whole answer would be illustrative),
the agent asks instead, listing what it needs from the plan's input descriptions. There is no `"missing"` reply: the
LLM always writes a plan, so it can no longer ask for a number the question doesn't need.

### Limits

8 steps, 20 inputs (an object, or a list of inputs with "name"), 6 checks, 200 characters per formula, 1,200 periods per simulation (100 years monthly), 50 rows per
`vary`, names `[A-Za-z][A-Za-z0-9_]*` that are not function names.

## What it costs

- Nothing guarantees the LLM chose the right model (yearly vs monthly compounding, withdrawals at the start vs the end
  of the year). Guards 2 to 4 make mistakes rarer and visible; the eval set measures how often they happen.
- Answers use one generic layout instead of hand-written wording per calculation type.
- Formula design depends on the model (gpt-4o in `config.yaml`); rerun the eval set when changing it.
- No Wolfram|Alpha. It used to supply closed forms for `solve` steps, but it was only sent the equation with letters
  (`solve P*(1+r)^t = F for P`), returned only the rearranged formula, never knew what was being calculated, and could
  not change the result (Python verified its formula against the equation, and solves numerically without it). The LLM
  now rearranges such equations itself and states the original as `satisfies`, which Python checks the same way; `solve`
  is left for unknowns no formula isolates, solved numerically. `src/core/wolfram.py` is no longer called by the app.

## Code

| Piece | Where |
|---|---|
| Plan validation, execution, guards | `src/core/calc_plan.py` |
| Prompt (`PLAN_SYSTEM`), repair prompt, renderer (`plan_text`) | `src/workflow/calc.py` |
| Node: plan → repair → execute → render, or ask | `calc_node` in `src/workflow/nodes.py` |
| Tests (offline, scripted plans) | `tests/test_calc_plan.py` |
| Eval set and runner | `tests/data/calc_eval.yaml`, `scripts/eval_calc.py` → [calc-eval.md](calc-eval.md) |

## Results so far

[calc-eval.md](calc-eval.md): 20 of 20 questions on gpt-4o, 5 of them after the repair round. How it got there:

- The first run of an early version passed 14 of 17. Every failure was a guard detail, fixed in the engine: a check at a
  rate of 0 for a formula that divides by the rate (now the limit), money paid out written as a negative number, small
  exponents (year 3), inputs written as a list, a solve with no root at 0, a stop condition using a per-period helper.
- "A $5,000 balance at 20% APR, paying 3% of the balance each month" then failed every time: the plan was right but the
  LLM's own check assumed a fixed payment, and the repair round kept the check. Prompt wording about writing checks
  moved failures around (it broke a passing question) and was reverted; the judge (guard 5) fixed it.
- The judge exposed a loophole: a $10 minimum payment written into a formula passed as a "structural" small number.
  Small whole numbers are now allowed only as exponents, so the assumption has to be a visible (sample) input.

Known limits: the judge is the same model and can be wrong (in one run it called a correct loan formula wrong because
its check at 0 years expected a payment of 0; the repair round still produced a correct plan). An underspecified question
gets different reasonable answers depending on the assumption the plan makes (stop below $1: 51 years; a $10 minimum
payment: 21 years), which the answer states.

Not changed: basic mode (keywords → `calculators.py`), the `illustrate` node (worked examples on Q&A answers), and the Q&A
verifier being literal about unusual terms ("Retirement Income Sustainability"), which is a separate issue.
