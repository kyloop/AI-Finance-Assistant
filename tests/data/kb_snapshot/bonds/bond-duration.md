# Duration (finance)

<!-- https://en.wikipedia.org/wiki/Duration_(finance) | revision 1376217597 -->

In finance, duration is a measure of how the price of a fixed-income instrument responds to a change in interest rates. It is used to compare rate risk across bonds and to construct hedges, and is often paired with convexity and the price value of a basis point. Duration-based estimates work best for small, parallel shifts in the yield curve.
Macaulay duration is the present-value-weighted average time to the cash flows and links payment timing to interest-rate risk. Modified duration expresses the first-order percentage price change for a stated compounding convention. When yields vary by maturity, Fisher–Weil duration discounts each payment at its own spot rate; Key rate duration isolates sensitivity at selected maturities; and effective or option-adjusted duration estimates sensitivity for instruments with cash flows that depend on rates.

## History and terminology

### Early development

The idea of duration was set out by Frederick Macaulay in a National Bureau of Economic Research study in 1938. He defined a time-weighted average of the present values of cash flows and used it to summarize a bond’s timing and rate sensitivity. In actuarial work, Frank Redington linked duration to immunization and added convexity to improve protection against larger moves in yields.

### Extensions

With a term structure of rates, discounting each payment at its own spot rate preserves the present-value weighting and gives a first-order hedge for a small parallel shift of the zero curve. This is the Fisher–Weil formulation. To handle non-parallel moves, practitioners report localised sensitivities at selected maturities using key rate durations. Option features led to effective or option-adjusted duration, estimated by small curve shifts in a pricing model while the option-adjusted spread is held constant. These uses are standard in index and reporting methodologies.

### Terminology and market usage

In modern texts “duration” can mean different but related measures. Macaulay duration is the present-value-weighted average time to payment. Modified duration is the first-order percentage change in price for a small change in the stated yield and compounding. Money or dollar duration is 
  
    
      
        P
        ×
        
          D
          
            mod
          
        
      
    
    {\displaystyle P\times D_{\text{mod}}}
  
. DV01, PV01 and PVBP express the price change per basis point. In the UK gilts market, modified duration is often called “volatility” in index guides and factsheets.

## Definition and intuition

This section uses the following conventions. A fixed-income instrument has 
  
    
      
        n
      
    
    {\displaystyle n}
  
 cash flows 
  
    
      
        
          C
          
            i
          
        
      
    
    {\displaystyle C_{i}}
  
 at times 
  
    
      
        
          t
          
            i
          
        
      
    
    {\displaystyle t_{i}}
  
 (in years). The last cash flow includes the bond redemption. The nominal yield to maturity is 
  
    
      
        y
      
    
    {\displaystyle y}
  
 with 
  
    
      
        m
      
    
    {\displaystyle m}
  
 compounding periods per year. The price as a function of yield is

  
    
      
        P
        (
        y
        )
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          
            
              C
              
                i
              
            
            
              
                
                  (
                
              
              1
              +
              y
              
                /
              
              m
              
                
                  
                    )
                  
                
                
                  m
                  
                    t
                    
                      i
                    
                  
                
              
            
          
        
        
        .
      
    
    {\displaystyle P(y)\;=\;\sum _{i=1}^{n}{\frac {C_{i}}{{\bigl (}1+y/m{\bigr )}^{mt_{i}}}}\,.}
  

Define the present values 
  
    
      
        
          
            P
            V
          
          
            i
          
        
        =
        
          C
          
            i
          
        
        
        (
        1
        +
        y
        
          /
        
        m
        
          )
          
            −
            m
            
              t
              
                i
              
            
          
        
      
    
    {\displaystyle \mathrm {PV} _{i}=C_{i}\,(1+y/m)^{-mt_{i}}}
  
 and weights 
  
    
      
        
          w
          
            i
          
        
        =
        
          
            P
            V
          
          
            i
          
        
        
          /
        
        P
        (
        y
        )
      
    
    {\displaystyle w_{i}=\mathrm {PV} _{i}/P(y)}
  
, which sum to one. Macaulay duration is the present-value-weighted average time to the cash flows:

  
    
      
        
          D
          
            Mac
          
        
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          t
          
            i
          
        
        
        
          w
          
            i
          
        
        
        =
        
        
          
            
              
                ∑
                
                  i
                
              
              
                t
                
                  i
                
              
              
              
                
                  P
                  V
                
                
                  i
                
              
            
            
              
                ∑
                
                  i
                
              
              
                
                  P
                  V
                
                
                  i
                
              
            
          
        
        
        .
      
    
    {\displaystyle D_{\text{Mac}}\;=\;\sum _{i=1}^{n}t_{i}\,w_{i}\;=\;{\frac {\sum _{i}t_{i}\,\mathrm {PV} _{i}}{\sum _{i}\mathrm {PV} _{i}}}\,.}
  

It summarises payment timing. For a zero-coupon bond that pays only at time 
  
    
      
        T
      
    
    {\displaystyle T}
  
, 
  
    
      
        
          D
          
            Mac
          
        
        =
        T
      
    
    {\displaystyle D_{\text{Mac}}=T}
  
. For a level-coupon bond it lies between zero and final maturity.
To link timing to price sensitivity, differentiate price with respect to yield. Modified duration is the first-order sensitivity of price to a small parallel change in 
  
    
      
        y
      
    
    {\displaystyle y}
  
:

  
    
      
        
          D
          
            mod
          
        
        
        =
        
        −
        
        
          
            1
            
              P
              (
              y
              )
            
          
        
        
        
          
            
              
                d
              
              P
            
            
              
                d
              
              y
            
          
        
        
        =
        
        
          
            
              D
              
                Mac
              
            
            
              1
              +
              y
              
                /
              
              m
            
          
        
        
        .
      
    
    {\displaystyle D_{\text{mod}}\;=\;-\,{\frac {1}{P(y)}}\,{\frac {\mathrm {d} P}{\mathrm {d} y}}\;=\;{\frac {D_{\text{Mac}}}{1+y/m}}\,.}
  

For a small change 
  
    
      
        Δ
        y
      
    
    {\displaystyle \Delta y}
  
 the approximation is

  
    
      
        
          
            
              Δ
              P
            
            P
          
        
        
        ≈
        
        −
        
        
          D
          
            mod
          
        
        
        Δ
        y
        
        .
      
    
    {\displaystyle {\frac {\Delta P}{P}}\;\approx \;-\,D_{\text{mod}}\,\Delta y\,.}
  

With continuous compounding at rate 
  
    
      
        r
      
    
    {\displaystyle r}
  
, pricing is 
  
    
      
        P
        (
        r
        )
        =
        
          ∑
          
            i
          
        
        
          C
          
            i
          
        
        
        
          e
          
            −
            r
            
              t
              
                i
              
            
          
        
      
    
    {\displaystyle P(r)=\sum _{i}C_{i}\,e^{-rt_{i}}}
  
 and

  
    
      
        
          D
          
            cont
          
        
        
        =
        
        −
        
        
          
            1
            
              P
              (
              r
              )
            
          
        
        
        
          
            
              
                d
              
              P
            
            
              
                d
              
              r
            
          
        
        
        =
        
        
          ∑
          
            i
          
        
        
          t
          
            i
          
        
        
        
          w
          
            i
          
        
        
        =
        
        
          D
          
            Mac
          
        
        
        .
      
    
    {\displaystyle D_{\text{cont}}\;=\;-\,{\frac {1}{P(r)}}\,{\frac {\mathrm {d} P}{\mathrm {d} r}}\;=\;\sum _{i}t_{i}\,w_{i}\;=\;D_{\text{Mac}}\,.}
  

These relations keep notation consistent across compounding conventions.

### Analogy

Imagine a long plank set along a timeline that begins today. Each future cash flow is a small weight placed on the plank at the cash flow time. Heavier weights correspond to cash flows with larger present values. If you slide a single support under the plank to the point where the system balances, that balance point is the time-centre of all the weights.
If most of the weight lies far along the plank the balance point sits further from today and the bond is more sensitive to a change in yields. If weight is concentrated near the start through high coupons or short maturity the balance point moves inward and sensitivity falls. This time-centre corresponds to Macaulay duration.
Now tilt the ground by a very small amount. The plank drops a little and, for such a small tilt, the vertical drop at the balance point is almost exactly proportional to the tilt. That proportional response mirrors modified duration, which gives the first-order change in price for a small change in yield.
With a larger tilt the motion does not remain proportional because the plank follows a curve. The extra curvature in the response explains convexity and shows why the second-order term matters for larger yield moves or for cash-flow patterns that make the curve more pronounced.
If the ground does not tilt uniformly but is raised or lowered under specific years, different parts of the plank move by different amounts. That picture matches shifts in the term structure and motivates measures such as Fisher–Weil duration and key-rate durations, where sensitivity depends on which maturities move.

### Worked examples

Zero-coupon bond
Assume maturity 
  
    
      
        T
        =
        3
      
    
    {\displaystyle T=3}
  
 years and yield 
  
    
      
        y
        =
        5
        %
      
    
    {\displaystyle y=5\%}
  
 with annual compounding (
  
    
      
        m
        =
        1
      
    
    {\displaystyle m=1}
  
). Then

  
    
      
        
          D
          
            Mac
          
        
        =
        T
        =
        3
        ,
        
        
          D
          
            mod
          
        
        =
        
          
            T
            
              1
              +
              y
              
                /
              
              m
            
          
        
        =
        
          
            3
            
              1
              +
              0.05
            
          
        
        ≈
        2.857
        
        .
      
    
    {\displaystyle D_{\text{Mac}}=T=3,\qquad D_{\text{mod}}={\frac {T}{1+y/m}}={\frac {3}{1+0.05}}\approx 2.857\,.}
  

