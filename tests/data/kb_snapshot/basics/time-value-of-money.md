# Time value of money

<!-- https://en.wikipedia.org/wiki/Time_value_of_money | revision 1375554307 -->

The time value of money refers to the idea that there is generally a greater benefit to receiving a sum of money now rather than an identical sum later. It may be seen as an implication of the later developed concept of time preference.
The time value of money refers to the observation that it is better to receive money sooner than later. Money you have today can be invested to earn a positive rate of return, producing more money tomorrow. Therefore, a dollar today is worth more than a dollar in the future.
The time value of money is among the factors considered when weighing the opportunity costs of spending rather than saving or investing money. As such, it is among the reasons why interest is paid or earned: interest, whether it is on a bank deposit or debt, compensates the depositor or lender for the loss of their use of their money. Investors are willing to forgo spending their money now only if they expect a favorable net return on their investment in the future, such that the increased value to be available later is sufficiently high to offset both the preference to spending money now and inflation (if present); see required rate of return.

## Overview

The time value of money compares cash flows that occur at different dates by converting them to a single valuation date (often called “time 0”). In a simple discrete-time model, time is measured in equal-length periods 
  
    
      
        t
        =
        0
        ,
        1
        ,
        2
        ,
        …
      
    
    {\displaystyle t=0,1,2,\dots }
  
 and a constant effective interest rate 
  
    
      
        i
      
    
    {\displaystyle i}
  
 is applied once per period.
If an amount 
  
    
      
        
          P
          V
        
      
    
    {\displaystyle \mathrm {PV} }
  
 is invested at time 0, its value after 
  
    
      
        n
      
    
    {\displaystyle n}
  
 periods (the future value) is

  
    
      
        
          F
          V
        
        =
        
          P
          V
        
        (
        1
        +
        i
        
          )
          
            n
          
        
        .
      
    
    {\displaystyle \mathrm {FV} =\mathrm {PV} (1+i)^{n}.}
  

Discounting reverses this relationship, such that the present value of a sure amount 
  
    
      
        
          F
          V
        
      
    
    {\displaystyle \mathrm {FV} }
  
 due at time 
  
    
      
        n
      
    
    {\displaystyle n}
  
 is

  
    
      
        
          P
          V
        
        =
        
          F
          V
        
        (
        1
        +
        i
        
          )
          
            −
            n
          
        
        =
        
          
            
              F
              V
            
            
              (
              1
              +
              i
              
                )
                
                  n
                
              
            
          
        
        .
      
    
    {\displaystyle \mathrm {PV} =\mathrm {FV} (1+i)^{-n}={\frac {\mathrm {FV} }{(1+i)^{n}}}.}
  

The factor 
  
    
      
        (
        1
        +
        i
        
          )
          
            n
          
        
      
    
    {\displaystyle (1+i)^{n}}
  
 is the accumulation factor over 
  
    
      
        n
      
    
    {\displaystyle n}
  
 periods, and 
  
    
      
        (
        1
        +
        i
        
          )
          
            −
            n
          
        
      
    
    {\displaystyle (1+i)^{-n}}
  
 is the corresponding discount factor.
For a sequence of dated cash flows 
  
    
      
        
          
            C
            F
          
          
            t
          
        
      
    
    {\displaystyle \mathrm {CF} _{t}}
  
 (positive for receipts and negative for payments), present value is the discounted sum of each cash flow:

  
    
      
        
          P
          V
        
        =
        
          ∑
          
            t
            =
            0
          
          
            n
          
        
        
          
            
              
                C
                F
              
              
                t
              
            
            
              (
              1
              +
              i
              
                )
                
                  t
                
              
            
          
        
        .
      
    
    {\displaystyle \mathrm {PV} =\sum _{t=0}^{n}{\frac {\mathrm {CF} _{t}}{(1+i)^{t}}}.}
  

This discounted-sum form underlies net present value calculations used in valuation and capital budgeting.
Nominal and real analyses must be kept consistent. Nominal cash flows are discounted at nominal rates, while real cash flows (with general inflation removed) are discounted at real rates; mixing conventions changes results mechanically even when the underlying economics is unchanged.

## History

Charging or paying interest, compounding balances over time, and comparing payments at different dates long predate the modern terminology. Historical accounts of actuarial practice describe the use of compound interest in business transactions from the Middle Ages onwards, with systematic mathematical treatments of life-contingent payments developing later alongside probability theory and mortality data.
The pricing of annuities and other long-dated contracts was an important context for the development of formal present-value techniques. Modern historical work on financial economics traces key advances to the valuation of life annuities using discounted expected value methods and relates these developments to the emergence of life tables and to computational methods for discounting contingent cash flows.
Poitras discusses seventeenth-century contributions associated with Johan de Witt and Edmond Halley, and Lewin notes them in an actuarial history context: de Witt's correspondence with Jan Hudde (1671) addressed valuation of life annuities, and Halley's 1693 work showed how a life table could be applied to annuity pricing using empirical mortality data.
Early economic thought about lending, usury, and the purchasing power of money forms part of the background for later theories of discounting and interest. In the sixteenth and early seventeenth centuries, scholars associated with the University of Salamanca discussed the changing purchasing power of money and the moral and legal status of credit within a scholastic tradition that addressed monetary and commercial questions alongside theology and law.
Some modern accounts read Martín de Azpilcueta's discussions of money and exchange as anticipating elements of later interest theory, but specialist scholarship cautions against treating his work as an early statement of modern time-preference theory and notes that he continued to condemn usury in general.
In economics, Irving Fisher’s The Theory of Interest (1930) formalised an account of intertemporal valuation that links interest to impatience (time preference) and investment opportunities and influenced later treatments of discounting and present value in economic analysis and finance.

