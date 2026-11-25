# Tax agent

| | |
|---|---|
| Status | Steps 1–3 of 4 built (2026-11-24): seven tools, picked by the model; every tax figure; the estimate carried across the chat; one question asked when it matters. |
| Code | `tax_node` in [src/workflow/nodes.py](../src/workflow/nodes.py), tools in [src/workflow/tax_tools.py](../src/workflow/tax_tools.py), the income-tax reading and rendering in [src/workflow/tax_calc.py](../src/workflow/tax_calc.py), the maths in [src/core/income_tax.py](../src/core/income_tax.py), the rules in [src/data/tax_rules.yaml](../src/data/tax_rules.yaml) |
| Tests | `tests/test_income_tax.py`, `tests/test_tax_whatif.py`, `tests/test_saved_plan.py` |

## Why it exists

Its pages: `taxes-and-accounts` (300 Wikipedia pages since 2026-11-25, 7,044 chunks; see kb-token-stats-taxes-and-accounts.md) and `retirement` (15).

Before this, the Tax agent was the Q&A agent with "tax" added to its fallback query and a caveat: the same function
(`_kb_answer`), the same 336 pages, no calculation. Tax figures came from the general calculator, which used a flat
sample rate and subtracted property tax in full. A tax expert does five things, and the agent is built around them:

1. **Knows this year's rules**: from data (`tax_rules.yaml`, updated each year from the IRS inflation adjustments), never
   from the model's memory.
2. **Understands the situation**: the user's amounts, filing status, holding period, account type.
3. **Calculates**: in Python, with the working shown.
4. **Explains**: the rule in plain words, then the user's numbers, then the source page.
5. **Knows its limits**: says what it covers (US federal, single or married filing jointly, this year) and what it
   doesn't (state tax, credits, AMT); explains and estimates, never advises.

## Tools

| # | Tool | Does | Built |
|---|---|---|---|
| 1 | `search_tax_pages` | the rule to explain, from the `taxes-and-accounts` and `retirement` pages only | step 1 |
| 2 | `get_tax_rules` | a year's figures from `tax_rules.yaml` | step 1 |
| 3 | `estimate_income_tax` | the step-by-step federal estimate from the user's income and deductions | step 1 (moved from the calculator) |
| 4 | `tax_on_plan` | the saved Goals plan's tax in a brokerage account, a traditional 401(k)/IRA and a Roth | step 1 (moved from the calculator) |
| 5 | `compare_accounts` | Roth vs traditional; what a 401(k)/IRA contribution saves today | step 3 |
| 6 | `marginal_effect` | what an extra amount of income, a sale or a deduction changes | step 3 |
| 7 | `capital_gain` | gain or loss on a sale from cost basis, short vs long term, wash sales | step 3 |

## Flow today

- **Amounts and "how much tax"** (`tax_calc.asks_income_tax`): the router sends it to the Tax agent alone
  (`_with_income_tax`). The LLM sorts each amount into a kind; Python checks every amount is the user's and none is left
  out, and `income_tax.estimate` computes. The answer is nine numbered steps (each: the rule, then the working), what
  was assumed, and the result if an assumption is the other way. It is `verbatim` and `explains_itself`: the
  synthesizer doesn't write over it, only adds "Read more" links to the tax pages. An unusable sort falls back to the
  page search.
- **The saved Goals plan and tax** (the message refers to the plan): three plan-specific searches of the tax pages, the
  plan's paid-in and growth figures for the explanation, and `tax_on_plan`'s table as a `verbatim_tail` after it.
  The calculator is no longer added for these.
- **Anything else about tax**: the tax pages only, with the caveat.

## Step 2: the estimate carried, one question asked

- **Carried.** Each estimate saves a tax profile in the conversation context (`context["tax"]`: year, filing status
  when the user gave it, each figure as `{text, amount, kind, loss}`, the totals and the question it asked). It stays
  until a new estimate replaces it, also through questions about something else; `CTX.describe` lists it in full
  digits so the proofreader can complete a follow-up.
- **Follow-ups.** A message that may change it (`tax_calc.changes_estimate`: an answer button, or a "what if" about
  filing status, holding period, W-2/1099, a bonus, deductions) routes to the Tax agent (`_last_estimate`,
  `_with_income_tax`). `tax_calc.follow_up` gives the LLM the numbered figures and the message (as typed and as
  reworded); it returns the whole new list. Python checks it: a carried figure is kept, or changed by an amount the
  user typed ("$10,000 more" on $200,000); a new figure's amount must be in the message; every amount the user typed
  is used (a total the proofreader summed is allowed, not required). What changed is described from the figures
  (`what_changed`), never the model's summary, and the answer opens with **Updated:** old total → new total.
  Nothing changed → the agent explains from the pages instead.
- **One question.** Every open point (filing status not given, a stock gain's holding period, a side job's W-2/1099) is
  worked out both ways. The one that moves the federal total most is asked when it is worth asking (at least $500 and
  1% of the total), with its two answers as reply buttons; the others stay stated assumptions with their alternative.

## Step 3: what-if tools, picked by the model

- **Picking.** With a tool-calling model, `_pick_tax_tool` binds `tax_whatif.TOOL_SPECS` (estimate_income_tax,
  update_estimate, marginal_effect, compare_accounts, capital_gain, explain_rules) and takes the one call the model
  makes, with the last estimate in the prompt. Python runs it: every amount in its arguments must be the user's (in the
  message, as typed or reworded, or in the last estimate), prices and share counts must appear in the message, and years
  or a return rate are used only when the message gives them (else the Goals plan's horizon or 20 years, and the risk
  profile's return, stated). An argument that isn't the user's raises `Refused` and the agent takes its usual path.
  Without a tool-calling model, or when the model picks nothing, the step-1/2 paths run as before.
- **marginal_effect** (raise, bonus, extra freelance or investment income, a contribution, a gift or other deduction):
  the estimate before and after, step by step, and how much of the extra goes to tax; a deduction notes whether
  itemizing now beats the standard deduction.
- **compare_accounts**: today's tax saved by a traditional contribution (from the user's own estimate, so NIIT and
  bracket edges count), the same take-home cost put in a Roth, growth, and the result at common retirement tax rates;
  the rule: below today's rate traditional wins, above it Roth.
- **capital_gain**: gain or loss from shares × prices or basis and proceeds; short vs long term (said, or from dates;
  else long-term, stated); a loss with the same shares bought back within 30 days is a wash sale (not deducted, added to
  the new basis); the tax on it from the last estimate or the income the message gives, else the rates.
- Routing: a tax question with amounts and a what-if cue (Roth, traditional, 401(k), sold, shares, raise, bonus,
  deduction, contribution) goes to the tax agent alone; `illustrate` skips answers the tax tools worked out.

## Next

4. A tax eval set (about 20 cases with hand-checked answers), run after any prompt or rules change.