A 25-basis-point change in yield (
  
    
      
        Δ
        y
        =
        0.0025
      
    
    {\displaystyle \Delta y=0.0025}
  
) gives

  
    
      
        
          
            
              Δ
              P
            
            P
          
        
        ≈
        −
        
        
          D
          
            mod
          
        
        
        Δ
        y
        ≈
        −
        
        2.857
        ×
        0.0025
        ≈
        −
        
        0.71
        %
        
        .
      
    
    {\displaystyle {\frac {\Delta P}{P}}\approx -\,D_{\text{mod}}\,\Delta y\approx -\,2.857\times 0.0025\approx -\,0.71\%\,.}
  

Level-coupon bond
Consider a two-year bond with a 5% annual coupon and yield 
  
    
      
        y
        =
        6
        %
      
    
    {\displaystyle y=6\%}
  
 (annual compounding). Present values of the cash flows:

  
    
      
        
          
            P
            V
          
          
            1
          
        
        =
        
          
            5
            1.06
          
        
        ≈
        4.717
        ,
        
        
          
            P
            V
          
          
            2
          
        
        =
        
          
            105
            
              1.06
              
                2
              
            
          
        
        ≈
        93.450
        
        .
      
    
    {\displaystyle \mathrm {PV} _{1}={\frac {5}{1.06}}\approx 4.717,\qquad \mathrm {PV} _{2}={\frac {105}{1.06^{2}}}\approx 93.450\,.}
  

Price and cash-flow weights:

  
    
      
        P
        =
        
          
            P
            V
          
          
            1
          
        
        +
        
          
            P
            V
          
          
            2
          
        
        ≈
        98.167
        ,
        
        
          w
          
            1
          
        
        =
        
          
            
              
                P
                V
              
              
                1
              
            
            P
          
        
        ≈
        0.048
        ,
        
        
          w
          
            2
          
        
        =
        
          
            
              
                P
                V
              
              
                2
              
            
            P
          
        
        ≈
        0.952
        
        .
      
    
    {\displaystyle P=\mathrm {PV} _{1}+\mathrm {PV} _{2}\approx 98.167,\qquad w_{1}={\frac {\mathrm {PV} _{1}}{P}}\approx 0.048,\quad w_{2}={\frac {\mathrm {PV} _{2}}{P}}\approx 0.952\,.}
  

Macaulay duration:

  
    
      
        
          D
          
            Mac
          
        
        =
        1
        ⋅
        
          w
          
            1
          
        
        +
        2
        ⋅
        
          w
          
            2
          
        
        ≈
        1
        ⋅
        0.048
        +
        2
        ⋅
        0.952
        ≈
        1.952
        
        .
      
    
    {\displaystyle D_{\text{Mac}}=1\cdot w_{1}+2\cdot w_{2}\approx 1\cdot 0.048+2\cdot 0.952\approx 1.952\,.}
  

Modified duration:

  
    
      
        
          D
          
            mod
          
        
        =
        
          
            
              D
              
                Mac
              
            
            
              1
              +
              y
            
          
        
        =
        
          
            1.952
            1.06
          
        
        ≈
        1.842
        
        .
      
    
    {\displaystyle D_{\text{mod}}={\frac {D_{\text{Mac}}}{1+y}}={\frac {1.952}{1.06}}\approx 1.842\,.}
  

A 50-basis-point rise in yield (
  
    
      
        Δ
        y
        =
        0.005
      
    
    {\displaystyle \Delta y=0.005}
  
) implies

  
    
      
        
          
            
              Δ
              P
            
            P
          
        
        ≈
        −
        
        
          D
          
            mod
          
        
        
        Δ
        y
        ≈
        −
        
        1.842
        ×
        0.005
        ≈
        −
        
        0.92
        %
        
        .
      
    
    {\displaystyle {\frac {\Delta P}{P}}\approx -\,D_{\text{mod}}\,\Delta y\approx -\,1.842\times 0.005\approx -\,0.92\%\,.}

### Term-structure intuition

When the term structure is not flat, discounting each payment at its own zero-coupon rate preserves the weighting idea in Macaulay’s statistic and leads to the Fisher–Weil refinement for parallel shifts of the zero-rate curve. Non-parallel movements are analysed with key-rate durations in later sections.

## Formal derivation

Let a fixed-income instrument pay cash flows 
  
    
      
        
          C
          
            i
          
        
      
    
    {\displaystyle C_{i}}
  
 at times 
  
    
      
        
          t
          
            i
          
        
      
    
    {\displaystyle t_{i}}
  
 (years), 
  
    
      
        i
        =
        1
        ,
        …
        ,
        n
      
    
    {\displaystyle i=1,\ldots ,n}
  
. The last cash flow 
  
    
      
        
          C
          
            n
          
        
      
    
    {\displaystyle C_{n}}
  
 at time 
  
    
      
        
          t
          
            n
          
        
      
    
    {\displaystyle t_{n}}
  
 includes the redemption. With a yield to maturity 
  
    
      
        y
      
    
    {\displaystyle y}
  
 compounded 
  
    
      
        m
      
    
    {\displaystyle m}
  
 times per year, the price as a function of yield is

  
    
      
        P
        (
        y
        )
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          
            
              C
              
                i
              
            
            
              
                
                  (
                
              
              1
              +
              y
              
                /
              
              m
              
                
                  
                    )
                  
                
                
                  m
                  
                    t
                    
                      i
                    
                  
                
              
            
          
        
        .
      
    
    {\displaystyle P(y)\;=\;\sum _{i=1}^{n}{\frac {C_{i}}{{\bigl (}1+y/m{\bigr )}^{mt_{i}}}}.}
  

Write the present values 
  
    
      
        
          
            P
            V
          
          
            i
          
        
        =
        
          C
          
            i
          
        
        
        (
        1
        +
        y
        
          /
        
        m
        
          )
          
            −
            m
            
              t
              
                i
              
            
          
        
      
    
    {\displaystyle \mathrm {PV} _{i}=C_{i}\,(1+y/m)^{-mt_{i}}}
  
 and define weights 
  
    
      
        
          w
          
            i
          
        
        =
        
          
            P
            V
          
          
            i
          
        
        
          /
        
        P
        (
        y
        )
      
    
    {\displaystyle w_{i}=\mathrm {PV} _{i}/P(y)}
  
 so that 
  
    
      
        
          ∑
          
            i
          
        
        
          w
          
            i
          
        
        =
        1
      
    
    {\displaystyle \sum _{i}w_{i}=1}
  
.
Differentiating 
  
    
      
        P
        (
        y
        )
      
    
    {\displaystyle P(y)}
  
 with respect to 
  
    
      
        y
      
    
    {\displaystyle y}
  
 gives

  
    
      
        
          
            
              
                d
              
              P
            
            
              
                d
              
              y
            
          
        
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          C
          
            i
          
        
        
        
          
            
              d
            
            
              
                d
              
              y
            
          
        
        
          
            (
          
        
        1
        +
        
          
            y
            m
          
        
        
          
            
              )
            
          
          
            −
            m
            
              t
              
                i
              
            
          
        
        
        =
        
        −
        
        
          
            1
            
              1
              +
              y
              
                /
              
              m
            
          
        
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          t
          
            i
          
        
        
        
          
            P
            V
          
          
            i
          
        
        .
      
    
    {\displaystyle {\frac {\mathrm {d} P}{\mathrm {d} y}}\;=\;\sum _{i=1}^{n}C_{i}\,{\frac {\mathrm {d} }{\mathrm {d} y}}{\Bigl (}1+{\frac {y}{m}}{\Bigr )}^{-mt_{i}}\;=\;-\,{\frac {1}{1+y/m}}\,\sum _{i=1}^{n}t_{i}\,\mathrm {PV} _{i}.}
  

Hence the modified duration is

  
    
      
        
          D
          
            mod
          
        
        (
        y
        )
        
        ≡
        
        −
        
        
          
            1
            
              P
              (
              y
              )
            
          
        
        
        
          
            
              
                d
              
              P
            
            
              
                d
              
              y
            
          
        
        
        =
        
        
          
            
              
                ∑
                
                  i
                
              
              
                t
                
                  i
                
              
              
              
                
                  P
                  V
                
                
                  i
                
              
            
            
              P
              (
              y
              )
            
          
        
        
        
          
            1
            
              1
              +
              y
              
                /
              
              m
            
          
        
        
        =
        
        
          
            
              D
              
                Mac
              
            
            
              
              1
              +
              y
              
                /
              
              m
              
            
          
        
        ,
      
    
    {\displaystyle D_{\text{mod}}(y)\;\equiv \;-\,{\frac {1}{P(y)}}\,{\frac {\mathrm {d} P}{\mathrm {d} y}}\;=\;{\frac {\sum _{i}t_{i}\,\mathrm {PV} _{i}}{P(y)}}\,{\frac {1}{1+y/m}}\;=\;{\frac {D_{\text{Mac}}}{\,1+y/m\,}},}
  

where the Macaulay duration is the present-value-weighted average time

  
    
      
        
          D
          
            Mac
          
        
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          t
          
            i
          
        
        
        
          w
          
            i
          
        
        
        =
        
        
          
            
              
                ∑
                
                  i
                
              
              
                t
                
                  i
                
              
              
              
                
                  P
                  V
                
                
                  i
                
              
            
            
              
                ∑
                
                  i
                
              
              
                
                  P
                  V
                
                
                  i
                
              
            
          
        
        .
      
    
    {\displaystyle D_{\text{Mac}}\;=\;\sum _{i=1}^{n}t_{i}\,w_{i}\;=\;{\frac {\sum _{i}t_{i}\,\mathrm {PV} _{i}}{\sum _{i}\mathrm {PV} _{i}}}.}
  

For a small change 
  
    
      
        Δ
        y
      
    
    {\displaystyle \Delta y}
  
