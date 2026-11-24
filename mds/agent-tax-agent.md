# Tax agent

| | |
|---|---|
| Status | Step 1 of 4 built (2026-11-24): the agent has its first four tools and owns every tax figure. |
| Code | `tax_node` in [src/workflow/nodes.py](../src/workflow/nodes.py), tools in [src/workflow/tax_tools.py](../src/workflow/tax_tools.py), the income-tax reading and rendering in [src/workflow/tax_calc.py](../src/workflow/tax_calc.py), the maths in [src/core/income_tax.py](../src/core/income_tax.py), the rules in [src/data/tax_rules.yaml](../src/data/tax_rules.yaml) |
| Tests | `tests/test_income_tax.py`, `tests/test_saved_plan.py` |

## Why it exists

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
| 5 | `compare_accounts` | Roth vs traditional; a 401(k) contribution vs salary | step 3 |
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

## Next

2. A tax profile kept in the conversation (filing status, income, account types), and asking one short question when
   a missing fact changes the answer a lot.
3. Tools 5–7, and the LLM picking tools like the Market agent (`market_tools.py`).
4. A tax eval set (about 20 cases with hand-checked answers), run after any prompt or rules change.