## Calculations

Time value of money problems involve the net value of cash flows at different points in time.
In a typical case, the variables might be: a balance (the real or nominal value of a debt or a financial asset in terms of monetary units), a periodic rate of interest, the number of periods, and a series of cash flows. (In the case of a debt, cash flows are payments against principal and interest; in the case of a financial asset, these are contributions to or withdrawals from the balance.) More generally, the cash flows may not be periodic but may be specified individually. Any of these variables may be the independent variable (the sought-for answer) in a given problem. For example, one may know that: the interest is 0.5% per period (per month, say); the number of periods is 60 (months); the initial balance (of the debt, in this case) is 25,000 units; and the final balance is 0 units. The unknown variable may be the monthly payment that the borrower must pay.
For example, £100 invested for one year, earning 5% interest, will be worth £105 after one year; therefore, £100 paid now and £105 paid exactly one year later both have the same value to a recipient who expects 5% interest assuming that inflation would be zero percent. That is, £100 invested for one year at 5% interest has a future value of £105 under the assumption that inflation would be zero percent.
This principle allows for the valuation of a likely stream of income in the future, in such a way that annual incomes are discounted and then added together, thus providing a lump-sum "present value" of the entire income stream; all of the standard calculations for time value of money derive from the most basic algebraic expression for the present value of a future sum, "discounted" to the present by an amount equal to the time value of money. For example, the future value sum 
  
    
      
        F
        V
      
    
    {\displaystyle FV}
  
 to be received in one year is discounted at the rate of interest 
  
    
      
        r
      
    
    {\displaystyle r}
  
 to give the present value sum 
  
    
      
        P
        V
      
    
    {\displaystyle PV}
  
:

  
    
      
        P
        V
        =
        
          
            
              F
              V
            
            
              (
              1
              +
              r
              )
            
          
        
      
    
    {\displaystyle PV={\frac {FV}{(1+r)}}}
  

Some standard calculations based on the time value of money are:

Present value: The current worth of a future sum of money or stream of cash flows, given a specified rate of return. Future cash flows are "discounted" at the discount rate; the higher the discount rate, the lower the present value of the future cash flows. Determining the appropriate discount rate is the key to valuing future cash flows properly, whether they be earnings or obligations.
Present value of an annuity: An annuity is a series of equal payments or receipts that occur at evenly spaced intervals. Leases and rental payments are examples. The payments or receipts occur at the end of each period for an ordinary annuity while they occur at the beginning of each period for an annuity due.
Present value of a perpetuity is an infinite and constant stream of identical cash flows.
Future value: The value of an asset or cash at a specified date in the future, based on the value of that asset in the present.
Future value of an annuity (FVA): The future value of a stream of payments (annuity), assuming the payments are invested at a given rate of interest.
There are several basic equations that represent the equalities listed above. The solutions may be found using (in most cases) the formulas, a financial calculator, or a spreadsheet. The formulas are programmed into most financial calculators and several spreadsheet functions (such as PV, FV, RATE, NPER, and PMT).
For any of the equations below, the formula may also be rearranged to determine one of the other unknowns. In the case of the standard annuity formula, there is no closed-form algebraic solution for the interest rate (although financial calculators and spreadsheet programs can readily determine solutions through rapid trial and error algorithms).
These equations are frequently combined for particular uses. For example, bonds can be readily priced using these equations. A typical coupon bond is composed of two types of payments: a stream of coupon payments similar to an annuity, and a lump-sum return of capital at the end of the bond's maturity—that is, a future payment. The two formulas can be combined to determine the present value of the bond.
An important note is that the interest rate i is the interest rate for the relevant period. For an annuity that makes one payment per year, i will be the annual interest rate. For an income or payment stream with a different payment schedule, the interest rate must be converted into the relevant periodic interest rate. For example, a monthly rate for a mortgage with monthly payments requires that the interest rate be divided by 12 (see the example below). See compound interest for details on converting between different periodic interest rates.
The rate of return in the calculations can be either the variable solved for, or a predefined variable that measures a discount rate, interest, inflation, rate of return, cost of equity, cost of debt or any number of other analogous concepts. The choice of the appropriate rate is critical to the exercise, and the use of an incorrect discount rate will make the results meaningless.
For calculations involving annuities, it must be decided whether the payments are made at the end of each period (known as an ordinary annuity), or at the beginning of each period (known as an annuity due). When using a financial calculator or a spreadsheet, it can usually be set for either calculation. The following formulas are for an ordinary annuity. For the answer to the present value of an annuity due, the PV of an ordinary annuity can be multiplied by (1 + i).

## Formula

The following formula use these common variables:

PV is the value at time zero (present value)
FV is the value at time n (future value)
A is the value of the individual payments in each compounding period
n is the number of periods (not necessarily an integer)
i is the interest rate at which the amount compounds each period
g is the growing rate of payments over each time period

### Future value of a present sum

The future value  (FV)  formula is similar and uses the same variables.

  
    
      
        F
        V
         
        =
         
        P
        V
        ⋅
        (
        1
        +
        i
        
          )
          
            n
          
        
      
    
    {\displaystyle FV\ =\ PV\cdot (1+i)^{n}}

### Present value of a future sum

The present value formula is the core formula for the time value of money; each of the other formulas is derived from this formula. For example, the annuity formula is the sum of a series of present value calculations.
The present value (PV) formula has four variables, each of which can be solved for by numerical methods:

  
    
      
        P
        V
         
        =
         
        
          
            
              F
              V
            
            
              (
              1
              +
              i
              
                )
                
                  n
                
              
            
          
        
      
    
    {\displaystyle PV\ =\ {\frac {FV}{(1+i)^{n}}}}
  