, the first-order approximation is

  
    
      
        
          
            
              Δ
              P
            
            P
          
        
        
        ≈
        
        −
        
        
          D
          
            mod
          
        
        
        Δ
        y
        .
      
    
    {\displaystyle {\frac {\Delta P}{P}}\;\approx \;-\,D_{\text{mod}}\,\Delta y.}
  

These relations assume fixed cash flows and a small parallel move in the quoted yield.

### Continuous compounding

If pricing uses a continuously compounded rate 
  
    
      
        r
      
    
    {\displaystyle r}
  
, then

  
    
      
        P
        (
        r
        )
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          C
          
            i
          
        
        
        
          
            e
          
          
            −
            r
            
              t
              
                i
              
            
          
        
        ,
        
        
          
            
              
                d
              
              P
            
            
              
                d
              
              r
            
          
        
        
        =
        
        −
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          t
          
            i
          
        
        
        
          C
          
            i
          
        
        
        
          
            e
          
          
            −
            r
            
              t
              
                i
              
            
          
        
        .
      
    
    {\displaystyle P(r)\;=\;\sum _{i=1}^{n}C_{i}\,\mathrm {e} ^{-rt_{i}},\qquad {\frac {\mathrm {d} P}{\mathrm {d} r}}\;=\;-\,\sum _{i=1}^{n}t_{i}\,C_{i}\,\mathrm {e} ^{-rt_{i}}.}
  

With weights 
  
    
      
        
          w
          
            i
          
        
        (
        r
        )
        =
        
          C
          
            i
          
        
        
        
          
            e
          
          
            −
            r
            
              t
              
                i
              
            
          
        
        
          /
        
        P
        (
        r
        )
      
    
    {\displaystyle w_{i}(r)=C_{i}\,\mathrm {e} ^{-rt_{i}}/P(r)}
  
,

  
    
      
        
          D
          
            m
            o
            d
          
        
        (
        r
        )
        =
        −
        
        
          
            1
            
              P
              (
              r
              )
            
          
        
        
        
          
            
              
                d
              
              P
            
            
              
                d
              
              r
            
          
        
        
        =
        
        
          ∑
          
            i
          
        
        
          t
          
            i
          
        
        
        
          w
          
            i
          
        
        (
        r
        )
        
        =
        
        
          D
          
            Mac
          
        
        .
      
    
    {\displaystyle D_{mod}(r)=-\,{\frac {1}{P(r)}}\,{\frac {\mathrm {d} P}{\mathrm {d} r}}\;=\;\sum _{i}t_{i}\,w_{i}(r)\;=\;D_{\text{Mac}}.}
  

Thus modified and Macaulay duration coincide under continuous compounding.

### Term-structure version (Fisher–Weil)

When the term structure is not flat, discount each cash flow at its own zero-coupon rate 
  
    
      
        z
        (
        t
        )
      
    
    {\displaystyle z(t)}
  
. For a parallel shift 
  
    
      
        a
      
    
    {\displaystyle a}
  
 to the zero curve,

  
    
      
        P
        (
        a
        )
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          C
          
            i
          
        
        exp
        
        
          
            (
          
        
        −
        
        
          ∫
          
            0
          
          
            
              t
              
                i
              
            
          
        
        [
        z
        (
        u
        )
        +
        a
        ]
        
        
          d
        
        u
        
          
            )
          
        
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          C
          
            i
          
        
        
        
          
            e
          
          
            −
            a
            
              t
              
                i
              
            
          
        
        
        
          
            e
          
          
            −
            
              ∫
              
                0
              
              
                
                  t
                  
                    i
                  
                
              
            
            z
            (
            u
            )
            
            
              d
            
            u
          
        
        .
      
    
    {\displaystyle P(a)\;=\;\sum _{i=1}^{n}C_{i}\exp \!{\Bigl (}-\!\int _{0}^{t_{i}}[z(u)+a]\,\mathrm {d} u{\Bigr )}\;=\;\sum _{i=1}^{n}C_{i}\,\mathrm {e} ^{-at_{i}}\,\mathrm {e} ^{-\int _{0}^{t_{i}}z(u)\,\mathrm {d} u}.}
  

Define spot-discounted values 
  
    
      
        
          
            
              
                
                  P
                  V
                
                ~
              
            
          
          
            i
          
        
        =
        
          C
          
            i
          
        
        
        
          
            e
          
          
            −
            
              ∫
              
                0
              
              
                
                  t
                  
                    i
                  
                
              
            
            z
            (
            u
            )
            
            
              d
            
            u
          
        
      
    
    {\displaystyle {\widetilde {\mathrm {PV} }}_{i}=C_{i}\,\mathrm {e} ^{-\int _{0}^{t_{i}}z(u)\,\mathrm {d} u}}
  
 and weights 
  
    
      
        
          
            
              
                w
                ~
              
            
          
          
            i
          
        
        =
        
          
            
              
                
                  P
                  V
                
                ~
              
            
          
          
            i
          
        
        
          /
        
        P
        (
        0
        )
      
    
    {\displaystyle {\tilde {w}}_{i}={\widetilde {\mathrm {PV} }}_{i}/P(0)}
  
. Differentiating at 
  
    
      
        a
        =
        0
      
    
    {\displaystyle a=0}
  
 gives

  
    
      
        −
        
        
          
            1
            
              P
              (
              0
              )
            
          
        
        
        
          
            
              ∂
              P
            
            
              ∂
              a
            
          
        
        
          
            
              |
            
          
          
            a
            =
            0
          
        
        
        =
        
        
          
            
              
                ∑
                
                  i
                
              
              
                t
                
                  i
                
              
              
              
                
                  
                    
                      
                        P
                        V
                      
                      ~
                    
                  
                
                
                  i
                
              
            
            
              
                ∑
                
                  i
                
              
              
                
                  
                    
                      
                        P
                        V
                      
                      ~
                    
                  
                
                
                  i
                
              
            
          
        
        
        =
        
        
          ∑
          
            i
          
        
        
          t
          
            i
          
        
        
        
          
            
              
                w
                ~
              
            
          
          
            i
          
        
        
        =
        
        
          D
          
            FW
          
        
        ,
      
    
    {\displaystyle -\,{\frac {1}{P(0)}}\,{\frac {\partial P}{\partial a}}{\Big |}_{a=0}\;=\;{\frac {\sum _{i}t_{i}\,{\widetilde {\mathrm {PV} }}_{i}}{\sum _{i}{\widetilde {\mathrm {PV} }}_{i}}}\;=\;\sum _{i}t_{i}\,{\tilde {w}}_{i}\;=\;D_{\text{FW}},}
  

the Fisher–Weil duration, which preserves present-value weighting with a full term structure.

### Money duration and DV01

Money duration
        
        
        =
        
        P
        ×
        
          D
          
            mod
          
        
        ,
        
        
          DV01
        
        
        =
        
        
          PVBP
        
        
        =
        
        P
        ×
        
          D
          
            mod
          
        
        ×
        
          10
          
            −
            4
          
        
        .
      
    
    {\displaystyle {\text{Money duration}}\;=\;P\times D_{\text{mod}},\qquad {\text{DV01}}\;=\;{\text{PVBP}}\;=\;P\times D_{\text{mod}}\times 10^{-4}.}
  

These identities are widely used in portfolio reporting and regulation.

### Properties and portfolio duration

For fixed, positive cash flows:

Duration rises with final maturity and falls as the yield rises.
Higher coupons shorten duration relative to a zero-coupon with the same maturity.
Portfolio duration is the present-value–weighted average of component durations:

  
    
      
        
          D
          
            port
          
        
        =
        
          
            
              
                
                  ∑
                  
                    j
                  
                
                
                  P
                  
                    j
                  
                
                
                  D
                  
                    j
                  
                
              
              
                
                  ∑
                  
                    j
                  
                
                
                  P
                  
                    j
                  
                
              
            
          
        
        
        .
      
    
    {\displaystyle D_{\text{port}}={\dfrac {\sum _{j}P_{j}D_{j}}{\sum _{j}P_{j}}}\,.}
  

For a small yield change 
  
    
      
        Δ
        y
      
    
    {\displaystyle \Delta y}
  
, 
  
    
      
        Δ
        P
        
          /
        
        P
        ≈
        −
        
          D
          
            mod
          
        
        
        Δ
        y
      
    
    {\displaystyle \Delta P/P\approx -D_{\text{mod}}\,\Delta y}
  
.

## Macaulay duration

Named for Frederick Macaulay, Macaulay duration is the present-value-weighted average time to a bond’s cash flows. It treats each payment’s time as a “location” and weights it by that payment’s present value. The denominator equals the bond’s price.

### Definition

Let cash flows be 
  
    
      
        
          C
          
            i
          
        
      
    
    {\displaystyle C_{i}}
  
 at times 
  
    
      
        
          t
          
            i
          
        
      
    
    {\displaystyle t_{i}}
  
 (years), 
  
    
      
        i
        =
        1
        ,
        …
        ,
        n
      
    
    {\displaystyle i=1,\ldots ,n}
  
. Write present values 
  
    
      
        
          
            P
            V
          
          
            i
          
        
      
    
    {\displaystyle \mathrm {PV} _{i}}
  
 and price 
  
    
      
        P
      
    
    {\displaystyle P}
  
 as

  
    
      
        P
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          
            P
            V
          
          
            i
          
        
        ,
        
        
          
            P
            V
          
          
            i
          
        
        
        =
        
        
          C
          
            i
          
        
        
        (
        1
        +
        y
        
          /
        
        m
        
          )
          
            −
            m
            
              t
              
                i
              
            
          
        
        .
      
    
    {\displaystyle P\;=\;\sum _{i=1}^{n}\mathrm {PV} _{i},\qquad \mathrm {PV} _{i}\;=\;C_{i}\,(1+y/m)^{-mt_{i}}.}
  

