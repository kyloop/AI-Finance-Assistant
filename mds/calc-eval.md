# Calculator eval

`python -m scripts.eval_calc` on 2026-11-24: 18/26 passed, 4 of them after the repair round. Provider `auto` (first key set); models anthropic: claude-sonnet-5-5, openai: gpt-4o-mini, gemini: gemini-2.0-flash. Questions and references: [tests/data/calc_eval.yaml](../tests/data/calc_eval.yaml); design: [calc-pipeline-design.md](calc-pipeline-design.md) and [calc-plan-design.md](calc-plan-design.md). Route: sourced (equation from the knowledge base and the web, cross-checked) or plan path (Finnie's own model).

| Id | Question | Result | Route | Results | Rejections |
|---|---|---|---|---|---|
| c01 | If I invest $1,000 in 5 different stocks, how much is in each stock? | pass | arithmetic | A = 200 |  |
| c02 | You have $10,000 to invest. You put 50% of it into a broad market index fund, 30% into a t… | pass | plan path | index = 5000; tech_stock = 3000; crypto = 2000 |  |
| c03 | If you decide to save $600 every month and split it equally into 3 different retirement ac… | **fail** | ask | asked | the reply is not a JSON plan / step by_account: "vary" needs "input", one of the inputs |
| c04 | Imagine you invest $10,000 in a retirement fund at an average annual interest rate of 8%, … | pass | plan path on sourced equations | A = 21589.2 |  |
| c05 | What's the monthly payment on a $300,000 mortgage at 6.5% for 30 years? | pass (repaired) | plan path on sourced equations | i = 0.00541667; n = 360; M = 1896.2 | the reply is not a JSON plan |
| c06 | What is $10,000 received in 10 years worth today at a 5% discount rate? | pass | plan path on sourced equations | PV = 6139.13 |  |
| c07 | How long does it take to double my money at 7% a year? | pass | sourced: matched | t = 10.2857 |  |
| c08 | If my investments return 7% and inflation is 3%, what is my real return? | pass | plan path on sourced equations | real_return = 0.04 |  |
| c09 | What APY does a 4.65% APR compounded monthly give? | pass | plan path on sourced equations | APY = 0.0475039 (samples: n) |  |
| c10 | I retire with $1,000,000 and withdraw $45,000 in the first year, raising the withdrawal 3%… | pass | plan path | years = 28 |  |
| c11 | What's the IRR if I invest $10,000 and get back $3,000, $4,000 and $5,000 over three years… | pass | plan path on sourced equations | irr = 0.0889634 |  |
| c12 | If I invest $10,000 and want $15,000 in 5 years, what yearly return do I need? | **fail** | sourced: matched | r = -0.7 |  |
| c13 | What will $1,000 be worth in today's money after 10 years of 3% inflation? | pass | plan path on sourced equations | PV = 744.094 |  |
| c14 | A bond pays a $50 coupon each year and trades at $950. What is its current yield? | pass | sourced: matched | C = 0.0526316 |  |
| c15 | I owe $5,000 on a credit card at 18% APR and pay $200 a month. How many months until it's … | **fail** | ask | asked | check failed: with P = 0, months = none (a simulation that never stopped, or an equation with no solution) (the simulation ran 1200 months without reaching `balance <= 0`: is the stop condition reachable?) but floor(B / P) = 7500000000; the formula or the check is wrong A reviewer judged the plan: The plan's model is incorrect because it does not handle the case where the payment amount (P) is zero. In such a scenario, the debt would never be paid off, and the expected output should reflect that the number of months to pay off the debt is infinite, not a numerical value. Therefore, the plan's calculation is flawed, and the check's expectation is not applicable in this case. / check 1: inf not defined (an input or an earlier step) |
| c16 | What is Retirement Income Sustainability? You retire with a $1,000,000 portfolio. You want… | **fail** | ask | asked | the question's number 4.5 isn't used: make it a "user" input that a step uses, compute it in a step, or list it in "ignored" with why / input(s) p not used by any step |
| c17 | How much will my savings grow? | pass | needs | asked |  |
| c18 | A future homebuyer determines they will need a $40,000 down payment to purchase a house ex… | pass | plan path on sourced equations | PV = 32877.1 |  |
| c19 | An individual stores $10,000 in physical cash under a mattress. The money sits untouched f… | **fail** (repaired) | sourced: matched, one source | FV_2 = 18061.1; PV = 10000; FV = 18061.1 | these can't be computed from the inputs: FV_2 needs i; PV needs FV_2, i |
| c20 | A consumer has an outstanding credit card balance of $5,000 at a 20% APR. If the minimum m… | **fail** | ask | asked | step total_interest: needs a formula of at most 200 characters / step total_interest: needs a formula of at most 200 characters |
| c21 | An employee receives a $5,000 year-end bonus and decides to use it to clear a portion of t… | **fail** | ask | asked | input(s) nper not used by any step / input(s) n not used by any step |
| c22 | A worker plans to buy a used car for $18,000. The dealership offers them a 5-year auto loa… | **fail** | ask | asked | input(s) P, r_loan, t_loan, t_savings not used by any step / input(s) P, r_loan, t_loan, t_savings not used by any step |
| c23 | Can you show me an example of how to calculate WACC? | pass (repaired) | plan path on sourced equations | r_e = 0.09; WACC = 0.074 (samples: Rf, beta_i, E_Rm, E, D, r_d) | check 2: "when" must set one or more inputs |
| c24 | If a stock has a beta of 1.2, what would its expected return be if the market return is 8%… | pass (repaired) | sourced: matched | r_stock = 0.09 (samples: r_f) | step r_stock: r_m is a percentage (unit "percent") added to or subtracted from a rate (a decimal) in 'r_f + beta*(r_m - r_f)'; give it as a rate too, a decimal (0.08 for 8%) |
| c25 | show me example of CAPM? | pass | sourced: matched | r_e = 0.09 (samples: r_f, beta_f, E_r_m) |  |
| c26 | How much will $5,000 grow to at 8% a year over 15 years? | pass | sourced: one source | FV = 15860.8 |  |