The cumulative present value of future cash flows can be calculated by summing the contributions of FVt, the value of cash flow at time t:

  
    
      
        P
        V
         
        =
         
        
          ∑
          
            t
            =
            1
          
          
            n
          
        
        
          
            
              F
              
                V
                
                  t
                
              
            
            
              (
              1
              +
              i
              
                )
                
                  t
                
              
            
          
        
      
    
    {\displaystyle PV\ =\ \sum _{t=1}^{n}{\frac {FV_{t}}{(1+i)^{t}}}}
  

Note that this series can be summed for a given value of n, or when n is ∞. This is a very general formula, which leads to several important special cases given below.

### Present value of an annuity for n payment periods

In this case the cash flow values remain the same throughout the n periods. The present value of an annuity (PVA) formula has four variables, each of which can be solved for by numerical methods:

  
    
      
        P
        V
        (
        A
        )
        
        =
        
        
          
            A
            i
          
        
        ⋅
        
          [
          
            1
            −
            
              
                1
                
                  
                    (
                    
                      1
                      +
                      i
                    
                    )
                  
                  
                    n
                  
                
              
            
          
          ]
        
      
    
    {\displaystyle PV(A)\,=\,{\frac {A}{i}}\cdot \left[{1-{\frac {1}{\left(1+i\right)^{n}}}}\right]}
  

To get the PV of an annuity due, multiply the above equation by (1 + i).

### Present value of a growing annuity

In this case, each cash flow grows by a factor of (1 + g). Similar to the formula for an annuity, the present value of a growing annuity (PVGA) uses the same variables with the addition of g as the rate of growth of the annuity (A is the annuity payment in the first period). This is a calculation that is rarely provided for on financial calculators.
Where i ≠ g :

  
    
      
        P
        V
        (
        A
        )
        
        =
        
        
          
            A
            
              (
              i
              −
              g
              )
            
          
        
        
          [
          
            1
            −
            
              
                (
                
                  
                    
                      1
                      +
                      g
                    
                    
                      1
                      +
                      i
                    
                  
                
                )
              
              
                n
              
            
          
          ]
        
      
    
    {\displaystyle PV(A)\,=\,{A \over (i-g)}\left[1-\left({1+g \over 1+i}\right)^{n}\right]}
  

Where i = g :

  
    
      
        P
        V
        (
        A
        )
        
        =
        
        
          
            
              A
              ×
              n
            
            
              1
              +
              i
            
          
        
      
    
    {\displaystyle PV(A)\,=\,{A\times n \over 1+i}}
  

To get the PV of a growing annuity due, multiply the above equation by (1 + i).

### Present value of a growing annuity and a fixed-benefit pension

How to calculate the present value of the Cost Of Living Adjustment that you will add to your fixed-benefit pension payment. The growth factor (1+g) applies to both cash flows and the fixed pension F. A is the first payment.

  
    
      
        P
        V
        (
        A
        )
        
        =
        
        
          
            
              A
              +
              F
            
            
              i
              −
              g
            
          
        
        
          [
          
            1
            −
            
              
                (
                
                  
                    
                      1
                      +
                      g
                    
                    
                      1
                      +
                      i
                    
                  
                
                )
              
              
                n
              
            
          
          ]
        
        −
        
          
            F
            i
          
        
        
          [
          
            1
            −
            
              
                1
                
                  (
                  1
                  +
                  i
                  
                    )
                    
                      n
                    
                  
                
              
            
          
          ]
        
      
    
    {\displaystyle PV(A)\,=\,{A+F \over i-g}\left[1-\left({1+g \over 1+i}\right)^{n}\right]-{F \over i}\left[1-{1 \over (1+i)^{n}}\right]}
  

To find the Present Value (PV) necessary to provide a Cost Of Living Adjustment for a pension, set A = 0 so:

Nothing is paid in the first year
The second year pays an amount equal to 
  
    
      
        F
        ×
        g
      
    
    {\displaystyle F\times g}
  

The third year pays 
  
    
      
        F
        (
        1
        +
        g
        
          )
          
            2
          
        
        
           minus 
        
        F
      
    
    {\displaystyle F(1+g)^{2}{\text{ minus }}F}
  

The fourth year pays 
  
    
      
        F
        (
        1
        +
        g
        
          )
          
            3
          
        
        
           minus 
        
        F
      
    
    {\displaystyle F(1+g)^{3}{\text{ minus }}F}
  
, and so on
If PV is more than what is needed, the extra amount gets spread across future payments, increasing each year by a factor of (1+g) which is a growing annuity. 

If PV is too small, the payment becomes negative, meaning the pension must be reduced by that amount in order to add the Cost Of Living Adjustment.

### Present value of a perpetuity

A perpetuity is payments of a set amount of money that occur on a routine basis and continue forever. When n → ∞, the PV of a perpetuity (a perpetual annuity) formula becomes a simple division.

  
    
      
        P
        V
        (
        P
        )
         
        =
         
        
          
            A
            i
          
        
      
    
    {\displaystyle PV(P)\ =\ {A \over i}}

### Present value of a growing perpetuity

When the perpetual annuity payment grows at a fixed rate (g, with g < i) the value is determined according to the following formula, obtained by setting n to infinity in the earlier formula for a growing perpetuity:

  
    
      
        P
        V
        (
        A
        )
        
        =
        
        
          
            A
            
              i
              −
              g
            
          
        
      
    
    {\displaystyle PV(A)\,=\,{A \over i-g}}
  

In practice, there are few securities with precise characteristics, and the application of this valuation approach is subject to various qualifications and modifications. Most importantly, it is rare to find a growing perpetual annuity with fixed rates of growth and true perpetual cash flow generation. Despite these qualifications, the general approach may be used in valuations of real estate, equities, and other assets.
This is the well known Gordon growth model used for stock valuation.