Define weights 
  
    
      
        
          w
          
            i
          
        
        =
        
          
            P
            V
          
          
            i
          
        
        
          /
        
        P
      
    
    {\displaystyle w_{i}=\mathrm {PV} _{i}/P}
  
, which sum to one. Macaulay duration is

  
    
      
        
          D
          
            Mac
          
        
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          t
          
            i
          
        
        
        
          w
          
            i
          
        
        
        =
        
        
          
            
              
                ∑
                
                  i
                  =
                  1
                
                
                  n
                
              
              
                t
                
                  i
                
              
              
              
                
                  P
                  V
                
                
                  i
                
              
            
            
              
                ∑
                
                  i
                  =
                  1
                
                
                  n
                
              
              
                
                  P
                  V
                
                
                  i
                
              
            
          
        
        .
      
    
    {\displaystyle D_{\text{Mac}}\;=\;\sum _{i=1}^{n}t_{i}\,w_{i}\;=\;{\frac {\sum _{i=1}^{n}t_{i}\,\mathrm {PV} _{i}}{\sum _{i=1}^{n}\mathrm {PV} _{i}}}.}

### Basic properties

For instruments with fixed, positive cash flows and times 
  
    
      
        
          t
          
            1
          
        
        ≤
        ⋯
        ≤
        
          t
          
            n
          
        
      
    
    {\displaystyle t_{1}\leq \cdots \leq t_{n}}
  
,

  
    
      
        
          t
          
            1
          
        
        
        ≤
        
        
          D
          
            Mac
          
        
        
        ≤
        
        
          t
          
            n
          
        
        ,
      
    
    {\displaystyle t_{1}\;\leq \;D_{\text{Mac}}\;\leq \;t_{n},}
  

with equality only when there is a single payment. Thus a zero-coupon bond maturing at 
  
    
      
        T
      
    
    {\displaystyle T}
  
 has 
  
    
      
        
          D
          
            Mac
          
        
        =
        T
      
    
    {\displaystyle D_{\text{Mac}}=T}
  
, while a level-coupon bond has 
  
    
      
        
          D
          
            Mac
          
        
      
    
    {\displaystyle D_{\text{Mac}}}
  
 strictly between the first coupon date and final maturity.

### Relation to other duration measures

Under a quoted yield to maturity 
  
    
      
        y
      
    
    {\displaystyle y}
  
 compounded 
  
    
      
        m
      
    
    {\displaystyle m}
  
 times per year,

  
    
      
        
          D
          
            mod
          
        
        
        =
        
        
          
            
              D
              
                Mac
              
            
            
              
              1
              +
              y
              
                /
              
              m
              
            
          
        
        ,
      
    
    {\displaystyle D_{\text{mod}}\;=\;{\frac {D_{\text{Mac}}}{\,1+y/m\,}},}
  

which links the time-average concept to the first-order price sensitivity used in hedging. If discounting uses spot rates 
  
    
      
        z
        (
        t
        )
      
    
    {\displaystyle z(t)}
  
 at each maturity, the same weighted-average form with spot-discounted present values gives the Fisher–Weil duration; when the curve is flat and conventions match, it equals 
  
    
      
        
          D
          
            Mac
          
        
      
    
    {\displaystyle D_{\text{Mac}}}
  
.

### Duration and weighted average life (WAL)

Weighted-average life averages payment times using principal amounts only and does not discount. Macaulay duration averages using present values and includes both coupons and principal. For an interest-only or bullet structure with small coupons the two figures can be close, yet they differ in general because duration reflects discounting and coupon timing.

## Modified duration

Modified duration is a price-sensitivity measure. It is the percentage derivative of price with respect to yield, so it captures the first-order change in price for a small parallel change in the quoted yield.

  
    
      
        
          D
          
            mod
          
        
        (
        y
        )
        
        ≡
        
        −
        
        
          
            1
            
              P
              (
              y
              )
            
          
        
        
        
          
            
              
                d
              
              P
            
            
              
                d
              
              y
            
          
        
        
        =
        
        −
        
        
          
            
              
                d
              
              
              ln
              ⁡
              P
              (
              y
              )
            
            
              
                d
              
              y
            
          
        
        
        .
      
    
    {\displaystyle D_{\text{mod}}(y)\;\equiv \;-\,{\frac {1}{P(y)}}\,{\frac {\mathrm {d} P}{\mathrm {d} y}}\;=\;-\,{\frac {\mathrm {d} \,\ln P(y)}{\mathrm {d} y}}\,.}

### Continuous compounding

When the yield is expressed with continuous compounding at rate 
  
    
      
        r
      
    
    {\displaystyle r}
  
, the Macaulay duration equals the modified duration:

  
    
      
        P
        (
        r
        )
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          C
          
            i
          
        
        
        
          
            e
          
          
            −
            r
            
              t
              
                i
              
            
          
        
        ,
        
        −
        
        
          
            1
            
              P
              (
              r
              )
            
          
        
        
        
          
            
              
                d
              
              P
            
            
              
                d
              
              r
            
          
        
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          t
          
            i
          
        
        
        
          
            
              
                C
                
                  i
                
              
              
              
                
                  e
                
                
                  −
                  r
                  
                    t
                    
                      i
                    
                  
                
              
            
            
              P
              (
              r
              )
            
          
        
        
        =
        
        
          D
          
            Mac
          
        
        
        ,
      
    
    {\displaystyle P(r)\;=\;\sum _{i=1}^{n}C_{i}\,\mathrm {e} ^{-rt_{i}},\qquad -\,{\frac {1}{P(r)}}\,{\frac {\mathrm {d} P}{\mathrm {d} r}}\;=\;\sum _{i=1}^{n}t_{i}\,{\frac {C_{i}\,\mathrm {e} ^{-rt_{i}}}{P(r)}}\;=\;D_{\text{Mac}}\,,}
  

so under continuous compounding 
  
    
      
        
          D
          
            mod
          
        
        =
        
          D
          
            Mac
          
        
      
    
    {\displaystyle D_{\text{mod}}=D_{\text{Mac}}}
  
.

### Periodic compounding

In most markets yields are quoted with 
  
    
      
        m
      
    
    {\displaystyle m}
  
 compounding periods per year. With 
  
    
      
        y
      
    
    {\displaystyle y}
  
 the nominal yield to maturity and 
  
    
      
        P
        (
        y
        )
        =
        
          ∑
          
            i
          
        
        
          C
          
            i
          
        
        (
        1
        +
        y
        
          /
        
        m
        
          )
          
            −
            m
            
              t
              
                i
              
            
          
        
      
    
    {\displaystyle P(y)=\sum _{i}C_{i}(1+y/m)^{-mt_{i}}}
  
,

  
    
      
        
          D
          
            mod
          
        
        
        =
        
        
          
            
              D
              
                Mac
              
            
            
              
              1
              +
              y
              
                /
              
              m
              
            
          
        
        
        .
      
    
    {\displaystyle D_{\text{mod}}\;=\;{\frac {D_{\text{Mac}}}{\,1+y/m\,}}\,.}
  

This relates the time-average concept to the elasticity used for hedging and reporting.

### Units and the small-change formula

Macaulay duration has units of time. Modified duration is unitless and acts as a semi-elasticity. For a small change 
  
    
      
        Δ
        y
      
    
    {\displaystyle \Delta y}
  
 in the annual yield (in decimal form),

  
    
      
        
          
            
              Δ
              P
            
            P
          
        
        
        ≈
        
        −
        
        
          D
          
            mod
          
        
        
        Δ
        y
        
        .
      
    
    {\displaystyle {\frac {\Delta P}{P}}\;\approx \;-\,D_{\text{mod}}\,\Delta y\,.}
  

For a 100-basis-point change 
  
    
      
        (
        Δ
        y
        =
        0.01
        )
      
    
    {\displaystyle (\Delta y=0.01)}
  
 the approximate percentage price change is 
  
    
      
        
          D
          
            mod
          
        
        ×
        1
        %
      
    
    {\displaystyle D_{\text{mod}}\times 1\%}
  
.

### Non-fixed cash flows

Macaulay duration applies to fixed cash flows. For instruments whose cash flows change when rates move, such as callable or prepayable securities, sensitivity is estimated by effective duration using small up and down shifts of the curve within a pricing model. In those cases 
  
    
      
        
          D
          
            mod
          
        
      
    
    {\displaystyle D_{\text{mod}}}
  
 is replaced by the effective measure for risk reporting and hedging.

### Finite yield changes and convexity

Modified duration is defined as a derivative, so accuracy declines as the yield change grows. For larger shocks the second-order term (convexity) improves the approximation, or the instrument can be repriced directly at the new yield or curve. The “Convexity and second-order effects” section gives the standard quadratic approximation and a worked example.

## Convexity and second-order effects

Convexity refines duration by capturing the curvature of the price–yield relationship. Let 
  
    
      
        P
        (
        y
        )
      
    
    {\displaystyle P(y)}
  
 be the price as a function of yield 
  
    
      
        y
      
    
    {\displaystyle y}
  
 expressed as a decimal. The modified duration is 
  
    
      
        
          D
          
            mod
          
        
        =
        −
        
          
            
              1
              P
            
          
        
        
          
            
              
                
                  d
                
                P
              
              
                
                  d
                
                y
              
            
          
        
      
    
    {\displaystyle D_{\text{mod}}=-{\tfrac {1}{P}}{\tfrac {\mathrm {d} P}{\mathrm {d} y}}}
  
. Convexity is the second derivative normalised by price:

  
    
      
        C
        
        =
        
        
          
            1
            P
          
        
        
        
          
            
              
                
                  d
                
                
                  2
                
              
              P
            
            
              
                d
              
              
                y
                
                  2
                
              
            
          
        
        
        .
      
    
    {\displaystyle C\;=\;{\frac {1}{P}}\,{\frac {\mathrm {d} ^{2}P}{\mathrm {d} y^{2}}}\,.}
  

