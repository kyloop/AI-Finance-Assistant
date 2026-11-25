# Tax agent eval

`python -m scripts.eval_tax` on 2026-11-24: **20/20 cases passed** (32/32 messages). Provider `auto`; models anthropic: claude-sonnet-5-5, openai: gpt-4o-mini, gemini: gemini-2.0-flash. Cases: [tests/data/tax_eval.yaml](../tests/data/tax_eval.yaml); design: [agent-tax-agent.md](agent-tax-agent.md).

Each case is replayed through the real workflow with the real model, the conversation's memory carried between messages as in the app. After every message the check compares who answered, the filing status, how each amount was sorted, the household, the income tax and federal total (within $1), the question asked and required phrases. Expected inputs are set by hand; the totals come from them by hand or with the hand-tested estimator. The model varies between runs, so a case can pass one run and fail the next: a failure is a lead to look at.

| Id | Kind | Case | Result | Income tax | Federal total | Asked | Problems |
|---|---|---|---|---|---|---|---|
| s01 | single (1) | Kevin's first case; single assumed, side job and stocks unspecified | pass | $43,574 | $58,030 | status |  |
| s02 | single (1) | single mom, head of household, two kids, daycare | pass | $-4,869 | $-1,044 | none |  |
| s03 | single (1) | retired couple, both 67, pension and a part-time job | pass | $2,250 | $4,545 | none |  |
| s04 | single (1) | waiter, tips included in pay | pass | $990 | $3,897 | status |  |
| s05 | single (1) | college tuition for a son and car-loan interest | pass | $8,070 | $14,572 | dependent |  |
| s06 | single (1) | Kevin's "Sarah" scenario, tax year 2025, itemizes, student loan phase-out | pass | $10,275 | $17,543 | none |  |
| s07 | single (1) | married, one child, qualified dividends, mortgage below the standard deduction | pass | $4,840 | $12,108 | none |  |
| s08 | single (1) | freelancer with self-employment tax | pass | $4,751 | $13,229 | none |  |
| s09 | single (1) | a capital loss limited to $3,000 | pass | $10,310 | $17,195 | none |  |
| s10 | single (1) | high earners, SALT cap, NIIT and additional Medicare | pass | $86,316 | $106,080 | none |  |
| s11 | single (1) | single senior with IRA withdrawals and a part-time job | pass | $5,254 | $6,784 | none |  |
| s12 | single (1) | overtime included in pay (time-and-a-half premium deducted) | pass | $5,910 | $11,265 | none |  |
| c01 | chain (5) | Kevin's chain, figures one message at a time, then the mortgage interest asked for | pass | $15,442 | $23,780 | status |  |
| c02 | chain (2) | the filing-status button | pass | $31,940 | $46,352 | stock |  |
| c03 | chain (2) | a correction to how the stocks were held | pass | $47,644 | $62,100 | none |  |
| c04 | chain (2) | a what-if raise after an estimate | pass | $17,570 | $26,750 | none |  |
| c05 | chain (3) | a side question in the middle keeps the estimate | pass | $9,792 | $16,619 | none |  |
| c06 | chain (2) | an explanation after an estimate uses that person's numbers and year | pass | $10,275 | $17,543 | none |  |
| c07 | chain (2) | an unmarried parent is asked about head of household and answers with the button | pass | $-4,869 | $-1,044 | none |  |
| c08 | chain (2) | a deduction given before any income is kept, then the income | pass | $17,570 | $26,750 | status |  |
