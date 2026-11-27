# Calculator eval

`python -m scripts.eval_calc` on 2026-11-27: 18/26 passed, 3 of them after the repair round. Provider `auto` (first key set); models anthropic: claude-sonnet-5-5, openai: gpt-4o-mini, gemini: gemini-2.0-flash. Questions and references: [tests/data/calc_eval.yaml](../tests/data/calc_eval.yaml); design: [calc-pipeline-design.md](calc-pipeline-design.md) and [calc-plan-design.md](calc-plan-design.md). Route: sourced (equation from the knowledge base and the web, cross-checked) or plan path (Finnie's own model).

| Id | Question | Result | Route | Results | Rejections |
|---|---|---|---|---|---|
| c01 | If I invest $1,000 in 5 different stocks, how much is in each stock? | pass (repaired) | arithmetic | amount_per_stock = 200 | the question's number 5 isn't used: make it a "user" input that a step uses, compute it in a step, or list it in "ignored" with why |
| c02 | You have $10,000 to invest. You put 50% of it into a broad market index fund, 30% into a t… | pass | plan path | index = 5000; tech_stock = 3000; crypto = 2000 |  |
| c03 | If you decide to save $600 every month and split it equally into 3 different retirement ac… | **fail** | sourced: matched | i = 0.005; n = 240; A = 200; PV = 200; FV = 662.041 |  |
| c04 | Imagine you invest $10,000 in a retirement fund at an average annual interest rate of 8%, … | pass | sourced: matched | A = 21589.2 |  |
| c05 | What's the monthly payment on a $300,000 mortgage at 6.5% for 30 years? | pass | sourced: matched | r = 0.00541667; n = 360; P = 1896.2 |  |
| c06 | What is $10,000 received in 10 years worth today at a 5% discount rate? | pass | plan path on sourced equations | PV = 6139.13 |  |
| c07 | How long does it take to double my money at 7% a year? | pass | sourced: matched | t = 10.2857 |  |
| c08 | If my investments return 7% and inflation is 3%, what is my real return? | pass | sourced: matched | r = 0.04 |  |
| c09 | What APY does a 4.65% APR compounded monthly give? | pass | plan path on sourced equations | APY = 0.0475039 (samples: n) |  |
| c10 | I retire with $1,000,000 and withdraw $45,000 in the first year, raising the withdrawal 3%… | pass | plan path | years = 28 |  |
| c11 | What's the IRR if I invest $10,000 and get back $3,000, $4,000 and $5,000 over three years… | pass | plan path on sourced equations | irr = 0.0889634 |  |
| c12 | If I invest $10,000 and want $15,000 in 5 years, what yearly return do I need? | pass | sourced: matched | r = 0.0844718; fv = 15000 |  |
| c13 | What will $1,000 be worth in today's money after 10 years of 3% inflation? | **fail** | plan path | FV = 1343.92 |  |
| c14 | A bond pays a $50 coupon each year and trades at $950. What is its current yield? | pass | sourced: matched | CY = 0.0526316 |  |
| c15 | I owe $5,000 on a credit card at 18% APR and pay $200 a month. How many months until it's … | **fail** | ask | asked | check 2: needs a formula of at most 200 characters / step months: balance ends at -86.04, so the last period paid more than was owed: pay at most what is owed ("payment": "min(P, balance + interest)") and keep the interest paid as a state variable, and take totals from those running totals, not payment × periods |
| c16 | What is Retirement Income Sustainability? You retire with a $1,000,000 portfolio. You want… | **fail** | ask | asked | the question's number 4.5 isn't used: make it a "user" input that a step uses, compute it in a step, or list it in "ignored" with why / input(s) withdrawal_rate not used by any step |
| c17 | How much will my savings grow? | pass | needs | asked |  |
| c18 | A future homebuyer determines they will need a $40,000 down payment to purchase a house ex… | pass | sourced: matched | PV = 32877.1 |  |
| c19 | An individual stores $10,000 in physical cash under a mattress. The money sits untouched f… | pass (repaired) | plan path on sourced equations | PV = 5536.76 (samples: i) | the question's number 3 isn't used: make it a "user" input that a step uses, compute it in a step, or list it in "ignored" with why |
| c20 | A consumer has an outstanding credit card balance of $5,000 at a 20% APR. If the minimum m… | **fail** | ask | asked | step years: needs a formula of at most 200 characters / step years: needs a formula of at most 200 characters |
| c21 | An employee receives a $5,000 year-end bonus and decides to use it to clear a portion of t… | **fail** | ask | asked | the question's number 5000 isn't used: make it a "user" input that a step uses, compute it in a step, or list it in "ignored" with why / input(s) bonus not used by any step |
| c22 | A worker plans to buy a used car for $18,000. The dealership offers them a 5-year auto loa… | **fail** (repaired) | sourced: one source | A = 27357.8; B = 9357.82 (samples: n) | input n = 24 is marked "user" but isn't in the question or the conversation; mark it "sample" if it's an assumption |
| c23 | Can you show me an example of how to calculate WACC? | pass | plan path on sourced equations | cost_of_equity = 0.09; cost_of_debt = 5.05; WACC = 0.916667 (samples: r_f, beta, r_m, APR, F, P, n, E, D) |  |
| c24 | If a stock has a beta of 1.2, what would its expected return be if the market return is 8%… | **fail** | sourced: matched | r_stock = 9.6 (samples: Rf) |  |
| c25 | show me example of CAPM? | pass | plan path on sourced equations | r_e = 0.09 (samples: R_f, beta_i, r_e_calculated) |  |
| c26 | How much will $5,000 grow to at 8% a year over 15 years? | pass | sourced: matched | FV = 15860.8 |  |