For a small change in yield 
  
    
      
        Δ
        y
      
    
    {\displaystyle \Delta y}
  
, the second-order approximation to the proportional price change is

  
    
      
        
          
            
              Δ
              P
            
            P
          
        
        
        ≈
        
        −
        
        
          D
          
            mod
          
        
        
        Δ
        y
        
        +
        
        
          
            
              1
              2
            
          
        
        
        C
        
        (
        Δ
        y
        
          )
          
            2
          
        
        
        .
      
    
    {\displaystyle {\frac {\Delta P}{P}}\;\approx \;-\,D_{\text{mod}}\,\Delta y\;+\;{\tfrac {1}{2}}\,C\,(\Delta y)^{2}\,.}
  

It is common to also quote dollar convexity, the coefficient on 
  
    
      
        (
        Δ
        y
        
          )
          
            2
          
        
      
    
    {\displaystyle (\Delta y)^{2}}
  
 in price units:

  
    
      
        
          
            
              1
              2
            
          
        
        
        P
        
        C
        
        .
      
    
    {\displaystyle {\tfrac {1}{2}}\,P\,C\,.}
  

These relations follow from a Taylor expansion of 
  
    
      
        P
        (
        y
        )
      
    
    {\displaystyle P(y)}
  
 and are standard in fixed-income texts.

### When convexity matters

The convexity term is small for very small yield moves. It becomes material for larger moves, for long-maturity or low-coupon instruments, and when securities exhibit negative convexity due to embedded options. In those cases effective duration and effective convexity are estimated by finite differences from an option-pricing model.

## Key rate duration and term-structure measures

Parallel shifts are a useful simplification, but yields rarely move that way. To analyse non-parallel changes in the term structure, practitioners measure sensitivity at selected maturities and combine those sensitivities to match an observed move in the curve.
Let 
  
    
      
        V
      
    
    {\displaystyle V}
  
 be the price and let 
  
    
      
        
          z
          
            i
          
        
      
    
    {\displaystyle z_{i}}
  
 denote the spot rate at key maturity 
  
    
      
        
          τ
          
            i
          
        
      
    
    {\displaystyle \tau _{i}}
  
. The key rate duration at 
  
    
      
        
          τ
          
            i
          
        
      
    
    {\displaystyle \tau _{i}}
  
 is the price sensitivity to a change in that spot rate with the rest of the curve held fixed:

  
    
      
        
          
            K
            R
            D
          
          
            i
          
        
        
        =
        
        −
        
        
          
            1
            V
          
        
        
        
          
            
              ∂
              V
            
            
              ∂
              
                z
                
                  i
                
              
            
          
        
        
        .
      
    
    {\displaystyle \mathrm {KRD} _{i}\;=\;-\,{\frac {1}{V}}\,{\frac {\partial V}{\partial z_{i}}}\,.}
  

In practice it is estimated by a small bump-and-reprice at the key maturity, using the chosen curve interpolation to localise the shift:

  
    
      
        
          
            K
            R
            D
          
          
            i
          
        
        
        ≈
        
        
          
            
              
                V
                
                  i
                
                
                  −
                
              
              −
              
                V
                
                  i
                
                
                  +
                
              
            
            
              2
              
              V
              
              Δ
              z
            
          
        
        ,
        
        
          V
          
            i
          
          
            ±
          
        
        
        =
        
        
          price with 
        
        
          z
          
            i
          
        
        
           shifted by 
        
        ±
        Δ
        z
        
           and other nodes fixed
        
        
        .
      
    
    {\displaystyle \mathrm {KRD} _{i}\;\approx \;{\frac {V_{i}^{-}-V_{i}^{+}}{2\,V\,\Delta z}},\qquad V_{i}^{\pm }\;=\;{\text{price with }}z_{i}{\text{ shifted by }}\pm \Delta z{\text{ and other nodes fixed}}\,.}
  

The corresponding key rate DV01 is the price change per basis point at that maturity:

  
    
      
        
          
            K
            R
            D
            
              -
            
            D
            V
            01
          
          
            i
          
        
        
        =
        
        V
        ×
        
          
            K
            R
            D
          
          
            i
          
        
        ×
        
          10
          
            −
            4
          
        
        
        .
      
    
    {\displaystyle \mathrm {KRD{\text{-}}DV01} _{i}\;=\;V\times \mathrm {KRD} _{i}\times 10^{-4}\,.}
  

With a consistent interpolation, a pure parallel shift can be represented as a combination of equal key rate bumps. The sum of the key rate DV01s then agrees with the parallel DV01 implied by modified duration:

  
    
      
        
          ∑
          
            i
          
        
        
          
            K
            R
            D
            
              -
            
            D
            V
            01
          
          
            i
          
        
        
        ≈
        
        V
        ×
        
          D
          
            mod
          
        
        ×
        
          10
          
            −
            4
          
        
        
        .
      
    
    {\displaystyle \sum _{i}\mathrm {KRD{\text{-}}DV01} _{i}\;\approx \;V\times D_{\text{mod}}\times 10^{-4}\,.}
  

Key rate duration connects to Fisher–Weil duration. A uniform shift in all spot rates yields the Fisher–Weil price change, while selective shifts at individual maturities reveal how risk is distributed across the cash flow timeline.

### Practical notes

The choice of key maturities and the curve interpolation method affect estimates. Using the same interpolation for pricing and shocks improves internal consistency.
Shifts should be small so that first-order approximations remain accurate. Larger shocks require convexity or direct repricing.
Report both the set of key rate DV01s and the parallel DV01. The totals provide a cross-check that the key rate bucket exposures add up to the overall rate risk.
In many benchmark methodologies key rate DV01s are computed under a constant option-adjusted spread. Under that convention the sum of the key rate DV01s is approximately equal to the option-adjusted duration for a parallel move, which provides a practical cross-check on reported exposures.

## Alternative and related measures

This section covers measures that complement modified duration and help compare risks across bonds and portfolios.

### Fisher–Weil duration

This measure discounts each cash flow at its own spot rate rather than a single yield to maturity. With zero rates 
  
    
      
        z
        (
        t
        )
      
    
    {\displaystyle z(t)}
  
 and cash flows 
  
    
      
        
          C
          
            i
          
        
      
    
    {\displaystyle C_{i}}
  
 at times 
  
    
      
        
          t
          
            i
          
        
      
    
    {\displaystyle t_{i}}
  
,

  
    
      
        P
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          C
          
            i
          
        
        
        
          
            e
          
          
            −
            
              ∫
              
                0
              
              
                
                  t
                  
                    i
                  
                
              
            
            z
            (
            u
            )
            
            
              d
            
            u
          
        
        ,
        
        
          D
          
            FW
          
        
        
        =
        
        
          
            1
            P
          
        
        
        
          ∑
          
            i
            =
            1
          
          
            n
          
        
        
          t
          
            i
          
        
        
        
          C
          
            i
          
        
        
        
          
            e
          
          
            −
            
              ∫
              
                0
              
              
                
                  t
                  
                    i
                  
                
              
            
            z
            (
            u
            )
            
            
              d
            
            u
          
        
        .
      
    
    {\displaystyle P\;=\;\sum _{i=1}^{n}C_{i}\,\mathrm {e} ^{-\int _{0}^{t_{i}}z(u)\,\mathrm {d} u},\qquad D_{\text{FW}}\;=\;{\frac {1}{P}}\,\sum _{i=1}^{n}t_{i}\,C_{i}\,\mathrm {e} ^{-\int _{0}^{t_{i}}z(u)\,\mathrm {d} u}.}
  

For a small parallel shift of the zero curve, 
  
    
      
        
          D
          
            FW
          
        
      
    
    {\displaystyle D_{\text{FW}}}
  
 gives the first-order price response. It equals Macaulay duration when the curve is flat and compounding is consistent.

### Money duration, DV01 and PVBP

Money duration (also called dollar duration) expresses sensitivity in price units per one-unit change in yield:

  
    
      
        
          Money duration
        
        
        =
        
        P
        ×
        
          D
          
            mod
          
        
        
        .
      
    
    {\displaystyle {\text{Money duration}}\;=\;P\times D_{\text{mod}}\,.}
  

The price value of a basis point (PVBP), also called DV01, is the price change for a one-basis-point parallel move in yield:

  
    
      
        
          PVBP
        
        
        =
        
        
          DV01
        
        
        =
        
        P
        ×
        
          D
          
            mod
          
        
        ×
        
          10
          
            −
            4
          
        
        
        .
      
    
    {\displaystyle {\text{PVBP}}\;=\;{\text{DV01}}\;=\;P\times D_{\text{mod}}\times 10^{-4}\,.}
  

Portfolio and risk reports often state aggregate rate risk in DV01 terms.

### Effective duration

When cash flows depend on rates, prices are taken from a model under small up and down shifts of the curve. The effective duration is estimated by a central difference:

  
    
      
        
          D
          
            eff
          
        
        
        ≈
        
        
          
            
              
                P
                
                  −
                
              
              −
              
                P
                
                  +
                
              
            
            
              2
              
              
                P
                
                  0
                
              
              
              Δ
              y
            
          
        
        ,
        
        
          P
          
            ±
          
        
        
        =
        
        
          model price with the curve shifted by 
        
        ±
        Δ
        y
        
        .
      
    
    {\displaystyle D_{\text{eff}}\;\approx \;{\frac {P_{-}-P_{+}}{2\,P_{0}\,\Delta y}},\qquad P_{\pm }\;=\;{\text{model price with the curve shifted by }}\pm \Delta y\,.}
  

Effective convexity is reported alongside this measure for option-affected instruments.

### Spread duration and OAS duration

