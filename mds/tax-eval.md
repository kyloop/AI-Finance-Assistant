# Tax agent eval

`python -m scripts.eval_tax` on 2026-11-24: **13/20 cases passed** (25/32 messages). Provider `auto`; models anthropic: claude-sonnet-5-5, openai: gpt-4o-mini, gemini: gemini-2.0-flash. Cases: [tests/data/tax_eval.yaml](../tests/data/tax_eval.yaml); design: [agent-tax-agent.md](agent-tax-agent.md).

Each case is replayed through the real workflow with the real model, the conversation's memory carried between messages as in the app. After every message the check compares who answered, the filing status, how each amount was sorted, the household, the income tax and federal total (within $1), the question asked and required phrases. Expected inputs are set by hand; the totals come from them by hand or with the hand-tested estimator. The model varies between runs, so a case can pass one run and fail the next: a failure is a lead to look at.

| Id | Kind | Case | Result | Income tax | Federal total | Asked | Problems |
|---|---|---|---|---|---|---|---|
| s01 | single (1) | Kevin's first case; single assumed, side job and stocks unspecified | pass | $43,574 | $58,030 | status |  |
| s02 | single (1) | single mom, head of household, two kids, daycare | pass | $-4,869 | $-1,044 | none |  |
| s03 | single (1) | retired couple, both 67, pension and a part-time job | pass | $2,250 | $4,545 | none |  |
| s04 | single (1) | waiter, tips included in pay | pass | $990 | $3,897 | status |  |
| s05 | single (1) | college tuition for a son and car-loan interest | **fail** | $5,870 | $12,372 | none | msg 1: income_tax 5870.0, expected [8070, 7570] / msg 1: total_federal 12372.5, expected [14572.5, 14072.5] |
| s06 | single (1) | Kevin's "Sarah" scenario, tax year 2025, itemizes, student loan phase-out | pass | $10,275 | $17,543 | none |  |
| s07 | single (1) | married, one child, qualified dividends, mortgage below the standard deduction | pass | $4,840 | $12,108 | none |  |
| s08 | single (1) | freelancer with self-employment tax | **fail** | $4,751 | $13,229 | status | msg 1: filing status None, expected 'single' |
| s09 | single (1) | a capital loss limited to $3,000 | pass | $10,310 | $17,195 | none |  |
| s10 | single (1) | high earners, SALT cap, NIIT and additional Medicare | pass | $86,316 | $106,080 | none |  |
| s11 | single (1) | single senior with IRA withdrawals and a part-time job | **fail** | $5,254 | $6,784 | status | msg 1: filing status None, expected 'single' |
| s12 | single (1) | overtime included in pay (time-and-a-half premium deducted) | pass | $5,910 | $11,265 | none |  |
| c01 | chain (5) | Kevin's chain, figures one message at a time, then the mortgage interest asked for | pass | $15,442 | $23,780 | status |  |
| c02 | chain (2) | the filing-status button | pass | $31,940 | $46,352 | stock |  |
| c03 | chain (2) | a correction to how the stocks were held | **fail** | $43,574 | $58,030 | none | msg 2: total_federal 58030.5, expected 62100.5 / msg 2: reply lacks 'is now short-term capital gains' |
| c04 | chain (2) | a what-if raise after an estimate | pass | $17,570 | $26,750 | none |  |
| c05 | chain (3) | a side question in the middle keeps the estimate | pass | $9,792 | $16,619 | none |  |
| c06 | chain (2) | an explanation after an estimate uses that person's numbers and year | **fail** | $10,275 | $17,543 | none | msg 2: reply lacks '$900' / msg 2: reply lacks '$48,350' |
| c07 | chain (2) | an unmarried parent is asked about head of household and answers with the button | **fail** | $-4,869 | $-1,044 | none | msg 1: asked 'none', expected status_hoh |
| c08 | chain (2) | a deduction given before any income is kept, then the income | **fail** | — | — | none | msg 2: answered by ['Finnie'], expected the Tax agent only / msg 2: 120,000 sorted as None, expected wages / msg 2: total_federal None, expected 26750 |
