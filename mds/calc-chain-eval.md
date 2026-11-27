# Calculator chain eval

`python -m scripts.eval_calc_chains` on 2026-11-27: **6/30 chains passed**, 46/90 messages (first message 16/30, first follow-up 17/30, second follow-up 13/30). Provider `auto`; models anthropic: claude-sonnet-5-5, openai: gpt-4o-mini, gemini: gemini-2.0-flash. Chains: [tests/data/calc_chain_eval.yaml](../tests/data/calc_chain_eval.yaml); single questions: [calc-eval.md](calc-eval.md); design: [calc-pipeline-design.md](calc-pipeline-design.md).

Each chain is three messages replayed through the real workflow with the real model, the conversation's memory carried between messages as in the app. A message passes when its reply contains every expected figure (within 0.5%); the references were worked out in Python from the standard formulas. The model varies between runs, so a chain can pass one run and fail the next: a failure is a lead to look at.

| Id | Chain | Result | Msg 1 | Msg 2 | Msg 3 |
|---|---|---|---|---|---|
| c01 | mortgage, a lower rate, then $200 a month extra | **fail** | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | **no 70 or 71; no 83,056.56** (Calculator (need_info), LLM plan) |
| c02 | car loan, a shorter term, then a down payment | **fail** | ok (Calculator, LLM steps) | **no 718.39** (Calculator, LLM steps) | **no 495.03** (Calculator (need_info), LLM plan) |
| c03 | credit card payoff at two payment sizes | **fail** | **no 32 or 31.92; no 1,979.05** (Calculator (need_info), LLM plan) | ok (Calculator, LLM plan) | ok (Calculator, LLM plan, repaired after) |
| c04 | student loan, 10 versus 20 years | **fail** | **no 434.11; no 12,092.61** (Calculator (need_info), LLM plan) | **no 275.15; no 26,037.18** (Calculator (need_info), LLM plan) | **no 13,944.57** (Calculator (need_info), LLM steps) |
| c05 | refinancing and its break-even | **fail** | **no 1,766.95** (Calculator (need_info), LLM plan) | **no 1,535.22; no 231.73** (Calculator (need_info), LLM plan) | **no 17.26 or 18 or 17** (Calculator (need_info), LLM plan) |
| c06 | lump sum growth, a lower rate, then monthly deposits and the growth part | **fail** | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | **no 94,126.11** (Calculator, LLM plan, repaired after) |
| c07 | annual versus monthly compounding, then deposits | **fail** | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | **no 53,622.81 or 53,768.22** (Calculator (need_info), LLM plan) |
| c08 | monthly saving over 10 then 20 years | **fail** | **no 81,939.67 or 82,349.37** (Calculator (need_info), LLM plan) | **no 231,020.45 or 232,175.55** (Calculator (need_info), LLM plan) | **no 149,080.77 or 149,826.18** (Calculator (need_info), LLM plan) |
| c09 | saving for a $50,000 goal | **fail** | ok (Calculator, LLM plan, repaired after) | ok (Calculator, Goal Planning, LLM plan) | **no 320.9 or 319.84** (Goal Planning (need_info), LLM plan) |
| c10 | emergency fund | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, Finance Q&A, LLM steps) |
| c11 | a retirement nest egg drawn down | **fail** | **no 36.72 or 36 or 37** (Calculator, LLM plan) | **no 25.68 or 25 or 26** (Calculator, LLM plan) | ok (Calculator, LLM steps) |
| c12 | retirement goal at retirement, today, then the monthly saving | **fail** | ok (Calculator, LLM steps) | **no 226,588.92 or 237,918.36** (Calculator (need_info), LLM plan) | **no 811.35 or 848.14 or 887.26 or 924.04** (Goal Planning (need_info), LLM plan) |
| c13 | how much to have at retirement for a monthly income | **fail** | ok (Calculator, LLM plan) | ok (Calculator, LLM steps) | **no 745,126.47 or 748,231.17** (Calculator (need_info), LLM plan) |
| c14 | saving for retirement, then the income it pays | **fail** | ok (Calculator, LLM steps) | **no 5,705.46 or 5,738.74 or 5,681.79** (Calculator (need_info), LLM steps) | **no 1,440,843.68 or 1,449,248.6; no 8,423.03 or 8,472.17 or 8,388.08** (Calculator (need_info), LLM steps) |
| c15 | college tuition in 12 years, rising costs, then the money still needed | **fail** | **no 73,014.98 or 68,882.05** (Calculator, LLM steps) | **no 116,899.33 or 110,282.39 or 123,748.33** (Finance Q&A (need_info), LLM plan) | **no 86,899.33 or 80,282.39 or 93,748.33** (Tax Education (need_info), LLM plan) |
| c16 | a future lump sum today, a higher rate, then the gap | pass | ok (Calculator, LLM plan) | ok (Calculator, LLM steps) | ok (Finance Q&A (need_info), LLM plan) |
| c17 | a project's NPV at two rates, then its IRR | **fail** | **no 3,956.26** (Market Analysis (need_info), LLM plan) | ok (Market Analysis, Calculator, LLM steps) | **no 15.24** (Calculator (need_info), LLM plan) |
| c18 | lump sum versus annual payments | pass | ok (Calculator, LLM plan) | ok (Calculator, LLM steps) | ok (Finance Q&A (need_info), LLM plan) |
| c19 | inflation, today's money and future prices | **fail** | ok (Calculator, LLM steps) | **no 90.31** (Calculator (need_info), LLM plan) | **no 67,297.13** (Calculator, LLM steps) |
| c20 | real return and real growth | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM plan, repaired after) | ok (Calculator, LLM steps) |
| c21 | APR to APY with different compounding | **fail** | ok (Calculator, LLM steps) | **no 5.13** (Calculator, LLM steps) | ok (Calculator, LLM steps) |
| c22 | compound annual growth rate | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, LLM plan) |
| c23 | a bond's price, current yield, then a lower yield | **fail** | **no 926.4** (Calculator (need_info), LLM steps) | **no 5.4** (Finance Q&A (need_info), LLM plan) | ok (Calculator, Finance Q&A, LLM plan) |
| c24 | what fees cost over 30 years | pass | ok (Calculator, LLM steps) | ok (Calculator, LLM steps) | ok (Calculator, Finance Q&A, LLM steps) |
| c25 | splitting money, then growing each part | **fail** | **no 7,200; no 3,600; no 1,200** (Tax Education) | ok (Calculator, LLM plan) | ok (Calculator, LLM plan) |
| c26 | salary with yearly raises | **fail** | **no 80,634.98 or 78,286.39** (Tax Education) | **no 687,832.76 or 708,467.74** (Tax Education (need_info), LLM plan) | ok (Tax Education) |
| c27 | renting versus a mortgage over 5 years | **fail** | **no 127,419.26** (Calculator (need_info), LLM plan) | ok (Calculator, LLM plan, repaired after) | ok (Calculator, LLM plan) |
| c28 | saving for a roof replacement | **fail** | **no 190.41 or 189.93** (Tax Education) | **no 2,318.96 or 2,251.42** (Tax Education) | **no 184.68 or 184.07** (Tax Education (need_info), LLM plan) |
| c29 | paying a loan off early | **fail** | **no 58 or 57.68** (Calculator (need_info), LLM steps) | ok (Calculator, LLM plan, repaired after) | **no 701.94** (Calculator, LLM plan, repaired after) |
| c30 | a college savings plan | **fail** | **no 77,470.64 or 77,857.99** (Calculator (need_info), LLM steps) | ok (Calculator, LLM plan) | **no 92,154.47 or 92,541.82** (Calculator (need_info), LLM plan) |
