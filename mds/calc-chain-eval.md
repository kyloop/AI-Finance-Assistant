# Calculator chain eval

`python -m scripts.eval_calc_chains` on 2026-11-27: **17/30 chains passed**, 69/90 messages (first message 25/30, first follow-up 24/30, second follow-up 20/30). Provider `auto`; models anthropic: claude-sonnet-5-5, openai: gpt-4o-mini, gemini: gemini-2.0-flash. Chains: [tests/data/calc_chain_eval.yaml](../tests/data/calc_chain_eval.yaml); single questions: [calc-eval.md](calc-eval.md); design: [calc-pipeline-design.md](calc-pipeline-design.md).

Each chain is three messages replayed through the real workflow with the real model, the conversation's memory carried between messages as in the app. A message passes when its reply contains every expected figure (within 0.5%); the references were worked out in Python from the standard formulas. The model varies between runs, so a chain can pass one run and fail the next: a failure is a lead to look at.

| Id | Chain | Result | Msg 1 | Msg 2 | Msg 3 |
|---|---|---|---|---|---|
| c01 | mortgage, a lower rate, then $200 a month extra | **fail** | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | **no 70 or 71; no 83,056.56** (Finance Q&A (need_info), LLM plan) |
| c02 | car loan, a shorter term, then a down payment | **fail** | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | **no 495.03** (Calculator, LLM plan) |
| c03 | credit card payoff at two payment sizes | pass | ok (Calculator, LLM plan, repaired after) | ok (Calculator, LLM plan) | ok (Calculator, Finance Q&A, LLM plan, repaired after) |
| c04 | student loan, 10 versus 20 years | **fail** | **no 434.11; no 12,092.61** (Calculator (need_info), LLM plan) | **no 275.15; no 26,037.18** (Calculator (need_info), LLM plan) | ok (Calculator, LLM steps) |
| c05 | refinancing and its break-even | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c06 | lump sum growth, a lower rate, then monthly deposits and the growth part | **fail** | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | **no 191,126.11; no 94,126.11** (Calculator, LLM steps) |
| c07 | annual versus monthly compounding, then deposits | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM plan) |
| c08 | monthly saving over 10 then 20 years | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c09 | saving for a $50,000 goal | **fail** | ok (Calculator, LLM steps) | **no 569.99 or 568.1** (Calculator, Goal Planning, LLM steps) | **no 320.9 or 319.84** (Calculator, Goal Planning, LLM steps) |
| c10 | emergency fund | **fail** | ok (Calculator, LLM steps) | ok (Calculator, LLM plan) | **no 28.64 or 29** (Calculator, LLM steps) |
| c11 | a retirement nest egg drawn down | pass | ok (Calculator, LLM plan) | ok (Calculator, LLM plan) | ok (Calculator, LLM plan) |
| c12 | retirement goal at retirement, today, then the monthly saving | **fail** | ok (Calculator, LLM steps) | **no 226,588.92 or 237,918.36** (Calculator, LLM steps) | **no 811.35 or 848.14 or 887.26 or 924.04** (Calculator, LLM steps) |
| c13 | how much to have at retirement for a monthly income | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c14 | saving for retirement, then the income it pays | **fail** | ok (Calculator, LLM steps) | ok (Calculator, LLM plan, repaired after) | **no 1,440,843.68 or 1,449,248.6; no 8,423.03 or 8,472.17 or 8,388.08** (Calculator, LLM steps) |
| c15 | college tuition in 12 years, rising costs, then the money still needed | **fail** | **no 73,014.98 or 68,882.05** (Tax Education) | **no 116,899.33 or 110,282.39 or 123,748.33** (Calculator, Finance Q&A, LLM plan) | **no 86,899.33 or 80,282.39 or 93,748.33** (Tax Education (need_info), LLM steps) |
| c16 | a future lump sum today, a higher rate, then the gap | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c17 | a project's NPV at two rates, then its IRR | **fail** | **no 3,956.26** (Market Analysis (need_info), LLM plan) | ok (Market Analysis, Calculator, LLM plan, repaired after) | **no 15.24** (Calculator (need_info), LLM plan) |
| c18 | lump sum versus annual payments | pass | ok (Calculator, Finance Q&A, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c19 | inflation, today's money and future prices | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c20 | real return and real growth | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator (need_info), LLM plan) |
| c21 | APR to APY with different compounding | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c22 | compound annual growth rate | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c23 | a bond's price, current yield, then a lower yield | pass | ok (Calculator, LLM plan) | ok (Calculator, Finance Q&A, LLM steps) | ok (Calculator, LLM plan) |
| c24 | what fees cost over 30 years | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM plan) |
| c25 | splitting money, then growing each part | **fail** | **no 7,200; no 3,600; no 1,200** (Tax Education) | ok (Calculator, LLM plan) | ok (Calculator, LLM steps) |
| c26 | salary with yearly raises | **fail** | **no 80,634.98 or 78,286.39** (Tax Education) | **no 687,832.76 or 708,467.74** (Tax Education (need_info), LLM plan) | ok (Calculator, LLM steps) |
| c27 | renting versus a mortgage over 5 years | pass | ok (Calculator, LLM plan) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c28 | saving for a roof replacement | **fail** | ok (Calculator, LLM steps) | **no 2,318.96 or 2,251.42** (Goal Planning (need_info), LLM plan) | **no 184.68 or 184.07** (Calculator, Finance Q&A, LLM plan, repaired after) |
| c29 | paying a loan off early | pass | ok (Calculator, LLM plan, repaired after) | ok (Calculator, LLM plan) | ok (Calculator, LLM plan) |
| c30 | a college savings plan | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM plan) |
