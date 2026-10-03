# Rule of 72

<!-- https://en.wikipedia.org/wiki/Rule_of_72 | revision 1375555714 -->

In finance, the rule of 72, the rule of 70 and the rule of 69.3 are methods for estimating an investment's doubling time. The rule number (e.g., 72) is divided by the interest percentage per period (usually years) to obtain the approximate number of periods required for doubling. Although scientific calculators and spreadsheet programs have functions to find the accurate doubling time, the rules are useful for mental calculations or when only a basic calculator is available.
These rules apply to exponential growth and are therefore used for compound interest as opposed to simple interest calculations. They can also be used for decay to obtain a halving time. The choice of number is mostly a matter of preference: 69 is more accurate for continuous compounding, while 72 works well in common interest situations and is more easily divisible.
There are a number of variations to the rules that improve accuracy. For periodic compounding, the exact doubling time for an interest rate of r percent per period is

  
    
      
        t
        =
        
          
            
              ln
              ⁡
              (
              2
              )
            
            
              ln
              ⁡
              (
              1
              +
              r
              
                /
              
              100
              )
            
          
        
        ≈
        
          
            72
            r
          
        
        ,
      
    
    {\displaystyle t={\frac {\ln(2)}{\ln(1+r/100)}}\approx {\frac {72}{r}},}
  

where t is the number of periods required. The formula above can be used for more than calculating the doubling time. If one wants to know the tripling time, for example, replace the constant 2 in the numerator with 3. As another example, if one wants to know the number of periods it takes for the initial value to rise by 35%, replace the constant 2 with 1.35.

## Using the rule to estimate compounding periods

To estimate the number of periods required to double an original investment, divide the most convenient "rule-quantity" by the expected growth rate, expressed as a percentage.

For instance, if you were to invest $100 with compounding interest at a rate of 9% per annum, the rule of 72 gives 72/9 = 8 years required for the investment to be worth $200; an exact calculation gives ln(2)/ln(1+0.09) = 8.0432 years.
Similarly, to determine the time it takes for the value of money to halve at a given rate, divide the rule quantity by that rate.

To determine the time for money's buying power to halve, financiers divide the rule-quantity by the inflation rate. Thus at 3.5% inflation using the rule of 70, it should take approximately 70/3.5 = 20 years for the value of a unit of currency to halve.
To estimate the impact of additional fees on financial policies (e.g., loading and expense charges on variable universal life insurance investment portfolios), divide 72 by the fee. For example, if the Universal Life policy charges an annual 3% fee over and above the cost of the underlying investment fund, then the total account value will be cut to 50% in 72 / 3 = 24 years, and then to 25% of the value in 48 years, compared to holding exactly the same investment outside the policy.

## Choice of rule

The value 72 is a convenient choice of numerator, since it has many small divisors: 1, 2, 3, 4, 6, 8, 9, and 12. It provides a good approximation for annual compounding, and for compounding at typical rates (from 6% to 10%); the approximations are less accurate at higher interest rates.
For continuous compounding, 69 gives accurate results for any rate, since ln(2) is about 69.3%; see derivation below. Since daily compounding is close enough to continuous compounding, for most purposes 69, 69.3 or 70 are better than 72 for daily compounding. For lower annual rates than those above, 69.3 would also be more accurate than 72. For higher annual rates, 78 is more accurate.

Note: The most accurate value on each row is in bold.

## History

An early reference to the rule is in the Summa de arithmetica (Venice, 1494. Fol. 181, n. 44) of Luca Pacioli (1445–1514). He presents the rule in a discussion regarding the estimation of the doubling time of an investment, but does not derive or explain the rule, and it is thus assumed that the rule predates Pacioli by some time.

 A voler sapere ogni quantità a tanto per 100 l'anno, in quanti anni sarà tornata doppia tra utile e capitale, tieni per regola 72, a mente, il quale sempre partirai per l'interesse, e quello che ne viene, in tanti anni sarà raddoppiato. Esempio: Quando l'interesse è a 6 per 100 l'anno, dico che si parta 72 per 6; ne vien 12, e in 12 anni sarà raddoppiato il capitale. (emphasis added).
Roughly translated:

In wanting to know of any capital, at a given yearly percentage, in how many years it will double adding the interest to the capital, keep as a rule [the number] 72 in mind, which you will always divide by the interest, and what results, in that many years it will be doubled. Example: When the interest is 6 percent per year, I say that one divides 72 by 6; 12 results, and in 12 years the capital will be doubled.

## Derivation

### Periodic compounding

For periodic compounding, future value is given by:

  
    
      
        F
        V
        =
        P
        V
        ⋅
        (
        1
        +
        r
        
          /
        
        100
        
          )
          
            t
          
        
      
    
    {\displaystyle FV=PV\cdot (1+r/100)^{t}}
  

where 
  
    
      
        P
        V
      
    
    {\displaystyle PV}
  
 is the present value, 
  
    
      
        t
      
    
    {\displaystyle t}
  
 is the number of time periods, and 
  
    
      
        r
      
    
    {\displaystyle r}
  
 stands for the interest rate per time period.
