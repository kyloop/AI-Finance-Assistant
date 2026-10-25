# Calculator pipeline: understand, define, find a sourced equation, fill it, compute, quote

Status: adopted. Builds on the plan engine in [calc-plan-design.md](calc-plan-design.md), which still validates and
executes every calculation and still handles questions no single equation answers (simulations).

## Why

With one LLM call designing the whole calculation, the plan, its self-checks and the judge all came from the same
model and made related mistakes: a wrong payment formula, forgotten interest, a check that "fixed" a correct plan into a
wrong one. Every wrong answer came from the LLM *inventing* a model. In this pipeline a standard equation must be found
in a source, found again in an independent source, and quoted; a wrong formula would have to contradict both.

## The seven steps (each LLM step is its own call, visible in Langfuse)

| # | Step | Who | Output |
|---|---|---|---|
| 1 | Understand the question | LLM (`UNDERSTAND_SYSTEM`) | what the user wants, the numbers given and what they mean, conditions (timing, compounding), ambiguities and the reading taken |
| 2 | Define what to calculate | LLM (`DEFINE_SYSTEM`) | the targets in order, each `formula` (a standard finance equation), `arithmetic` (splits, sums, differences of given numbers or earlier targets, with its expression) or `simulation` (period by period, no single equation), with the concept's standard name and search queries |
| 3 | Find the equation | search + LLM | for each `formula` target, below |
| 4 | Prepare the variables | LLM (`VARIABLES_SYSTEM`) | a value for every variable of every equation: a number from the question (`user`), a typical value (`sample`), or derived from them (`r/12`, `12*t`, an earlier target) |
| 5 | Put the values into the equation | Python | `calc_plan.run`: no invented numbers, every number in the question used, the rearranged formula satisfies the sourced equation |
| 6 | Show the result | Python | inputs, equation, working, result |
| 7 | Quote the source | Python | the verbatim quote of each equation with its source (knowledge-base article or web page) and whether two sources agreed |

### Step 3: find the equation, cross-checked

1. Search the knowledge base (Qdrant, Wikipedia articles) and the web (Tavily) with step 2's queries.
2. **3a, read the source as written.** One LLM call per source (`EXTRACT_SYSTEM`) returns a verbatim quote, the
   equation exactly as the source writes it (LaTeX, Greek letters, `×`), every symbol in it with the source's definition,
   and which symbol is the target. Python rejects an extraction whose quote isn't in the source text; a quote stitched
   together from two places is replaced by the equation alone when that is in the source.
3. **3b, put it in the parser's notation** (`translate`). Python rewrites the common notation first (`plain`: `\frac`,
   `r_{f}`, `\beta`/`β` → `beta`, `βi` → `beta_i`, `E(Rm)` → `E_Rm`, `×`/`·`/a spaced `x` → `*`, dashes → `-`,
   `[ ]` → `( )`), names each symbol the same way, and checks the result: it parses, every name in it is one of the
   source's symbols, the target is in it. Only if that fails does an LLM call (`TRANSLATE_SYSTEM`) translate it, with
   Python's reason, one repair round, checked the same way. When the target stands alone on one side, the other side is
   the formula; otherwise step 5 solves the equation numerically. No LLM rearranges equations.