### Future value of an annuity

The future value (after n periods) of an annuity (FVA) formula has four variables, each of which can be solved for by numerical methods:

  
    
      
        F
        V
        (
        A
        )
        
        =
        
        A
        ⋅
        
          
            
              
                
                  (
                  
                    1
                    +
                    i
                  
                  )
                
                
                  n
                
              
              −
              1
            
            i
          
        
      
    
    {\displaystyle FV(A)\,=\,A\cdot {\frac {\left(1+i\right)^{n}-1}{i}}}
  

To get the FV of an annuity due, multiply the above equation by (1 + i).

### Future value of a growing annuity

The future value (after n periods) of a growing annuity (FVA) formula has five variables, each of which can be solved for by numerical methods:
Where i ≠ g :

  
    
      
        F
        V
        (
        A
        )
        
        =
        
        A
        ⋅
        
          
            
              
                
                  (
                  
                    1
                    +
                    i
                  
                  )
                
                
                  n
                
              
              −
              
                
                  (
                  
                    1
                    +
                    g
                  
                  )
                
                
                  n
                
              
            
            
              i
              −
              g
            
          
        
      
    
    {\displaystyle FV(A)\,=\,A\cdot {\frac {\left(1+i\right)^{n}-\left(1+g\right)^{n}}{i-g}}}
  

Where i = g :

  
    
      
        F
        V
        (
        A
        )
        
        =
        
        A
        ⋅
        n
        (
        1
        +
        i
        
          )
          
            n
            −
            1
          
        
      
    
    {\displaystyle FV(A)\,=\,A\cdot n(1+i)^{n-1}}

### Formula table

The following table summarizes the different formulas commonly used in calculating the time value of money. These values are often displayed in tables where the interest rate and time are specified.

Notes:

A is a fixed payment amount, every period
G is the initial payment amount of an increasing payment amount, that starts at G and increases by G for each subsequent period.
D is the initial payment amount of an exponentially (geometrically) increasing payment amount, that starts at D and increases by a factor of (1 + g) each subsequent period.

## Derivations

### Annuity derivation

The formula for the present value of a regular stream of future payments (an annuity) is derived from a sum of the formula for future value of a single future payment, as below, where C is the payment amount and n the period.
A single payment C at future time m has the following future value at future time n:

  
    
      
        F
        V
         
        =
        C
        (
        1
        +
        i
        
          )
          
            n
            −
            m
          
        
      
    
    {\displaystyle FV\ =C(1+i)^{n-m}}
  

Summing over all payments from time 1 to time n, then reversing the order of terms and substituting k = n − m:

  
    
      
        F
        V
        A
         
        =
        
          ∑
          
            m
            =
            1
          
          
            n
          
        
        C
        (
        1
        +
        i
        
          )
          
            n
            −
            m
          
        
         
        =
        
          ∑
          
            k
            =
            0
          
          
            n
            −
            1
          
        
        C
        (
        1
        +
        i
        
          )
          
            k
          
        
      
    
    {\displaystyle FVA\ =\sum _{m=1}^{n}C(1+i)^{n-m}\ =\sum _{k=0}^{n-1}C(1+i)^{k}}
  

Note that this is a geometric series, with the initial value being a = C, the multiplicative factor being 1 + i, with n terms. Applying the formula for geometric series, we get:

  
    
      
        F
        V
        A
         
        =
        
          
            
              C
              (
              1
              −
              (
              1
              +
              i
              
                )
                
                  n
                
              
              )
            
            
              1
              −
              (
              1
              +
              i
              )
            
          
        
         
        =
        
          
            
              C
              (
              1
              −
              (
              1
              +
              i
              
                )
                
                  n
                
              
              )
            
            
              −
              i
            
          
        
      
    
    {\displaystyle FVA\ ={\frac {C(1-(1+i)^{n})}{1-(1+i)}}\ ={\frac {C(1-(1+i)^{n})}{-i}}}
  

The present value of the annuity (PVA) is obtained by simply dividing by 
  
    
      
        (
        1
        +
        i
        
          )
          
            n
          
        
      
    
    {\displaystyle (1+i)^{n}}
  
:

  
    
      
        P
        V
        A
         
        =
        
          
            
              F
              V
              A
            
            
              (
              1
              +
              i
              
                )
                
                  n
                
              
            
          
        
        =
        
          
            C
            i
          
        
        
          (
          
            1
            −
            
              
                1
                
                  (
                  1
                  +
                  i
                  
                    )
                    
                      n
                    
                  
                
              
            
          
          )
        
      
    
    {\displaystyle PVA\ ={\frac {FVA}{(1+i)^{n}}}={\frac {C}{i}}\left(1-{\frac {1}{(1+i)^{n}}}\right)}
  

Another simple and intuitive way to derive the future value of an annuity is to consider an endowment, whose interest is paid as the annuity, and whose principal remains constant. The principal of this hypothetical endowment can be computed as that whose interest equals the annuity payment amount:

  
    
      
        
          Principal
        
        ×
        i
        =
        C
      
    
    {\displaystyle {\text{Principal}}\times i=C}
  

  
    
      
        
          Principal
        
        =
        
          
            C
            i
          
        
        +
        
          goal
        
      
    
    {\displaystyle {\text{Principal}}={\frac {C}{i}}+{\text{goal}}}
  

Note that no money enters or leaves the combined system of endowment principal + accumulated annuity payments, and thus the future value of this system can be computed simply via the future value formula:

  
    
      
        F
        V
        =
        P
        V
        (
        1
        +
        i
        
          )
          
            n
          
        
      
    
    {\displaystyle FV=PV(1+i)^{n}}
  