The future value is double the present value when:

  
    
      
        F
        V
        =
        2
        ⋅
        P
        V
      
    
    {\displaystyle FV=2\cdot PV}
  

which is the following condition:

  
    
      
        (
        1
        +
        r
        
          /
        
        100
        
          )
          
            t
          
        
        =
        2
        
      
    
    {\displaystyle (1+r/100)^{t}=2\,}
  

This equation is easily solved for 
  
    
      
        t
      
    
    {\displaystyle t}
  
:

  
    
      
        
          
            
              
                ln
                ⁡
                (
                (
                1
                +
                r
                
                  /
                
                100
                
                  )
                  
                    t
                  
                
                )
              
              
                
                =
                ln
                ⁡
                2
              
            
            
              
                t
                ⋅
                ln
                ⁡
                (
                1
                +
                r
                
                  /
                
                100
                )
              
              
                
                =
                ln
                ⁡
                2
              
            
            
              
                t
              
              
                
                =
                
                  
                    
                      ln
                      ⁡
                      2
                    
                    
                      ln
                      ⁡
                      (
                      1
                      +
                      r
                      
                        /
                      
                      100
                      )
                    
                  
                
                .
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}\ln((1+r/100)^{t})&=\ln 2\\t\cdot \ln(1+r/100)&=\ln 2\\t&={\frac {\ln 2}{\ln(1+r/100)}}.\end{aligned}}}
  

A simple rearrangement shows

  
    
      
        
          
            
              ln
              ⁡
              2
            
            
              ln
              ⁡
              (
              1
              +
              r
              
                /
              
              100
              )
            
          
        
        =
        
          
            
              ln
              ⁡
              2
            
            
              r
              
                /
              
              100
            
          
        
        ⋅
        
          
            
              r
              
                /
              
              100
            
            
              ln
              ⁡
              (
              1
              +
              r
              
                /
              
              100
              )
            
          
        
        .
      
    
    {\displaystyle {\frac {\ln 2}{\ln(1+r/100)}}={\frac {\ln 2}{r/100}}\cdot {\frac {r/100}{\ln(1+r/100)}}.}
  

If 
  
    
      
        r
        
          /
        
        100
      
    
    {\displaystyle r/100}
  
 is small, then 
  
    
      
        ln
        ⁡
        (
        1
        +
        r
        
          /
        
        100
        )
      
    
    {\displaystyle \ln(1+r/100)}
  
 approximately equals 
  
    
      
        r
        
          /
        
        100
      
    
    {\displaystyle r/100}
  
 (this is the first term in the Taylor series). That is, the latter factor grows slowly when 
  
    
      
        r
      
    
    {\displaystyle r}
  
 is close to zero.
Call this latter factor 
  
    
      
        (
        r
        
          /
        
        100
        )
        
          /
        
        ln
        ⁡
        (
        1
        +
        r
        
          /
        
        100
        )
        =
        f
        (
        r
        )
      
    
    {\displaystyle (r/100)/\ln(1+r/100)=f(r)}
  
. The function 
  
    
      
        f
        (
        r
        )
      
    
    {\displaystyle f(r)}
  
 is shown to be accurate in the approximation of 
  
    
      
        t
      
    
    {\displaystyle t}
  
 for a small, positive interest rate when 
  
    
      
        r
        =
        8
      
    
    {\displaystyle r=8}
  
 (see derivation below). 
  
    
      
        f
        (
        8
        )
        ≈
        1.039
      
    
    {\displaystyle f(8)\approx 1.039}
  
, and we therefore approximate time 
  
    
      
        t
      
    
    {\displaystyle t}
  
 as:

  
    
      
        t
        (
        r
        )
        =
        
          
            
              ln
              ⁡
              2
            
            
              r
              
                /
              
              100
            
          
        
        ⋅
        f
        (
        8
        )
        ≈
        
          
            0.72
            
              r
              
                /
              
              100
            
          
        
        =
        
          
            72
            r
          
        
        .
      
    
    {\displaystyle t(r)={\frac {\ln 2}{r/100}}\cdot f(8)\approx {\frac {0.72}{r/100}}={\frac {72}{r}}.}
  

