# Tax agent

| | |
|---|---|
| Status | Steps 1–3 of 4 built (2026-11-24): seven tools, picked by the model; every tax figure; the estimate carried across the chat; one question asked when it matters. |
| Code | `tax_node` in [src/workflow/nodes.py](../src/workflow/nodes.py), tools in [src/workflow/tax_tools.py](../src/workflow/tax_tools.py), the income-tax reading and rendering in [src/workflow/tax_calc.py](../src/workflow/tax_calc.py), the maths in [src/core/income_tax.py](../src/core/income_tax.py), the rules in [src/data/tax_rules.yaml](../src/data/tax_rules.yaml) |
| Tests | `tests/test_income_tax.py`, `tests/test_tax_whatif.py`, `tests/test_saved_plan.py` |

## Why it exists

Its pages: `tax-notes` (9 notes of our own, from IRS pages), `taxes-and-accounts` (338 Wikipedia pages, 6,997 chunks, US sections only; see kb-token-stats-taxes-and-accounts.md) and `retirement` (15). The agent covers US federal tax only.

Before this, the Tax agent was the Q&A agent with "tax" added to its fallback query and a caveat: the same function
(`_kb_answer`), the same 336 pages, no calculation. Tax figures came from the general calculator, which used a flat
sample rate and subtracted property tax in full. A tax expert does five things, and the agent is built around them:

1. **Knows this year's rules**: from data (`tax_rules.yaml`, updated each year from the IRS inflation adjustments), never
   from the model's memory.
2. **Understands the situation**: the user's amounts, filing status, holding period, account type.
3. **Calculates**: in Python, with the working shown.
4. **Explains**: the rule in plain words, then the user's numbers, then the source page.
5. **Knows its limits**: says what it covers (US federal, all four filing statuses, 2025 and 2026) and what it
   doesn't (state tax, the AMT, less common credits); explains and estimates, never advises.

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

## Credits, new deductions, all filing statuses

`src/core/income_tax.py` now covers single, married filing jointly, married filing separately and head of household
(brackets, standard deduction, capital-gains bands, SALT cap, NIIT and additional-Medicare lines for each, in
`tax_rules.yaml`), the extra standard deduction for 65+/blind, the One Big Beautiful Bill Act deductions (seniors $6,000
each, tips, the overtime premium, car-loan interest; each capped and phased out; `obbba_deductions`) and the common credits
(`credits`): child tax credit and credit for other dependents ($2,200 / $500, reduced $50 per $1,000 over $200k/$400k, refundable
up to $1,700 a child at 15% of earnings over $2,500), earned income credit (2026 table), child and dependent care credit
(50% falling to 35%, then to 20%, as amended in 2025), American Opportunity (40% refundable) and Lifetime Learning credits.
Nonrefundable credits come off the income tax before NIIT; refundable ones can make the result negative (a refund beyond
withholding). The sorter reads the household (children under 17, other dependents, people 65+, students), each count kept
only when the message has a word for it (`household_of`); tips and overtime are pay plus a deduction, not counted twice
when "including"; an only job is wages; an unmarried parent is asked about head of household. Left out: the saver's credit
(2026 limits not confirmed), the earned income credit's investment-income test, the AMT, state tax.

## Rental property (Schedule E)