Initially, before any payments, the present value of the system is just the endowment principal, 
  
    
      
        P
        V
        =
        
          
            C
            i
          
        
      
    
    {\displaystyle PV={\frac {C}{i}}}
  
. At the end, the future value is the endowment principal (which is the same) plus the future value of the total annuity payments (
  
    
      
        F
        V
        =
        
          
            C
            i
          
        
        +
        F
        V
        A
      
    
    {\displaystyle FV={\frac {C}{i}}+FVA}
  
). Plugging this back into the equation:

  
    
      
        
          
            C
            i
          
        
        +
        F
        V
        A
        =
        
          
            C
            i
          
        
        (
        1
        +
        i
        
          )
          
            n
          
        
      
    
    {\displaystyle {\frac {C}{i}}+FVA={\frac {C}{i}}(1+i)^{n}}
  

  
    
      
        F
        V
        A
        =
        
          
            C
            i
          
        
        
          [
          
            
              
                (
                
                  1
                  +
                  i
                
                )
              
              
                n
              
            
            −
            1
          
          ]
        
      
    
    {\displaystyle FVA={\frac {C}{i}}\left[\left(1+i\right)^{n}-1\right]}

### Growing Annuity and a fixed-benefit pension derivation

C = First payment increasing by g each year
F = Fixed pension
View this as a lender/borrower scenario with the lender on the left side of the equal sign and the borrower on the right.
At the end of a 1-year loan, a saver would have his money grow by 1+i or PV(1+i). If he instead loaned this money out to a borrower, the borrower would need to make one payment C back to the lender. Setting these equal would give

  
    
      
        n
        =
        1
        :
        P
        V
        (
        1
        +
        i
        )
        =
        (
        C
        +
        F
        )
        −
        F
      
    
    {\displaystyle n=1:PV(1+i)=(C+F)-F}
  

At the end of a 2-year loan, a saver would have his money grow by another 1+i for a total amount of 
  
    
      
        P
        V
        (
        1
        +
        i
        
          )
          
            2
          
        
      
    
    {\displaystyle PV(1+i)^{2}}
  
. If he instead loaned this money out, the borrower would need to make two payments. The first payment (C+F)-F would start earning interest since it has now been paid back. His second payment (C+F) would grow by 1+g. The pension F would remain the same

  
    
      
        
          
            
              
                n
                =
                2
                :
                P
                V
                (
                1
                +
                i
                
                  )
                  
                    2
                  
                
                =
              
              
                
                (
                C
                +
                F
                )
                (
                1
                +
                i
                )
                −
                F
                (
                1
                +
                i
                )
              
            
            
              
              
                
                +
                (
                C
                +
                F
                )
                (
                1
                +
                g
                )
                −
                F
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}n=2:PV(1+i)^{2}=&(C+F)(1+i)-F(1+i)\\&+(C+F)(1+g)-F\end{aligned}}}
  

At the end of a 3-year loan, a saver would have his money grow by another 1+i for a total amount of 
  
    
      
        P
        V
        (
        1
        +
        i
        
          )
          
            3
          
        
      
    
    {\displaystyle PV(1+i)^{3}}
  
. If he instead loaned this money out, the borrower would need to make three payments. The first two payments would earn an additional (1+i) interest. His third payment would grow by an additional 1+g and the pension would still remain the same.

  
    
      
        
          
            
              
                n
                =
                3
                :
                P
                V
                (
                1
                +
                i
                
                  )
                  
                    3
                  
                
                =
              
              
                
                (
                C
                +
                F
                )
                (
                1
                +
                i
                
                  )
                  
                    2
                  
                
                −
                F
                (
                1
                +
                i
                
                  )
                  
                    2
                  
                
              
            
            
              
              
                
                +
                (
                C
                +
                F
                )
                (
                1
                +
                g
                )
                (
                1
                +
                i
                )
                −
                F
                (
                1
                +
                i
                )
              
            
            
              
              
                
                +
                (
                C
                +
                F
                )
                (
                1
                +
                g
                
                  )
                  
                    2
                  
                
                −
                F
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}n=3:PV(1+i)^{3}=&(C+F)(1+i)^{2}-F(1+i)^{2}\\&+(C+F)(1+g)(1+i)-F(1+i)\\&+(C+F)(1+g)^{2}-F\end{aligned}}}
  

Simplify the 3-year loan and generalize it at the end for n years. Start by combining the (C+F) and F terms

  
    
      
        
          
            
              
                P
                V
                (
                1
                +
                i
                
                  )
                  
                    3
                  
                
                =
              
              
                
                (
                C
                +
                F
                )
                (
                1
                +
                g
                
                  )
                  
                    2
                  
                
                
                  [
                  
                    
                      
                        (
                        
                          
                            
                              1
                              +
                              i
                            
                            
                              1
                              +
                              g
                            
                          
                        
                        )
                      
                      
                        2
                      
                    
                    +
                    
                      
                        
                          1
                          +
                          i
                        
                        
                          1
                          +
                          g
                        
                      
                    
                    +
                    1
                  
                  ]
                
              
            
            
              
              
                
                −
                F
                
                  [
                  
                    (
                    1
                    +
                    i
                    
                      )
                      
                        2
                      
                    
                    +
                    (
                    1
                    +
                    i
                    )
                    +
                    1
                  
                  ]
                
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}PV(1+i)^{3}=&(C+F)(1+g)^{2}\left[\left({\frac {1+i}{1+g}}\right)^{2}+{\frac {1+i}{1+g}}+1\right]\\&-F\left[(1+i)^{2}+(1+i)+1\right]\end{aligned}}}
  