For credit instruments, sensitivity is often measured to a parallel change in credit spread 
  
    
      
        s
      
    
    {\displaystyle s}
  
 over the reference curve, holding the underlying curve fixed:

  
    
      
        
          D
          
            spread
          
        
        
        =
        
        −
        
        
          
            1
            P
          
        
        
        
          
            
              ∂
              P
            
            
              ∂
              s
            
          
        
        ,
        
        
          SPV01
        
        
        =
        
        P
        ×
        
          D
          
            spread
          
        
        ×
        
          10
          
            −
            4
          
        
        
        .
      
    
    {\displaystyle D_{\text{spread}}\;=\;-\,{\frac {1}{P}}\,{\frac {\partial P}{\partial s}},\qquad {\text{SPV01}}\;=\;P\times D_{\text{spread}}\times 10^{-4}\,.}
  

When valuation uses an option-adjusted spread (OAS), the reported figure is the OAS duration, estimated by small bump-and-reprice shifts of the OAS within the pricing model.

### Sherman ratio

The Sherman ratio is a practitioner heuristic that relates the income on a bond or index to its interest-rate sensitivity. It is the annual yield per unit of duration, often interpreted as the parallel rise in yield over one year that would offset the income return.
Let 
  
    
      
        y
      
    
    {\displaystyle y}
  
 be the annual yield (in decimal) and 
  
    
      
        D
      
    
    {\displaystyle D}
  
 a duration measure such as modified duration or an option-adjusted duration. A common form is

  
    
      
        
          Sherman ratio
        
        
        =
        
        
          
            y
            D
          
        
        
        .
      
    
    {\displaystyle {\text{Sherman ratio}}\;=\;{\frac {y}{D}}\,.}
  

Using the small-change formula 
  
    
      
        Δ
        P
        
          /
        
        P
        ≈
        −
        D
        
        Δ
        y
      
    
    {\displaystyle \Delta P/P\approx -D\,\Delta y}
  
, the one-year break-even parallel rise that would erase income is approximately 
  
    
      
        Δ
        y
        ≈
        y
        
          /
        
        D
      
    
    {\displaystyle \Delta y\approx y/D}
  
. For example, an index with yield 
  
    
      
        2
        %
      
    
    {\displaystyle 2\%}
  
 and duration 
  
    
      
        10
      
    
    {\displaystyle 10}
  
 has a ratio of 
  
    
      
        0.20
      
    
    {\displaystyle 0.20}
  
, which suggests that a rise of about 20 basis points over a year would offset the income.
The ratio depends on the yield definition (for example yield-to-worst or an option-adjusted yield), on the chosen duration, and ignores convexity, roll-down and spread changes, so it is a rough guide rather than a formal risk measure.

### Carry and roll-down

In practice fixed-income returns over a horizon depend not only on price sensitivity but also on income and the shape of the term structure. “Carry” is the income an instrument earns if the curve does not move, and “roll-down” is the price effect from the bond or swap moving to a shorter maturity on an unchanged curve.
Let 
  
    
      
        y
      
    
    {\displaystyle y}
  
 denote the current annual yield and 
  
    
      
        D
      
    
    {\displaystyle D}
  
 and 
  
    
      
        C
      
    
    {\displaystyle C}
  
 the modified duration and convexity. Over a small horizon 
  
    
      
        h
      
    
    {\displaystyle h}
  
 years, a simple horizon-return approximation is

  
    
      
        
          Total return
        
        
        ≈
        
        y
        
        h
        
        +
        
        
          roll-down
        
        
        −
        
        D
        
        Δ
        y
        
        +
        
        
          
            
              1
              2
            
          
        
        
        C
        
        (
        Δ
        y
        
          )
          
            2
          
        
        ,
      
    
    {\displaystyle {\text{Total return}}\;\approx \;y\,h\;+\;{\text{roll-down}}\;-\;D\,\Delta y\;+\;{\tfrac {1}{2}}\,C\,(\Delta y)^{2},}
  

where 
  
    
      
        Δ
        y
      
    
    {\displaystyle \Delta y}
  
 is the parallel change in the relevant yield over the horizon. The roll-down term depends on the local slope of the curve and vanishes on a flat curve.

#### One-year breakeven move

A related rule of thumb is the parallel rise in yields over one year that would offset the income and roll-down:

  
    
      
        Δ
        
          y
          
            breakeven
          
        
        
        ≈
        
        
          
            
              y
              
              +
              
              
                roll-down (per year)
              
            
            D
          
        
        
        .
      
    
    {\displaystyle \Delta y_{\text{breakeven}}\;\approx \;{\frac {y\;+\;{\text{roll-down (per year)}}}{D}}\,.}
  

If roll-down is small this reduces to the Sherman-style ratio 
  
    
      
        y
        
          /
        
        D
      
    
    {\displaystyle y/D}
  
.

### Duration-times-spread (credit)

For credit instruments, managers often measure spread risk with duration-times-spread (DTS), defined as effective spread duration multiplied by the option-adjusted spread. DTS scales spread exposure by the current spread level and better reflects that spreads tend to move proportionally rather than in parallel.

  
    
      
        
          DTS
        
        
        =
        
        
          D
          
            spread
          
        
        ×
        
          spread
        
        
        .
      
    
    {\displaystyle {\text{DTS}}\;=\;D_{\text{spread}}\times {\text{spread}}\,.}
  

DTS is used in index construction, portfolio limits and risk reports alongside spread duration and DV01 for rates.

### “Spread per turn of duration” and spread breakeven

Another credit heuristic mirrors the Sherman ratio by comparing spread to duration. “Spread per turn of duration” (sometimes called spread breakeven) is

  
    
      
        
          
            spread
            
              D
              
                eff
              
            
          
        
        
        ,
      
    
    {\displaystyle {\frac {\text{spread}}{D_{\text{eff}}}}\,,}
  

interpreted as the parallel widening in spread that would offset one year of spread income on a static curve.
This is a quick valuation lens for comparing sectors or ratings buckets, but it ignores migration, default, convexity and curve shape effects, so it should be read as a rough guide rather than a risk model.

## Applications

Duration summarises interest rate risk in single bonds and in portfolios. In practice it is paired with convexity and key-rate measures when moves are large or non-parallel.

### Hedging and portfolio construction

Managers set a target DV01 for a portfolio and adjust it with liquid instruments such as government bonds, futures or interest rate swaps. They then shape exposure across maturities with key-rate DV01s so that risk is not concentrated at a single point on the curve. Barbell and bullet structures can share the same parallel DV01 yet differ in convexity and in key-rate exposure.

### Immunisation and asset–liability management

Immunisation matches the value and duration of assets to those of liabilities so that small parallel shifts leave the surplus approximately unchanged. Discounting each cash flow at its own spot rate yields the Fisher–Weil refinement for a given term structure. Pension funds and insurers apply these ideas in asset–liability management and monitor liability-relative DV01 and key-rate exposures.

### Index and benchmark management

Index providers publish duration, convexity and key-rate exposures for each index. These figures guide passive replication, risk budgeting and attribution, and allow portfolio DV01 and key-rate DV01s to be compared directly with those of a chosen benchmark. Many methodologies compute key-rate DV01s under a constant option-adjusted spread and note that their sum is close to the option-adjusted duration for a parallel move.

### Regulatory and risk reporting

Banks measure interest rate risk in the banking book using duration-based sensitivity of economic value and report exposures by tenor. Supervisory standards highlight limits of linear measures under large or non-parallel shocks and require complementary metrics and scenarios. Asset managers disclose portfolio DV01 and, where relevant, spread DV01 in regulatory filings.

### Using derivatives to shape duration

Swaps, futures and bond total-return swaps can raise or lower parallel DV01 or target key-rate buckets without trading underlying bonds. The choice depends on liquidity, balance-sheet use and basis risk between the derivative and the hedged cash flows.

### Practical cautions

Duration is a first-order tool. Large rate moves, curve reshaping, embedded options and spread changes can make duration-only hedges drift from their targets. In those cases practitioners add convexity, use key-rate and spread duration, or reprice directly in a model.

## Risk – duration as interest rate sensitivity

The primary use of modified duration is to summarise interest rate sensitivity. Thinking in yield terms allows comparisons across different instruments. The examples below use a 10-year final maturity with 5% nominal yield and semi-annual compounding.

Notes

† DV01 shown for the receive-fixed swap is the PV01 of the fixed leg per 1 bp for $100 notional at par. The sign depends on receive versus pay fixed.
All four instruments mature in 10 years, yet their sensitivities differ. The zero-coupon has the highest sensitivity and the annuity the lowest because cash flows arrive earlier. Modified duration provides a comparable percentage measure across the three bonds. For example, the zero-coupon’s value changes at about 9.76% per 100 bp, so a +1 bp move implies a price change of roughly −0.0976% (from $61.0271 to about $60.968).
When comparing equal notionals, DV01 gives the dollar change per 1 bp. DV01 is natural for swaps, where there is no initial price, as well as for bonds. The swap’s PV01 at par is close to the coupon bond’s DV01 because both reflect the present value of fixed-leg cash flows on the same curve. In portfolio terms, dollar convexity adds across holdings in the same way as DV01, which allows second-order effects to be summarised at portfolio level for a given shock size.
Modified duration measures the size of the parallel-rate sensitivity. It does not identify which part of the term structure drives the move. The annuity above has 
  
    
      
        
          D
          
            Mac
          
        
        ≈
        4.8
      
    
    {\displaystyle D_{\text{Mac}}\approx 4.8}
  
 years yet its cash flows extend to 10 years, so it remains sensitive to longer maturities. Sensitivity to specific maturities is captured by key rate durations.
For fixed cash flows, price changes arise from two sources:

Passage of time, which moves price toward par and is predictable.
Changes in the yield, from shifts in the benchmark curve and from spread changes.
The price–yield relationship is inverse. The duration term gives a linear approximation. For larger moves, adding convexity provides a quadratic correction, or the instrument can be repriced exactly at the new yield. The options analogue is the pair of first- and second-order Greeks, delta and gamma.

## Limitations and caveats

