# Tax agent eval

`python -m scripts.eval_tax` on 2026-11-24: **40/40 cases passed** (74/74 messages). Provider `auto`; models anthropic: claude-sonnet-5-5, openai: gpt-4o-mini, gemini: gemini-2.0-flash. Cases: [tests/data/tax_eval.yaml](../tests/data/tax_eval.yaml); design: [agent-tax-agent.md](agent-tax-agent.md).

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
| d01 | chain (2) | head-of-household button for a parent with one young child | pass | $1,748 | $6,338 | none |  |
| d02 | chain (2) | a figure added after the estimate | pass | $8,120 | $13,858 | none |  |
| d03 | chain (2) | an amount corrected, which switches from itemizing to the standard deduction | pass | $10,970 | $17,855 | none |  |
| d04 | chain (2) | an unmarried-parent question answered "married filing jointly" | pass | $-1,836 | $1,989 | none |  |
| d05 | chain (2) | what a charitable gift saves when already itemizing | pass | $12,752 | $20,402 | none |  |
| d06 | chain (2) | Roth vs traditional after an estimate | pass | $17,570 | $26,750 | none |  |
| d07 | chain (2) | a stock sale after an estimate | pass | $6,570 | $11,925 | none |  |
| d08 | chain (2) | a wash sale, then a question about it | pass | — | — | none |  |
| d09 | chain (2) | retired couple, then a Social Security question | pass | $0 | $0 | none |  |
| d10 | chain (2) | a single dad who then says he's married and adds his wife's pay | pass | $6,040 | $14,072 | none |  |
| d11 | chain (3) | deductions added one by one until itemizing wins | pass | $14,724 | $26,199 | none |  |
| d12 | chain (2) | a freelancer, then estimated tax | pass | $7,527 | $18,830 | none |  |
| d13 | chain (2) | tips, then overtime added | pass | $3,700 | $8,366 | none |  |
| d14 | chain (2) | a single mom corrects the number of children | pass | $-7,323 | $-4,263 | none |  |
| d15 | chain (2) | the filing-status button answered "single" | pass | $10,620 | $17,122 | none |  |
| d16 | chain (2) | a deduction first, then income and status | pass | $6,130 | $11,485 | none |  |
| d17 | chain (3) | an estimate, a side question, then a what-if bonus | pass | $12,070 | $19,338 | none |  |
| d18 | chain (2) | crypto held under a year, then "what if I'd held it longer" | pass | $5,020 | $9,610 | none |  |
| d19 | chain (2) | the student-dependent question answered yes | pass | $8,120 | $14,622 | none |  |
| d20 | chain (2) | a low-income family with credits, then a raise | pass | $-9,083 | $-5,258 | none |  |