Write these terms in summation notation

  
    
      
        
          
            
              
                P
                V
                (
                1
                +
                i
                
                  )
                  
                    3
                  
                
                =
              
              
                
                (
                C
                +
                F
                )
                (
                1
                +
                g
                
                  )
                  
                    2
                  
                
                
                  ∑
                  
                    k
                    =
                    0
                  
                  
                    2
                  
                
                
                  
                    (
                    
                      
                        
                          1
                          +
                          i
                        
                        
                          1
                          +
                          g
                        
                      
                    
                    )
                  
                  
                    k
                  
                
              
            
            
              
              
                
                −
                F
                
                  ∑
                  
                    k
                    =
                    0
                  
                  
                    2
                  
                
                (
                1
                +
                i
                
                  )
                  
                    k
                  
                
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}PV(1+i)^{3}=&(C+F)(1+g)^{2}\sum _{k=0}^{2}\left({\frac {1+i}{1+g}}\right)^{k}\\&-F\sum _{k=0}^{2}(1+i)^{k}\end{aligned}}}
  

Rewrite this is closed form using the geometric Series formula
  
    
      
        
          ∑
          
            k
            =
            0
          
          
            n
          
        
        
          r
          
            k
          
        
        =
        
          
            
              
                r
                
                  n
                  +
                  1
                
              
              −
              1
            
            
              r
              −
              1
            
          
        
      
    
    {\displaystyle \sum _{k=0}^{n}r^{k}={\frac {r^{n+1}-1}{r-1}}}
  

  
    
      
        
          
            
              
                P
                V
                (
                1
                +
                i
                
                  )
                  
                    3
                  
                
                =
              
              
                
                (
                C
                +
                F
                )
                (
                1
                +
                g
                
                  )
                  
                    2
                  
                
                
                  [
                  
                    
                      
                        
                          
                            (
                            
                              
                                
                                  1
                                  +
                                  i
                                
                                
                                  1
                                  +
                                  g
                                
                              
                            
                            )
                          
                          
                            3
                          
                        
                        −
                        1
                      
                      
                        
                          (
                          
                            
                              
                                1
                                +
                                i
                              
                              
                                1
                                +
                                g
                              
                            
                          
                          )
                        
                        −
                        1
                      
                    
                  
                  ]
                
              
            
            
              
              
                
                −
                F
                
                  [
                  
                    
                      
                        (
                        1
                        +
                        i
                        
                          )
                          
                            3
                          
                        
                        −
                        1
                      
                      
                        (
                        1
                        +
                        i
                        )
                        −
                        1
                      
                    
                  
                  ]
                
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}PV(1+i)^{3}=&(C+F)(1+g)^{2}\left[{\frac {\left({\frac {1+i}{1+g}}\right)^{3}-1}{\left({\frac {1+i}{1+g}}\right)-1}}\right]\\&-F\left[{\frac {(1+i)^{3}-1}{(1+i)-1}}\right]\end{aligned}}}
  

Multiply the top and bottom of the C+F term by (1+g) and cancel the 1's on the F term

  
    
      
        
          
            
              
                P
                V
                (
                1
                +
                i
                
                  )
                  
                    3
                  
                
                =
              
              
                
                (
                C
                +
                F
                )
                (
                1
                +
                g
                
                  )
                  
                    3
                  
                
                
                  [
                  
                    
                      
                        
                          
                            (
                            
                              
                                
                                  1
                                  +
                                  i
                                
                                
                                  1
                                  +
                                  g
                                
                              
                            
                            )
                          
                          
                            3
                          
                        
                        −
                        1
                      
                      
                        1
                        +
                        i
                        −
                        (
                        1
                        +
                        g
                        )
                      
                    
                  
                  ]
                
              
            
            
              
              
                
                −
                F
                
                  [
                  
                    
                      
                        (
                        1
                        +
                        i
                        
                          )
                          
                            3
                          
                        
                        −
                        1
                      
                      i
                    
                  
                  ]
                
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}PV(1+i)^{3}=&(C+F)(1+g)^{3}\left[{\frac {\left({\frac {1+i}{1+g}}\right)^{3}-1}{1+i-(1+g)}}\right]\\&-F\left[{\frac {(1+i)^{3}-1}{i}}\right]\end{aligned}}}
  

Multiply the 
  
    
      
        (
        1
        +
        g
        
          )
          
            3
          
        
      
    
    {\displaystyle (1+g)^{3}}
  
 on the C+F term through the square brackets.

  
    
      
        
          
            
              
                P
                V
                (
                1
                +
                i
                
                  )
                  
                    3
                  
                
                =
              
              
                
                (
                C
                +
                F
                )
                
                  [
                  
                    
                      
                        (
                        1
                        +
                        i
                        
                          )
                          
                            3
                          
                        
                        −
                        (
                        1
                        +
                        g
                        
                          )
                          
                            3
                          
                        
                      
                      
                        i
                        −
                        g
                      
                    
                  
                  ]
                
              
            
            
              
              
                
                −
                F
                
                  [
                  
                    
                      
                        (
                        1
                        +
                        i
                        
                          )
                          
                            3
                          
                        
                        −
                        1
                      
                      i
                    
                  
                  ]
                
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}PV(1+i)^{3}=&(C+F)\left[{\frac {(1+i)^{3}-(1+g)^{3}}{i-g}}\right]\\&-F\left[{\frac {(1+i)^{3}-1}{i}}\right]\end{aligned}}}
  