Duration is a first-order tool. It works best for small, parallel shifts in the term structure and for instruments with fixed cash flows. Outside those conditions it needs support from convexity, key-rate measures, spread measures and direct repricing in a model.

### First-order scope

The duration approximation comes from a linear term in a Taylor expansion of price in yield. As the shock grows the error increases and convexity matters. Practitioners add convexity or reprice directly when moves are large.

### Non-parallel curve moves

Market changes often mix level, slope and curvature. A single duration can misstate risk when the curve reshapes. Key-rate duration spreads exposure across maturities and aligns a hedge to the observed move.

### Cash-flow uncertainty and options

When cash flows vary with rates, such as for callable or prepayable securities, the price–yield curve can show negative convexity and the measured duration depends on model choices. Effective duration and effective convexity estimate sensitivity by small up and down shifts within the pricing model.

### Curve construction and interpolation

Fisher–Weil and key-rate measures require a spot-rate curve. The choice of instruments, bootstrapping and interpolation changes discount factors and hence measured sensitivities. Using one curve for both pricing and shocks improves internal consistency.

### Conventions and units

Reported numbers depend on the yield and compounding convention and on whether price is clean or dirty. Money duration equals price times modified duration under the stated convention. DV01 depends on the bumped quantity, for example a par rate, a zero rate or a yield to maturity. Comparisons should use a common convention and unit.

### Credit and basis considerations

Interest-rate duration does not capture credit-spread risk. Spread duration and spread PV01 measure sensitivity to changes in credit spreads with the underlying curve held fixed. Basis risk between the hedging instrument and the exposure, for example between a futures contract and a bond or between swaps and bonds of different issuers, can leave a hedge exposed even when parallel DV01 is matched.

## Bond formulas

For a level-coupon bond with nominal yield to maturity 
  
    
      
        y
      
    
    {\displaystyle y}
  
 compounded 
  
    
      
        m
      
    
    {\displaystyle m}
  
 times per year, write the per-period yield 
  
    
      
        r
        =
        y
        
          /
        
        m
      
    
    {\displaystyle r=y/m}
  
, the number of coupon periods 
  
    
      
        N
      
    
    {\displaystyle N}
  
 (assumed an integer), the per-period coupon 
  
    
      
        C
      
    
    {\displaystyle C}
  
, the face value 
  
    
      
        F
      
    
    {\displaystyle F}
  
, and the price

  
    
      
        P
        
        =
        
        C
        
        
          
            
              1
              −
              (
              1
              +
              r
              
                )
                
                  −
                  N
                
              
            
            r
          
        
        
        +
        
        F
        
        (
        1
        +
        r
        
          )
          
            −
            N
          
        
        
        .
      
    
    {\displaystyle P\;=\;C\,{\frac {1-(1+r)^{-N}}{r}}\;+\;F\,(1+r)^{-N}\,.}
  

The Macaulay duration (in years) has the closed form

  
    
      
        
          D
          
            Mac
          
        
        
        =
        
        
          
            1
            
              m
              
              P
            
          
        
        
        
          [
          
            C
            
            
              
                
                  1
                  +
                  r
                
                
                  r
                  
                    2
                  
                
              
            
            
              
                (
              
            
            1
            −
            (
            1
            +
            r
            
              )
              
                −
                N
              
            
            
              
                )
              
            
            
            −
            
            
              
                
                  N
                  
                  C
                
                r
              
            
            
            (
            1
            +
            r
            
              )
              
                −
                N
              
            
            
            +
            
            N
            
            F
            
            (
            1
            +
            r
            
              )
              
                −
                N
              
            
          
          ]
        
        .
      
    
    {\displaystyle D_{\text{Mac}}\;=\;{\frac {1}{m\,P}}\!\left[C\,{\frac {1+r}{r^{2}}}{\bigl (}1-(1+r)^{-N}{\bigr )}\;-\;{\frac {N\,C}{r}}\,(1+r)^{-N}\;+\;N\,F\,(1+r)^{-N}\right].}
  

The modified duration follows from the compounding relation

  
    
      
        
          D
          
            mod
          
        
        
        =
        
        
          
            
              D
              
                Mac
              
            
            
              
              1
              +
              r
              
            
          
        
        
        ,
      
    
    {\displaystyle D_{\text{mod}}\;=\;{\frac {D_{\text{Mac}}}{\,1+r\,}}\,,}
  

and the price value of a basis point (DV01 or PVBP) is

  
    
      
        
          DV01
        
        
        =
        
        P
        ×
        
          D
          
            mod
          
        
        ×
        
          10
          
            −
            4
          
        
        
        .
      
    
    {\displaystyle {\text{DV01}}\;=\;P\times D_{\text{mod}}\times 10^{-4}\,.}
  

These formulas are standard checks for implementations and spreadsheets.

### Zero-coupon: DV01 closed form

For 
  
    
      
        C
        =
        0
      
    
    {\displaystyle C=0}
  
 with 
  
    
      
        N
        =
        m
        T
      
    
    {\displaystyle N=mT}
  
:

  
    
      
        
          D
          
            Mac
          
        
        
        =
        
        T
        ,
        
        
          D
          
            mod
          
        
        
        =
        
        
          
            T
            
              1
              +
              r
            
          
        
        ,
        
        
          DV01
        
        
        =
        
        F
        
        (
        1
        +
        r
        
          )
          
            −
            N
          
        
        
        
          
            T
            
              1
              +
              r
            
          
        
        ×
        
          10
          
            −
            4
          
        
        .
      
    
    {\displaystyle D_{\text{Mac}}\;=\;T,\qquad D_{\text{mod}}\;=\;{\frac {T}{1+r}},\qquad {\text{DV01}}\;=\;F\,(1+r)^{-N}\,{\frac {T}{1+r}}\times 10^{-4}.}

### Level annuity: Macaulay duration

For 
  
    
      
        F
        =
        0
      
    
    {\displaystyle F=0}
  
 and 
  
    
      
        q
        =
        (
        1
        +
        r
        
          )
          
            −
            N
          
        
      
    
    {\displaystyle q=(1+r)^{-N}}
  
:

  
    
      
        
          D
          
            Mac
          
          
            annuity
          
        
        
        =
        
        
          
            1
            m
          
        
        
        
          [
          
            
              
                
                  1
                  +
                  r
                
                r
              
            
            
            −
            
            
              
                
                  N
                  
                  q
                
                
                  1
                  −
                  q
                
              
            
          
          ]
        
        .
      
    
    {\displaystyle D_{\text{Mac}}^{\text{annuity}}\;=\;{\frac {1}{m}}\!\left[{\frac {1+r}{r}}\;-\;{\frac {N\,q}{1-q}}\right].}

### Par bond: Macaulay duration

For a par bond 
  
    
      
        C
        =
        r
        F
      
    
    {\displaystyle C=rF}
  
 so 
  
    
      
        P
        =
        F
      
    
    {\displaystyle P=F}
  
 and 
  
    
      
        q
        =
        (
        1
        +
        r
        
          )
          
            −
            N
          
        
      
    
    {\displaystyle q=(1+r)^{-N}}
  
:

  
    
      
        
          D
          
            Mac
          
          
            par
          
        
        
        =
        
        
          
            1
            m
          
        
        
        
          
            
              1
              +
              r
            
            r
          
        
        
        (
        1
        −
        q
        )
        
        .
      
    
    {\displaystyle D_{\text{Mac}}^{\text{par}}\;=\;{\frac {1}{m}}\,{\frac {1+r}{r}}\,(1-q)\,.}

### Par bond: DV01 closed form

With the same conditions as above:

  
    
      
        
          
            DV01
          
          
            par
          
        
        
        =
        
        F
        
        
          
            
              1
              −
              q
            
            
              m
              
              r
            
          
        
        ×
        
          10
          
            −
            4
          
        
        
        .
      
    
    {\displaystyle {\text{DV01}}^{\text{par}}\;=\;F\,{\frac {1-q}{m\,r}}\times 10^{-4}\,.}

### Consol or perpetuity

For 
  
    
      
        N
        →
        ∞
      
    
    {\displaystyle N\to \infty }
  
 with 
  
    
      
        C
        >
        0
      
    
    {\displaystyle C>0}
  
 and 
  
    
      
        F
        =
        0
      
    
    {\displaystyle F=0}
  
:

  
    
      
        P
        =
        
          
            C
            r
          
        
        ,
        
        
          D
          
            Mac
          
        
        =
        
          
            1
            m
          
        
        
          
            
              1
              +
              r
            
            r
          
        
        ,
        
        
          D
          
            mod
          
        
        =
        
          
            1
            
              m
              r
            
          
        
        ,
        
        
          DV01
        
        =
        
          
            P
            
              m
              r
            
          
        
        ×
        
          10
          
            −
            4
          
        
        .
      
    
    {\displaystyle P={\frac {C}{r}},\qquad D_{\text{Mac}}={\frac {1}{m}}{\frac {1+r}{r}},\qquad D_{\text{mod}}={\frac {1}{mr}},\qquad {\text{DV01}}={\frac {P}{mr}}\times 10^{-4}.}

### Discounted-sum identity S0

Let 
  
    
      
        q
        =
        (
        1
        +
        r
        
          )
          
            −
            1
          
        
      
    
    {\displaystyle q=(1+r)^{-1}}
  
. Then

  
    
      
        
          S
          
            0
          
        
        
        =
        
        
          ∑
          
            k
            =
            1
          
          
            N
          
        
        
          q
          
            k
          
        
        
        =
        
        
          
            
              q
              
              (
              1
              −
              
                q
                
                  N
                
              
              )
            
            
              1
              −
              q
            
          
        
        
        .
      
    
    {\displaystyle S_{0}\;=\;\sum _{k=1}^{N}q^{k}\;=\;{\frac {q\,(1-q^{N})}{1-q}}\,.}
  

This identity appears in standard derivations for price and is useful in implementations.