This approximation increases in accuracy as the compounding of interest becomes continuous (see derivation below).
In order to derive a more precise adjustment, it is noted that 
  
    
      
        ln
        ⁡
        (
        1
        +
        r
        
          /
        
        100
        )
      
    
    {\displaystyle \ln(1+r/100)}
  
 is more closely approximated by 
  
    
      
        r
        
          /
        
        100
        −
        
          
            
              1
              2
            
          
        
        (
        r
        
          /
        
        100
        
          )
          
            2
          
        
      
    
    {\displaystyle r/100-{\tfrac {1}{2}}(r/100)^{2}}
  
 (using the second term in the Taylor series). 
  
    
      
        0.693
        
          /
        
        
          (
          
            r
            
              /
            
            100
            −
            
              
                
                  1
                  2
                
              
            
            (
            r
            
              /
            
            100
            
              )
              
                2
              
            
          
          )
        
      
    
    {\displaystyle 0.693/\left(r/100-{\tfrac {1}{2}}(r/100)^{2}\right)}
  
 can then be further simplified by Taylor approximations:

  
    
      
        
          
            
              
                t
                (
                r
                )
                =
                

                
              
              
                
                  
                    0.693
                    
                      r
                      
                        /
                      
                      100
                      −
                      
                        
                          
                            1
                            2
                          
                        
                      
                      (
                      r
                      
                        /
                      
                      100
                      
                        )
                        
                          2
                        
                      
                    
                  
                
                =
                
                  
                    69.3
                    
                      r
                      −
                      
                        r
                        
                          2
                        
                      
                      
                        /
                      
                      200
                    
                  
                
                =
                
                  
                    69.3
                    r
                  
                
                
                  
                    1
                    
                      1
                      −
                      r
                      
                        /
                      
                      200
                    
                  
                
                ≈
                
                  
                    69.3
                    r
                  
                
                (
                1
                +
                r
                
                  /
                
                200
                )
                =
                
                  
                    69.3
                    r
                  
                
                +
                
                  
                    69.3
                    200
                  
                
              
            
            
              
                t
                (
                r
                )
                =
                

                
              
              
                
                  
                    69.3
                    r
                  
                
                +
                0.3465.
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}t(r)={}&{\frac {0.693}{r/100-{\tfrac {1}{2}}(r/100)^{2}}}={\frac {69.3}{r-r^{2}/200}}={\frac {69.3}{r}}{\frac {1}{1-r/200}}\approx {\frac {69.3}{r}}(1+r/200)={\frac {69.3}{r}}+{\frac {69.3}{200}}\\[8pt]t(r)={}&{\frac {69.3}{r}}+0.3465.\end{aligned}}}
  

Replacing the 
  
    
      
        r
      
    
    {\displaystyle r}
  
 in 
  
    
      
        r
        
          /
        
        200
      
    
    {\displaystyle r/200}
  
 with 7.79 gives 72 in the numerator. This shows that the rule of 72 is most accurate for periodically compounded interests around 8 %. Similarly, replacing the 
  
    
      
        r
      
    
    {\displaystyle r}
  
 in 
  
    
      
        r
        
          /
        
        200
      
    
    {\displaystyle r/200}
  
 with 2.02 gives 70 in the numerator, showing the rule of 70 is most accurate for periodically compounded interests around 2 %.
As a sophisticated but elegant mathematical method to achieve a more accurate fit, the function 
  
    
      
        t
        (
        r
        )
        =
        ln
        ⁡
        (
        2
        )
        
          /
        
        ln
        ⁡
        (
        1
        +
        r
        
          /
        
        100
        )
      
    
    {\displaystyle t(r)=\ln(2)/\ln(1+r/100)}
  
 is developed in a Laurent series at the point 
  
    
      
        r
        =
        0
      
    
    {\displaystyle r=0}
  
. With the first two terms one obtains:

  
    
      
        
          
            
              
                t
                (
                r
                )
                ≈
                

                
              
              
                
                  
                    
                      100
                      ⋅
                      ln
                      ⁡
                      2
                    
                    r
                  
                
                +
                
                  
                    
                      ln
                      ⁡
                      2
                    
                    2
                  
                
              
            
            
              
                t
                (
                r
                )
                ≈
                

                
              
              
                
                  
                    69.3147
                    r
                  
                
                +
                0.346574
                ,
                
                   or rounded:
                
              
            
            
              
                t
                (
                r
                )
                ≈
                

                
              
              
                
                  
                    69
                    r
                  
                
                +
                0.35.
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}t(r)\approx {}&{\frac {100\cdot \ln 2}{r}}+{\frac {\ln 2}{2}}\\[8pt]t(r)\approx {}&{\frac {69.3147}{r}}+0.346574,{\text{ or rounded:}}\\[8pt]t(r)\approx {}&{\frac {69}{r}}+0.35.\end{aligned}}}

### Continuous compounding

In the case of theoretical continuous compounding, the derivation is simpler and yields to a more accurate rule:

  
    
      
        
          
            
              
                exp
                ⁡
                
                  (
                  
                    
                      
                        r
                        100
                      
                    
                    ⋅
                    t
                  
                  )
                
              
              
                
                =
                
                  
                    
                      F
                      V
                    
                    
                      P
                      V
                    
                  
                
                =
                2
              
            
            
              
                
                  
                    r
                    100
                  
                
                ⋅
                t
              
              
                
                =
                ln
                ⁡
                2
              
            
            
              
                t
              
              
                
                =
                
                  
                    
                      100
                      ⋅
                      ln
                      ⁡
                      2
                    
                    r
                  
                
                ≈
                
                  
                    69.3147
                    r
                  
                
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}\exp \left({\frac {r}{100}}\cdot t\right)&={\frac {FV}{PV}}=2\\[6pt]{\frac {r}{100}}\cdot t&=\ln 2\\[6pt]t&={\frac {100\cdot \ln 2}{r}}\approx {\frac {69.3147}{r}}\end{aligned}}}