Divide both sides by 
  
    
      
        (
        1
        +
        i
        
          )
          
            3
          
        
      
    
    {\displaystyle (1+i)^{3}}
  
 and generalize by replacing the exponent 3 with n

  
    
      
        
          
            
              
                P
                V
                =
                
                  
                    
                      C
                      +
                      F
                    
                    
                      i
                      −
                      g
                    
                  
                
                
                  [
                  
                    1
                    −
                    
                      
                        (
                        
                          
                            
                              1
                              +
                              g
                            
                            
                              1
                              +
                              i
                            
                          
                        
                        )
                      
                      
                        n
                      
                    
                  
                  ]
                
                −
                
                  
                    F
                    i
                  
                
                
                  [
                  
                    1
                    −
                    
                      
                        1
                        
                          (
                          1
                          +
                          i
                          
                            )
                            
                              n
                            
                          
                        
                      
                    
                  
                  ]
                
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}PV={\frac {C+F}{i-g}}\left[1-\left({\frac {1+g}{1+i}}\right)^{n}\right]-{\frac {F}{i}}\left[1-{\frac {1}{(1+i)^{n}}}\right]\end{aligned}}}

### Perpetuity derivation

Without showing the formal derivation here, the perpetuity formula is derived from the annuity formula. Specifically, the term:

  
    
      
        
          (
          
            1
            −
            
              
                1
                
                  (
                  1
                  +
                  i
                  
                    )
                    
                      n
                    
                  
                
              
            
          
          )
        
      
    
    {\displaystyle \left({1-{1 \over {(1+i)^{n}}}}\right)}
  

can be seen to approach the value of 1 as n grows larger. At infinity, it is equal to 1, leaving 
  
    
      
        
          
            C
            i
          
        
      
    
    {\displaystyle {C \over i}}
  
 as the only term remaining.

## Continuous compounding

Rates are sometimes converted into the continuous compound interest rate equivalent because the continuous equivalent is more convenient (for example, more easily differentiated). Each of the formulas above may be restated in their continuous equivalents. For example, the present value at time 0 of a future payment at time t can be restated in the following way, where e is the base of the natural logarithm and r is the continuously compounded rate:

  
    
      
        
          PV
        
        =
        
          FV
        
        ⋅
        
          e
          
            −
            r
            t
          
        
      
    
    {\displaystyle {\text{PV}}={\text{FV}}\cdot e^{-rt}}
  

This can be generalized to discount rates that vary over time: instead of a constant discount rate r, one uses a function of time r(t). In that case, the discount factor, and thus the present value, of a cash flow at time T is given by the integral of the continuously compounded rate r(t):

  
    
      
        
          PV
        
        =
        
          FV
        
        ⋅
        exp
        ⁡
        
          (
          
            −
            
              ∫
              
                0
              
              
                T
              
            
            r
            (
            t
            )
            
            d
            t
          
          )
        
      
    
    {\displaystyle {\text{PV}}={\text{FV}}\cdot \exp \left(-\int _{0}^{T}r(t)\,dt\right)}
  

Indeed, a key reason for using continuous compounding is to simplify the analysis of varying discount rates and to allow one to use the tools of calculus. Further, for interest accrued and capitalized overnight (hence compounded daily), continuous compounding is a close approximation for the actual daily compounding. More sophisticated analysis includes the use of differential equations, as detailed below.

### Examples

Using continuous compounding yields the following formulas for various instruments:

Annuity

  
    
      
         
        P
        V
         
        =
         
        
          
            
              A
              (
              1
              −
              
                e
                
                  −
                  r
                  t
                
              
              )
            
            
              
                e
                
                  r
                
              
              −
              1
            
          
        
      
    
    {\displaystyle \ PV\ =\ {A(1-e^{-rt}) \over e^{r}-1}}
  

Perpetuity

  
    
      
         
        P
        V
         
        =
         
        
          
            A
            
              
                e
                
                  r
                
              
              −
              1
            
          
        
      
    
    {\displaystyle \ PV\ =\ {A \over e^{r}-1}}
  

Growing annuity

  
    
      
         
        P
        V
         
        =
         
        
          
            
              A
              
                e
                
                  −
                  g
                
              
              (
              1
              −
              
                e
                
                  −
                  (
                  r
                  −
                  g
                  )
                  t
                
              
              )
            
            
              
                e
                
                  (
                  r
                  −
                  g
                  )
                
              
              −
              1
            
          
        
      
    
    {\displaystyle \ PV\ =\ {Ae^{-g}(1-e^{-(r-g)t}) \over e^{(r-g)}-1}}
  

Growing perpetuity

  
    
      
         
        P
        V
         
        =
         
        
          
            
              A
              
                e
                
                  −
                  g
                
              
            
            
              
                e
                
                  (
                  r
                  −
                  g
                  )
                
              
              −
              1
            
          
        
      
    
    {\displaystyle \ PV\ =\ {Ae^{-g} \over e^{(r-g)}-1}}
  

Annuity with continuous payments

  
    
      
         
        P
        V
         
        =
         
        
          
            
              1
              −
              
                e
                
                  (
                  −
                  r
                  t
                  )
                
              
            
            r
          
        
      
    
    {\displaystyle \ PV\ =\ {1-e^{(-rt)} \over r}}
  

These formulas assume that payment A is made in the first payment period and annuity ends at time t.

## Differential equations

Ordinary and partial differential equations (ODEs and PDEs)—equations involving derivatives and one (respectively, multiple) variables—are ubiquitous in more advanced treatments of financial mathematics. While time value of money can be understood without using the framework of differential equations, the added sophistication sheds additional light on time value, and provides a simple introduction before considering more complicated and less familiar situations. This exposition follows (Carr & Flesaker 2006, pp. 6–7).
The fundamental change that the differential equation perspective brings is that, rather than computing a number (the present value now), one computes a function (the present value now or at any point in future). This function may then be analyzed (how does its value change over time?) or compared with other functions.
Formally, the statement that "value decreases over time" is given by defining the linear differential operator 
  
    
      
        
          
            L
          
        
      
    
    {\displaystyle {\mathcal {L}}}
  
 as:

  
    
      
        
          
            L
          
        
        :=
        −
        
          ∂
          
            t
          
        
        +
        r
        (
        t
        )
        .
      
    
    {\displaystyle {\mathcal {L}}:=-\partial _{t}+r(t).}
  