### Discounted-sum identity S1

With 
  
    
      
        q
        =
        (
        1
        +
        r
        
          )
          
            −
            1
          
        
      
    
    {\displaystyle q=(1+r)^{-1}}
  
:

  
    
      
        
          S
          
            1
          
        
        
        =
        
        
          ∑
          
            k
            =
            1
          
          
            N
          
        
        k
        
        
          q
          
            k
          
        
        
        =
        
        
          
            
              q
              
                
                  (
                
              
              1
              −
              (
              N
              +
              1
              )
              
                q
                
                  N
                
              
              +
              N
              
                q
                
                  N
                  +
                  1
                
              
              
                
                  )
                
              
            
            
              (
              1
              −
              q
              
                )
                
                  2
                
              
            
          
        
        
        .
      
    
    {\displaystyle S_{1}\;=\;\sum _{k=1}^{N}k\,q^{k}\;=\;{\frac {q{\bigl (}1-(N+1)q^{N}+Nq^{N+1}{\bigr )}}{(1-q)^{2}}}\,.}
  

This supports closed-form duration for level coupons.

### Second-moment identity S2

With 
  
    
      
        q
        =
        (
        1
        +
        r
        
          )
          
            −
            1
          
        
      
    
    {\displaystyle q=(1+r)^{-1}}
  
:

  
    
      
        
          S
          
            2
          
        
        
        =
        
        
          ∑
          
            k
            =
            1
          
          
            N
          
        
        
          k
          
            2
          
        
        
          q
          
            k
          
        
        
        =
        
        
          
            
              q
              
              
                (
                
                  
                    N
                    
                      2
                    
                  
                  
                    q
                    
                      N
                    
                  
                  −
                  2
                  
                    N
                    
                      2
                    
                  
                  
                    q
                    
                      N
                      +
                      1
                    
                  
                  +
                  
                    N
                    
                      2
                    
                  
                  
                    q
                    
                      N
                      +
                      2
                    
                  
                  +
                  2
                  N
                  
                    q
                    
                      N
                    
                  
                  −
                  2
                  N
                  
                    q
                    
                      N
                      +
                      1
                    
                  
                  −
                  q
                  +
                  
                    q
                    
                      N
                    
                  
                  +
                  
                    q
                    
                      N
                      +
                      1
                    
                  
                  −
                  1
                
                )
              
            
            
              (
              1
              −
              q
              
                )
                
                  3
                
              
            
          
        
        
        .
      
    
    {\displaystyle S_{2}\;=\;\sum _{k=1}^{N}k^{2}q^{k}\;=\;{\frac {q\!\left(N^{2}q^{N}-2N^{2}q^{N+1}+N^{2}q^{N+2}+2Nq^{N}-2Nq^{N+1}-q+q^{N}+q^{N+1}-1\right)}{(1-q)^{3}}}\,.}
  

This supports closed-form convexity.

### Level-coupon convexity: closed form

Using the identities above for a level-coupon bond:

  
    
      
        C
        
        =
        
        
          
            1
            
              
                m
                
                  2
                
              
              (
              1
              +
              r
              
                )
                
                  2
                
              
              
              P
            
          
        
        
        
          
            [
          
        
        
        C
        
        (
        
          S
          
            1
          
        
        +
        
          S
          
            2
          
        
        )
        
        +
        
        N
        (
        N
        +
        1
        )
        
        F
        
        (
        1
        +
        r
        
          )
          
            −
            N
          
        
        
        
          
            ]
          
        
        .
      
    
    {\displaystyle C\;=\;{\frac {1}{m^{2}(1+r)^{2}\,P}}\,{\Bigl [}\,C\,(S_{1}+S_{2})\;+\;N(N+1)\,F\,(1+r)^{-N}\,{\Bigr ]}.}

### Finite-difference modified duration

For a symmetric bump 
  
    
      
        ±
        Δ
        y
      
    
    {\displaystyle \pm \Delta y}
  
 to the quoted yield:

  
    
      
        
          D
          
            mod
          
        
        
        ≈
        
        −
        
        
          
            
              
                P
                
                  +
                
              
              −
              
                P
                
                  −
                
              
            
            
              2
              
              
                P
                
                  0
                
              
              
              Δ
              y
            
          
        
        
        .
      
    
    {\displaystyle D_{\text{mod}}\;\approx \;-\,{\frac {P_{+}-P_{-}}{2\,P_{0}\,\Delta y}}\,.}
  

This is a common check on analytical duration and underlies effective duration.

### Key-rate DV01 (local bump)

For a bump applied only at tenor 
  
    
      
        
          τ
          
            k
          
        
      
    
    {\displaystyle \tau _{k}}
  
:

  
    
      
        
          KRD
        
        (
        
          τ
          
            k
          
        
        )
        
        ≈
        
        −
        
        
          
            
              
                P
                
                  +
                
                
                  (
                  k
                  )
                
              
              −
              
                P
                
                  −
                
                
                  (
                  k
                  )
                
              
            
            
              2
              
              
                P
                
                  0
                
              
              
              Δ
              y
            
          
        
        
        .
      
    
    {\displaystyle {\text{KRD}}(\tau _{k})\;\approx \;-\,{\frac {P_{+}^{(k)}-P_{-}^{(k)}}{2\,P_{0}\,\Delta y}}\,.}
  

This is used to report sensitivity by maturity bucket.

### Example 1: two-year, high-coupon bond (semi-annual)

Face 
  
    
      
        F
        =
        100
      
    
    {\displaystyle F=100}
  
, coupon 
  
    
      
        20
        %
      
    
    {\displaystyle 20\%}
  
 per year paid semi-annually so 
  
    
      
        C
        =
        10
      
    
    {\displaystyle C=10}
  
, nominal yield 
  
    
      
        y
        =
        4
        %
      
    
    {\displaystyle y=4\%}
  
 with 
  
    
      
        m
        =
        2
      
    
    {\displaystyle m=2}
  
 so 
  
    
      
        r
        =
        0.02
      
    
    {\displaystyle r=0.02}
  
, and 
  
    
      
        N
        =
        4
      
    
    {\displaystyle N=4}
  
.
Price via the cash-flow sum:

  
    
      
        P
        
        =
        
        
          ∑
          
            i
            =
            1
          
          
            4
          
        
        
          
            10
            
              (
              1.02
              
                )
                
                  i
                
              
            
          
        
        
        +
        
        
          
            100
            
              (
              1.02
              
                )
                
                  4
                
              
            
          
        
        
        ≈
        
        130.462
        
        .
      
    
    {\displaystyle P\;=\;\sum _{i=1}^{4}{\frac {10}{(1.02)^{i}}}\;+\;{\frac {100}{(1.02)^{4}}}\;\approx \;130.462\,.}
  

Macaulay and modified duration:

  
    
      
        
          D
          
            Mac
          
        
        
        ≈
        
        1.777
        
           years
        
        ,
        
        
          D
          
            mod
          
        
        
        =
        
        
          
            1.777
            1.02
          
        
        
        ≈
        
        1.743
        
        .
      
    
    {\displaystyle D_{\text{Mac}}\;\approx \;1.777{\text{ years}},\qquad D_{\text{mod}}\;=\;{\frac {1.777}{1.02}}\;\approx \;1.743\,.}
  

DV01 per 1 bp:

  
    
      
        
          DV01
        
        
        =
        
        130.462
        ×
        1.743
        ×
        
          10
          
            −
            4
          
        
        
        ≈
        
        0.0227
        
        .
      
    
    {\displaystyle {\text{DV01}}\;=\;130.462\times 1.743\times 10^{-4}\;\approx \;0.0227\,.}

### Example 2: five-year, annual coupon bond

Face 
  
    
      
        F
        =
        1000
      
    
    {\displaystyle F=1000}
  
, coupon 
  
    
      
        5
        %
      
    
    {\displaystyle 5\%}
  
 annually so 
  
    
      
        C
        =
        50
      
    
    {\displaystyle C=50}
  
, annual yield 
  
    
      
        y
        =
        6.5
        %
      
    
    {\displaystyle y=6.5\%}
  
 with 
  
    
      
        m
        =
        1
      
    
    {\displaystyle m=1}
  
 so 
  
    
      
        r
        =
        0.065
      
    
    {\displaystyle r=0.065}
  
, and 
  
    
      
        N
        =
        5
      
    
    {\displaystyle N=5}
  
.
Price:

  
    
      
        P
        
        =
        
        50
        
          ∑
          
            t
            =
            1
          
          
            4
          
        
        
          
            1
            
              (
              1.065
              
                )
                
                  t
                
              
            
          
        
        
        +
        
        
          
            1050
            
              (
              1.065
              
                )
                
                  5
                
              
            
          
        
        
        ≈
        
        937.665
        
        .
      
    
    {\displaystyle P\;=\;50\sum _{t=1}^{4}{\frac {1}{(1.065)^{t}}}\;+\;{\frac {1050}{(1.065)^{5}}}\;\approx \;937.665\,.}
  

Macaulay and modified duration:

  
    
      
        
          D
          
            Mac
          
        
        
        ≈
        
        4.529
        
           years
        
        ,
        
        
          D
          
            mod
          
        
        
        =
        
        
          
            4.529
            1.065
          
        
        
        ≈
        
        4.253
        
        .
      
    
    {\displaystyle D_{\text{Mac}}\;\approx \;4.529{\text{ years}},\qquad D_{\text{mod}}\;=\;{\frac {4.529}{1.065}}\;\approx \;4.253\,.}
  

DV01 per 1 bp:

  
    
      
        
          DV01
        
        
        =
        
        937.665
        ×
        4.253
        ×
        
          10
          
            −
            4
          
        
        
        ≈
        
        0.399
        
        .
      
    
    {\displaystyle {\text{DV01}}\;=\;937.665\times 4.253\times 10^{-4}\;\approx \;0.399\,.}