4. An LLM judge (`MATCH_SYSTEM`) gets the question and both equations and decides whether they compute the same thing
   the same way (same compounding, same payment timing; names may differ) **and** whether that is what the question
   asks for (what money is worth in today's dollars is not what goods will cost later). A more general form that
   reduces to the other when its extra terms are zero (WACC with preferred stock) also matches, and the judge says which
   of the two to use for the question. Both → pass, both sources quoted.
5. No match (or one source found nothing): the LLM writes better queries from what went wrong (`REFINE_SYSTEM`), both
   sources are searched again, extracted and judged again. Match → pass. Still disagreeing → ask the user rather than
   guess. When the judge says one of the two doesn't compute the target at all (`misread`: a present-value formula read
   as a future value), that one is dropped and the other counts as one source, so a misreading doesn't make the user
   choose between a right and a wrong equation. Only one source has it (or web search isn't configured) → use it, quoted, marked "one source, not
   cross-checked".

### Worked examples (sample numbers only)

"Show me an example of how to calculate WACC" or "how is present value calculated?" asks to see a calculation, not to
calculate the user's own figures. The router sends such requests to `calc` (rule 8 and an example in its prompt). The
calculator recognises them from the wording (`wants_example`: "an example", "how do you calculate", "illustrate",
"sample numbers"…) or from step 1's `"example": true`; then step 4 (or the plan path) picks typical sample numbers for
everything, a plan with no user number is answered instead of asking, and the answer is titled "Worked example", every
value marked (sample). Without such a request, a plan with no user number still asks ("How much will my savings
grow?"). Plain concept questions ("what is WACC?") stay with Q&A and get no calculation; the follow-up suggestions
offer one with concrete numbers. Step 2 never lists the inputs as targets: Python drops "given"/"input" entries, an
arithmetic target that only names a value (`beta = given_beta`), and a target that is one of the numbers step 1 read
from the message (`initial investment` when $5,000 is "the initial investment amount") unless step 1 said to find it.

### Questions without a single equation

When step 2 says a target is a `simulation` (a payment that's a share of the balance, withdrawals rising with
inflation), the whole question goes to the plan path of [calc-plan-design.md](calc-plan-design.md): the LLM designs a
period-by-period model, guarded by its self-checks and the judge, and the answer says it is Finnie's own model, not a
sourced equation. If steps 1–2 fail (no usable reply), the plan path is the fallback too. When step 4 can't fill an
equation step 3 found, the plan path gets those equations and must build on them; the answer quotes them.

### When nothing computes: confirm with the user

If the plan path fails too, the calculator doesn't send a fixed request for numbers. One LLM call (`CONFIRM_SYSTEM`)
gets the message, step 1's understanding and why it failed, and writes what it thinks the user wants (with their
numbers) and what is missing or unclear, plus 2–3 complete versions of the question the user can click (with a typical
value for what's missing, e.g. a 3% risk-free rate). The verifier keeps these choices. Without a usable reply, Python
restates step 1's understanding and asks whether it's right; without that, it asks what to work out. Basic mode (no
LLM) keeps a fixed, topic-neutral request.

### Python's checks on the LLM steps

- An extraction's quote must appear in its source (whitespace and LaTeX spacing ignored), and every constant in its
  equation other than 0, 1, 2, 12, 52, 100, 365 must appear in the quote (the 72 of the Rule of 72). Constants of a
  sourced equation are then allowed in its formula; the plan path's ban on constants still applies to the LLM's own
  formulas.
- The rearranged formula must satisfy the sourced equation (`satisfies`, checked with the user's numbers).
- Step 4 sees each variable as the source defines it (with the quote), so a nominal annual rate stays annual and a
  per-period rate is divided by the periods. A rate may be a decimal (`rate`, 0.07) or, where the source's formula
  takes a percentage such as the Rule of 72, a `percent` (7); a `percent` added to 1 (`1 + r`), or added to or
  subtracted from a `rate` (`rm - rf` with 8 and 0.03), is rejected as a unit error. A ratio such as a beta is a
  `number`; a `rate` above 1 is rejected with that hint.
- LLM replies are parsed by `first_json` (`src/workflow/jsonreply.py`): LaTeX backslashes copied from a source (`\mu`,
  `\beta`) are kept as written instead of breaking the JSON or turning into control characters, an object closed early
  (`{"inputs": {...}},{"derived": ...}`) is rejoined, and an object nested in a reply that still isn't valid is never
  returned as if it were the reply.
- Step 4: every variable of every equation gets a value; `user` values are in the question; every number in the
  question is used or reproduced (guards 1 and 2 of the plan engine). A rejected step 4 is repaired once with the error;
  if it still can't be filled (an IRR stated as a sum over cash flows), the question goes to the plan path.
- Variables with the same name in two equations are renamed (`i`, `i_2`) before step 4.
- Step 4 giving the user's number under its own name (`r_year`) and no value for the equation's (`r`): Python pairs
  them when exactly one unused input is of the same kind (a rate for a rate, years for periods), with no repair round.

### Replies to the calculator's question

The proofreader (`PROOFREAD_SYSTEM` in `nodes.py`) treats a reply to the assistant's last message ("yes, confirm",
"no, 6%", a value it asked for) as a follow-up and rewrites it as the complete question the assistant proposed, with the
value given ("How much does $30,000 grow at 6% a year over 10 years?"), never as a question about the assumption. The
calculator then gets the conversation, and the question stands on its own.

### Numbers the calculation doesn't need

Step 4 may list a number from the question in `ignored` with why (the terms of a loan the question only mentions as the
alternative); the answer shows them under "Not used". A number that is neither used nor ignored with a reason still
rejects the plan, even after the repair round: decided to keep this strict, so a dropped condition (a 3% inflation
adjustment) blocks the answer instead of only being flagged in it. The cost is that the calculator sometimes asks
instead of answering when step 4 forgets to list a background number (1 of 3 runs of the car-savings question, c22).

## Results

[calc-eval.md](calc-eval.md), gpt-4o, 21 questions. The first run of the pipeline passed 17 with no wrong answers; the
second passed 18 but gave three wrong answers on the sourced path, each from a step that the cross-check doesn't
cover: an equation both sources agreed on but that computed a different quantity (future cost instead of today's
value), a source formula taking a percentage given a decimal (Rule of 72), a nominal annual rate given per month.
Hence the judge checking the fit to the question, step 4 seeing the source's definitions, the `percent` unit and its
`1 + r` rule. Latest run: 19 of 21, no wrong answers (the two misses asked the user). 11 questions took the sourced
path (9 cross-checked, 2 from one source), 8 the plan path, 1 was plain arithmetic, 1 asked for numbers.

Known limits: matching two sources shows they agree with each other, not that the variables were filled correctly; the
guards on step 4 catch unit errors they know about (`1 + r` with a percentage) and numbers that don't belong, not every
mismatch of meaning. Answers take 6–10 LLM calls on the sourced path.

2026-10-22, after step 3a/3b (equations read as the source writes them), the JSON repairs, the unit guards and the
confirmation (26 questions, three CAPM/growth questions added): gpt-4o 24/26 (the misses: one asked; one wrong answer
on c21, a source's `P` meaning the payment filled with the loan amount, the meaning mismatch below, not seen on a
second run); gpt-4o-mini, the configured model, 17/26 with no wrong answers, every miss asked the user
([calc-eval.md](calc-eval.md)). An earlier gpt-4o-mini run gave three wrong answers that led to the guards on a lone
`0` "from the user" (c17), on a result whose unit doesn't match its inputs (920% for 9.2%), and to letting the plan
path leave out a sourced equation that doesn't fit the question (c13).

Earlier run with worked examples (23 questions): 20 passed, no wrong answers. The three misses asked: two background-
number cases on the strict guard, and one where the sources really disagree (compound annual return vs simple return;
the judge's reasoning said which fits, but by design disagreeing sources ask the user).

## Cost

A one-formula question: 5 LLM calls (understand, define, 2 extractions, judge) + 1 (variables), 2 searches; a refine
round adds 4 calls and 2 searches. Simulations: understand + define + the plan path.

## Code

| Piece | Where |
|---|---|
| Steps 1–4, cross-check, plan assembly | `src/workflow/calc_pipeline.py` |
| Steps 5–6 (validate, execute, render), quotes | `src/core/calc_plan.py`, `calc.plan_text` in `src/workflow/calc.py` |
| Node | `calc_node` in `src/workflow/nodes.py` |
| Tests (scripted LLM, fake KB and web) | `tests/test_calc_pipeline.py` |
| Eval | `python -m scripts.eval_calc` → [calc-eval.md](calc-eval.md) |