This states that value decreases (−) over time (∂t) at the discount rate (r(t)). Applied to a function, it yields:

  
    
      
        
          
            L
          
        
        f
        =
        −
        
          ∂
          
            t
          
        
        f
        (
        t
        )
        +
        r
        (
        t
        )
        f
        (
        t
        )
        .
      
    
    {\displaystyle {\mathcal {L}}f=-\partial _{t}f(t)+r(t)f(t).}
  

For an instrument whose payment stream is described by f(t), the value V(t) satisfies the inhomogeneous first-order ODE 
  
    
      
        
          
            L
          
        
        V
        =
        f
      
    
    {\displaystyle {\mathcal {L}}V=f}
  
 ("inhomogeneous" is because one has f rather than 0, and "first-order" is because one has first derivatives but no higher derivatives)—this encodes the fact that when any cash flow occurs, the value of the instrument changes by the value of the cash flow (if one receives a £10 coupon, the remaining value decreases by exactly £10).
The standard technique tool in the analysis of ODEs is Green's functions, from which other solutions can be built. In terms of time value of money, the Green's function (for the time value ODE) is the value of a bond paying £1 at a single point in time u; the value of any other stream of cash flows can then be obtained by taking combinations of this basic cash flow. In mathematical terms, this instantaneous cash flow is modeled as a Dirac delta function 
  
    
      
        
          δ
          
            u
          
        
        (
        t
        )
        :=
        δ
        (
        t
        −
        u
        )
        .
      
    
    {\displaystyle \delta _{u}(t):=\delta (t-u).}
  

The Green's function for the value at time t of a £1 cash flow at time u is

  
    
      
        b
        (
        t
        ;
        u
        )
        :=
        H
        (
        u
        −
        t
        )
        ⋅
        exp
        ⁡
        
          (
          
            −
            
              ∫
              
                t
              
              
                u
              
            
            r
            (
            v
            )
            
            d
            v
          
          )
        
      
    
    {\displaystyle b(t;u):=H(u-t)\cdot \exp \left(-\int _{t}^{u}r(v)\,dv\right)}
  

where H is the Heaviside step function. The notation "
  
    
      
        ;
        u
      
    
    {\displaystyle ;u}
  
" is to emphasize that u is a parameter (fixed in any instance—the time when the cash flow will occur), while t is a variable (time). In other words, future cash flows are exponentially discounted (exp) by the sum (integral, 
  
    
      
        
          
            ∫
          
        
      
    
    {\displaystyle \textstyle {\int }}
  
) of the future discount rates (
  
    
      
        
          
            
              ∫
              
                t
              
              
                u
              
            
          
        
      
    
    {\displaystyle \textstyle {\int _{t}^{u}}}
  
 for future, r(v) for discount rates), while past cash flows are worth 0 (
  
    
      
        H
        (
        u
        −
        t
        )
        =
        1
        
           if 
        
        t
        <
        u
        ,
        0
        
           if 
        
        t
        >
        u
      
    
    {\displaystyle H(u-t)=1{\text{ if }}t<u,0{\text{ if }}t>u}
  
), because they have already occurred. Note that the value at the moment of a cash flow is not well-defined—there is a discontinuity at that point, and one can use a convention (assume cash flows have already occurred, or not already occurred), or simply not define the value at that point.
In case the discount rate is constant, 
  
    
      
        r
        (
        v
        )
        ≡
        r
        ,
      
    
    {\displaystyle r(v)\equiv r,}
  
 this simplifies to

  
    
      
        b
        (
        t
        ;
        u
        )
        =
        H
        (
        u
        −
        t
        )
        ⋅
        
          e
          
            −
            (
            u
            −
            t
            )
            r
          
        
        =
        
          
            {
            
              
                
                  
                    e
                    
                      −
                      (
                      u
                      −
                      t
                      )
                      r
                    
                  
                
                
                  t
                  <
                  u
                
              
              
                
                  0
                
                
                  t
                  >
                  u
                  ,
                
              
            
            
          
        
      
    
    {\displaystyle b(t;u)=H(u-t)\cdot e^{-(u-t)r}={\begin{cases}e^{-(u-t)r}&t<u\\0&t>u,\end{cases}}}
  

where 
  
    
      
        (
        u
        −
        t
        )
      
    
    {\displaystyle (u-t)}
  
 is "time remaining until cash flow".
Thus for a stream of cash flows f(u) ending by time T (which can be set to 
  
    
      
        T
        =
        +
        ∞
      
    
    {\displaystyle T=+\infty }
  
 for no time horizon) the value at time t, 
  
    
      
        V
        (
        t
        ;
        T
        )
      
    
    {\displaystyle V(t;T)}
  
 is given by combining the values of these individual cash flows:

  
    
      
        V
        (
        t
        ;
        T
        )
        =
        
          ∫
          
            t
          
          
            T
          
        
        f
        (
        u
        )
        b
        (
        t
        ;
        u
        )
        
        d
        u
        .
      
    
    {\displaystyle V(t;T)=\int _{t}^{T}f(u)b(t;u)\,du.}
  

This formalizes time value of money to future values of cash flows with varying discount rates, and is the basis of many formulas in financial mathematics, such as the Black–Scholes formula with varying interest rates.
