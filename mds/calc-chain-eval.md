# Calculator chain eval

`python -m scripts.eval_calc_chains` on 2026-11-27: **21/30 chains passed**, 77/90 messages (first message 28/30, first follow-up 27/30, second follow-up 22/30). Provider `auto`; models anthropic: claude-sonnet-5-5, openai: gpt-4o-mini, gemini: gemini-2.0-flash. Chains: [tests/data/calc_chain_eval.yaml](../tests/data/calc_chain_eval.yaml); single questions: [calc-eval.md](calc-eval.md); design: [calc-pipeline-design.md](calc-pipeline-design.md).

Each chain is three messages replayed through the real workflow with the real model, the conversation's memory carried between messages as in the app. A message passes when its reply contains every expected figure (within 0.5%); the references were worked out in Python from the standard formulas. The model varies between runs, so a chain can pass one run and fail the next: a failure is a lead to look at.

| Id | Chain | Result | Msg 1 | Msg 2 | Msg 3 |
|---|---|---|---|---|---|
| c01 | mortgage, a lower rate, then $200 a month extra | **fail** | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | **no 70 or 71; no 83,056.56** (Finance Q&A (need_info), LLM plan) |
| c02 | car loan, a shorter term, then a down payment | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c03 | credit card payoff at two payment sizes | pass | ok (Calculator, LLM plan, repaired after) | ok (Calculator, LLM plan) | ok (Calculator, Finance Q&A, LLM plan) |
| c04 | student loan, 10 versus 20 years | pass | ok (Calculator, LLM plan, repaired after) | ok (Calculator, LLM plan, repaired after) | ok (Calculator, LLM plan) |
| c05 | refinancing and its break-even | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c06 | lump sum growth, a lower rate, then monthly deposits and the growth part | **fail** | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | **no 191,126.11; no 94,126.11** (Calculator, LLM steps) |
| c07 | annual versus monthly compounding, then deposits | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM plan) |
| c08 | monthly saving over 10 then 20 years | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM plan) | ok (Calculator, LLM steps) |
| c09 | saving for a $50,000 goal | pass | ok (Calculator, LLM plan, repaired after) | ok (Calculator, Goal Planning, LLM plan, repaired after) | ok (Calculator, Goal Planning, LLM plan, repaired after) |
| c10 | emergency fund | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM plan) |
| c11 | a retirement nest egg drawn down | pass | ok (Calculator, LLM plan) | ok (Calculator, LLM plan) | ok (Calculator, LLM plan) |
| c12 | retirement goal at retirement, today, then the monthly saving | **fail** | ok (Calculator, LLM steps) | **no 226,588.92 or 237,918.36** (Calculator, LLM steps) | **no 811.35 or 848.14 or 887.26 or 924.04** (Calculator, LLM plan) |
| c13 | how much to have at retirement for a monthly income | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c14 | saving for retirement, then the income it pays | **fail** | ok (Calculator, LLM steps) | **no 5,705.46 or 5,738.74 or 5,681.79** (Calculator (need_info), LLM plan) | **no 1,440,843.68 or 1,449,248.6; no 8,423.03 or 8,472.17 or 8,388.08** (Calculator, LLM plan) |
| c15 | college tuition in 12 years, rising costs, then the money still needed | **fail** | **no 73,014.98 or 68,882.05** (Calculator, LLM steps) | **no 116,899.33 or 110,282.39 or 123,748.33** (Calculator, Finance Q&A, LLM steps) | **no 86,899.33 or 80,282.39 or 93,748.33** (Calculator, LLM steps) |
| c16 | a future lump sum today, a higher rate, then the gap | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, Finance Q&A, LLM steps) |
| c17 | a project's NPV at two rates, then its IRR | **fail** | ok (Market Analysis, Calculator, LLM plan, repaired after) | ok (Market Analysis, Calculator, LLM plan, repaired after) | **no 15.24** (Calculator (need_info), LLM plan) |
| c18 | lump sum versus annual payments | pass | ok (Calculator, Finance Q&A, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, Finance Q&A, LLM plan) |
| c19 | inflation, today's money and future prices | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c20 | real return and real growth | **fail** | **no 4.85 or 5** (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, Finance Q&A, LLM plan) |
| c21 | APR to APY with different compounding | pass | ok (Calculator, LLM steps) | ok (Calculator, Finance Q&A, LLM steps) | ok (Calculator, LLM steps) |
| c22 | compound annual growth rate | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c23 | a bond's price, current yield, then a lower yield | pass | ok (Calculator, LLM plan) | ok (Calculator, LLM steps) | ok (Calculator, LLM plan) |
| c24 | what fees cost over 30 years | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, Finance Q&A, LLM steps) |
| c25 | splitting money, then growing each part | pass | ok (Calculator, LLM plan) | ok (Calculator, LLM steps) | ok (Calculator, LLM plan) |
| c26 | salary with yearly raises | pass | ok (Calculator, LLM plan) | ok (Calculator, LLM plan) | ok (Calculator, LLM steps) |
| c27 | renting versus a mortgage over 5 years | pass | ok (Calculator, LLM plan) | ok (Calculator, LLM steps) | ok (Calculator, LLM plan, repaired after) |
| c28 | saving for a roof replacement | **fail** | ok (Calculator, LLM plan, repaired after) | ok (Calculator, Goal Planning, LLM plan) | **no 184.68 or 184.07** (Calculator, Goal Planning (need_info), LLM plan) |
| c29 | paying a loan off early | pass | ok (Calculator, LLM plan) | ok (Calculator, LLM plan) | ok (Calculator, LLM plan) |
| c30 | a college savings plan | **fail** | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | **no 92,154.47 or 92,541.82** (Calculator, Finance Q&A, LLM steps) |