Added 2026-11-25 after a rental-owner scenario ("David earns $120,000 ... rental income $30,000, management fees,
repairs, property taxes, mortgage interest, depreciation ... what is his net rental income?") went to the calculator,
which couldn't place the figures. Now:

- **Sorting.** Two kinds: `rental_income` (rent received) and `rental_expense` (any cost of the rental: fees, repairs,
  insurance, utilities, its property tax and mortgage interest, depreciation). `property_tax` and `mortgage_interest`
  are for the home the user lives in.
- **Maths** (`income_tax.rental`). Net = rent − expenses, added to income and to net investment income (NIIT). The
  rental's property tax is a rental expense, so the SALT cap doesn't touch it. A loss is passive: up to $25,000 offsets
  other income with active participation, reduced by half of modified AGI over $100,000 (gone at $150,000; none married
  filing separately, assuming the couple lived together); the rest carries forward (`rental_loss_allowance` in the rules).
  Left out: real-estate professionals, depreciation recapture on a sale, personal-use and short-rental rules (the
  `how-rental-income-is-taxed` note explains them).
- **Answer.** The estimate opens with "Work out the rental property's profit" (each expense in the user's words, the
  net in bold); explanations after it ("which rental expenses are deductible?") add the user's own rental lines, and a
  question about a gain the estimate holds as short-term says it is taxed as ordinary income (`estimate_facts`).
- **Routing.** A message laying out a tax situation (three or more amounts, income, and tax words or a rental:
  `tax_calc.is_scenario`) goes to the tax agent even when the router LLM picks the calculator; the router prompt now says
  the tax agent works out anyone's own taxes from their figures.
- **Test.** `d21` in `tests/data/tax_eval.yaml` (David's three questions).

## This year's figures in explanations

`tax_tools.current_figures` picks the current-year figures a question touches from `tax_rules.yaml` (`limits` and the
tax tables: standard deduction, brackets, capital-gains bands, SALT cap, child and earned income credits, the 2025-law
deductions, 401(k)/403(b)/457/TSP and IRA limits and catch-ups, Roth income ranges, HSA, gift and estate exemptions, the
home-sale exclusion, Social Security benefit thresholds, RMD age) by keyword, and the tax agent puts them ahead of the
pages; the synthesizer is told to prefer "Current <year> figures" over older amounts in the sources. Questions about a tax
rule go to the tax agent rather than Q&A (`_tax_to_tax_agent`). An estimate's "Read more" links are the pages for what it
used (`tax_calc.topics_of` → `_named_pages`), and tuition paid for a son or daughter adds the "is your student your
dependent?" alternative ($500 credit).

## Figures given one message at a time

A message that states one of the user's own figures, with or without a question (`tax_calc.states_tax_figure`: first
person, an amount, an income or deduction word; not a price, news, loan or savings question), goes to the tax agent
(`_with_income_tax`). The first one starts an estimate (`answer`); a deduction with no income yet is kept and the income
asked for (`noted`); each later one is added by the follow-up path and the total recalculated ("**Updated:** added
$109,000 of wages. Federal taxes go from $0 to $25,079"). An only job counts as wages. A deductible cost named without
an amount ("I have a monthly mortgage payment") gets a question for the yearly amount (`missing_amount`), with how much
it would take to beat the standard deduction against the running estimate; the profile keeps `pending` so the answer
("about $12,000 a year") goes straight into the estimate, skipping the tool picker.

## Notes in our own words

Nine short notes (`src/data/tax_notes/`, category `tax-notes`, `rag.local_categories`) cover what Wikipedia lacks:
estimated quarterly tax, selling a home, dividends and interest, Social Security benefits, crypto, student loan interest,
bonuses, rental income, RSUs and options. The tax agent searches them with the tax and retirement pages
(`TAX_CATEGORIES`); answers cite them as "Finnie note, from the IRS" with the IRS page as the link. Measurements in
kb-token-stats-tax-notes.md.

## Tax year 2025 and the student loan deduction

`tax_rules.yaml` has a 2025 block as well as 2026 (2025 brackets and standard deduction as raised by the 2025 law, 65+
addition, capital-gains bands, earned income credit table, SALT cap $40,000, wage base $176,100; the 50% child-care rate
starts only in 2026). A question naming 2025 is worked out with 2025 rules. The student loan interest deduction (up to
$2,500, phased out by modified AGI; none on a separate return) is an above-the-line adjustment. A third-person scenario
with no question ("Sarah is a single taxpayer... salary $95,000...") runs the estimate when the model picks it, and is
never sent to the off-topic guard (`_tax_scenario`). "401(k)", "529", "Form 1099" and the like are names, not amounts
(`NOT_AMOUNTS`).

## Next

4. A tax eval set (about 20 cases with hand-checked answers), run after any prompt or rules change.
