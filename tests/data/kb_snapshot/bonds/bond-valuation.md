# Bond valuation

<!-- https://en.wikipedia.org/wiki/Bond_valuation | revision 1372347148 -->

Bond valuation is the process of estimating the fair value of a bond. In the prevalent present-value approach, the value equals the sum of expected cash flows discounted at appropriate rates.
In practice, under relative pricing, this discount rate is often inferred by reference to similar, more liquid instruments; arbitrage-free pricing is also common.
Several related yield measures can be computed for a given price. If the market price of a bond is below par value, it trades at a discount; if it is above par, it trades at a premium. 
If a bond has embedded options, valuation combines option pricing with discounting. Depending on the option type, the option value is added to or subtracted from the value of the option-free bond to obtain the total price. See under Bond option § Embedded options.

## Bond valuation

The fair price of a “straight” bond (no embedded options - see bond features) is the present value of its expected cash flows discounted at appropriate rates. In practice, prices are often inferred relative to more liquid instruments. Two approaches are common: relative pricing and arbitrage-free pricing. When valuation must reflect uncertainty in future rates, for example when valuing a bond option, analysts use interest-rate models.

### Present value approach

A basic calculation discounts each cash flow at a single market rate for all periods. A more realistic variant discounts each cash flow at its own rate along the curve. The formula below assumes a coupon has just been paid. See clean and dirty price for other dates.

  
    
      
        P
        
        =
        
        
          ∑
          
            n
            =
            1
          
          
            N
          
        
        
          
            C
            
              (
              1
              +
              i
              
                )
                
                  n
                
              
            
          
        
        
        +
        
        
          
            M
            
              (
              1
              +
              i
              
                )
                
                  N
                
              
            
          
        
        
        =
        
        C
        
        
          
            
              1
              −
              (
              1
              +
              i
              
                )
                
                  −
                  N
                
              
            
            i
          
        
        
        +
        
        M
        
        (
        1
        +
        i
        
          )
          
            −
            N
          
        
        .
      
    
    {\displaystyle P\;=\;\sum _{n=1}^{N}{\frac {C}{(1+i)^{n}}}\;+\;{\frac {M}{(1+i)^{N}}}\;=\;C\,{\frac {1-(1+i)^{-N}}{i}}\;+\;M\,(1+i)^{-N}.}
  

where:

  
    
      
        F
      
    
    {\displaystyle F}
  
 is the par (face) value

  
    
      
        
          i
          
            c
          
        
      
    
    {\displaystyle i_{c}}
  
 is the coupon rate per period

  
    
      
        C
        =
        F
        
        
          i
          
            c
          
        
      
    
    {\displaystyle C=F\,i_{c}}
  
 is the coupon payment per period

  
    
      
        N
      
    
    {\displaystyle N}
  
 is the number of remaining payments

  
    
      
        i
      
    
    {\displaystyle i}
  
 is the market discount rate per period (often linked to yield to maturity)

  
    
      
        M
      
    
    {\displaystyle M}
  
 is the redemption amount at maturity (usually equal to 
  
    
      
        F
      
    
    {\displaystyle F}
  
)

  
    
      
        P
      
    
    {\displaystyle P}
  
 is the bond price

### Relative price approach

Under this approach the bond is priced relative to a benchmark, usually a government bond yield curve. Set the bond's yield to maturity as the benchmark yield plus a credit spread appropriate to its credit rating and maturity or duration. Use this required return in the present-value formula above by replacing 
  
    
      
        i
      
    
    {\displaystyle i}
  
 with the bond's YTM.

### Arbitrage-free pricing approach

Under this approach each promised cash flow is valued at its own discount rate. View the bond as a package of cash flows and discount each one at the rate implied by a matching zero-coupon of the same maturity and credit quality.
Let 
  
    
      
        C
        
          F
          
            n
          
        
      
    
    {\displaystyle CF_{n}}
  
 be the cash flow at time 
  
    
      
        
          t
          
            n
          
        
      
    
    {\displaystyle t_{n}}
  
 and 
  
    
      
        Z
        (
        0
        ,
        
          t
          
            n
          
        
        )
      
    
    {\displaystyle Z(0,t_{n})}
  
 the discount factor for that date. Then

  
    
      
        P
        
        =
        
        
          ∑
          
            n
            =
            1
          
          
            N
          
        
        C
        
          F
          
            n
          
        
        
        Z
        (
        0
        ,
        
          t
          
            n
          
        
        )
        .
      
    
    {\displaystyle P\;=\;\sum _{n=1}^{N}CF_{n}\,Z(0,t_{n}).}
  

This is the arbitrage-free price. If the market price differs from this value, traders can construct assets with identical cash flows and lock in a profit until prices adjust. See Rational pricing § Assets with identical cash flows for the general argument.
A development here is that  post crisis, investment banks may (will) value their bonds using CSA-linked discount curves, while adjusting the expected cashflows  for default risk via the use of an issuer credit curve. See Multi-curve framework § Context.

### Stochastic calculus approach

When pricing a bond option or other interest rate derivative, future short rates are random, so a single fixed discount rate is not enough. In this setting one uses a one-factor short-rate model and risk-neutral valuation.
Under such a model, the price 
  
    
      
        P
        (
        t
        ,
        r
        ;
        T
        )
      
    
    {\displaystyle P(t,r;T)}
  
 of a zero-coupon bond maturing at 
  
    
      
        T
      
    
    {\displaystyle T}
  
 satisfies the risk-neutral bond PDE

  
    
      
        
          
            
              ∂
              P
            
            
              ∂
              t
            
          
        
        
        +
        
        
          a
          
            
              Q
            
          
        
        (
        r
        ,
        t
        )
        
        
          
            
              ∂
              P
            
            
              ∂
              r
            
          
        
        
        +
        
        
          
            
              1
              2
            
          
        
        
        σ
        (
        r
        ,
        t
        
          )
          
            2
          
        
        
        
          
            
              
                ∂
                
                  2
                
              
              P
            
            
              ∂
              
                r
                
                  2
                
              
            
          
        
        
        −
        
        r
        
        P
        
        =
        
        0
        ,
      
    
    {\displaystyle {\frac {\partial P}{\partial t}}\;+\;a_{\mathbb {Q} }(r,t)\,{\frac {\partial P}{\partial r}}\;+\;{\tfrac {1}{2}}\,\sigma (r,t)^{2}\,{\frac {\partial ^{2}P}{\partial r^{2}}}\;-\;r\,P\;=\;0,}
  

where 
  
    
      
        
          a
          
            
              Q
            
          
        
        (
        r
        ,
        t
        )
      
    
    {\displaystyle a_{\mathbb {Q} }(r,t)}
  
 is the risk-neutral drift of the short rate and 
  
    
      
        σ
        (
        r
        ,
        t
        )
      
    
    {\displaystyle \sigma (r,t)}
  
 its volatility.
Equivalently, under the risk-neutral measure 
  
    
      
        
          Q
        
      
    
    {\displaystyle \mathbb {Q} }
  
,

  
    
      
        P
        (
        t
        ,
        T
        ,
        
          r
          
            t
          
        
        )
        
        =
        
        
          
            E
          
          
            
              Q
            
          
        
        
        
          
            [
          
        
        exp
        
        
          
            (
          
        
        −
        
          
            ∫
            
              t
            
            
              T
            
          
          
            r
            
              s
            
          
          
          
            d
          
          s
          
            
              )
            
          
          
          
            
              |
            
          
          
          
            r
            
              t
            
          
          
            
              ]
            
          
          .
        
      
    
    {\displaystyle P(t,T,r_{t})\;=\;\mathbb {E} ^{\mathbb {Q} }\!{\bigl [}\exp \!{\bigl (}-\textstyle \int _{t}^{T}r_{s}\,\mathrm {d} s{\bigr )}\,{\big |}\,r_{t}{\bigr ]}.}
  

To obtain a number in practice you must choose a specific short-rate model. Common choices are the CIR model, the Black–Derman–Toy model, the Hull–White model, the HJM framework, and the Chen model. Some models yield closed-form solutions. Otherwise use a lattice or a simulation.

## Clean and dirty price

When a bond is valued between coupon dates the price includes accrued interest for the time since the previous coupon date. The price including accrued interest is the dirty price (also called full price, all-in price, or cash price). The clean price excludes accrued interest.
Clean prices are more stable through time than dirty prices. The dirty price rises deterministically between coupons as interest accrues, then drops by roughly the coupon amount when the coupon is paid.

  
    
      
        
          P
          
            dirty
          
        
        
        =
        
        
          P
          
            clean
          
        
        
        +
        
        
          AI
        
        .
      
    
    {\displaystyle P_{\text{dirty}}\;=\;P_{\text{clean}}\;+\;{\text{AI}}.}
  

Here 
  
    
      
        
          AI
        
      
    
    {\displaystyle {\text{AI}}}
  
 is accrued interest for the current coupon period. Under the market day count convention, a common calculation is

  
    
      
        
          AI
        
        
        =
        
        C
        ×
        α
        ,
      
    
    {\displaystyle {\text{AI}}\;=\;C\times \alpha ,}
  

where 
  
    
      
        C
      
    
    {\displaystyle C}
  
 is the coupon for the period and 
  
    
      
        α
      
    
    {\displaystyle \alpha }
  
 is the accrual fraction from the last coupon to the valuation date.
For example, a bond pays coupons on 1 Apr and 1 Oct each year. The annual coupon rate is 6% on par 100, so each half-year coupon is

  
    
      
        C
        =
        0.06
        ×
        
          
            100
            2
          
        
        =
        3.
      
    
    {\displaystyle C=0.06\times {\frac {100}{2}}=3.}
  

Suppose settlement is 1 Jul 2025. Under a 30/360 day count the accrual fraction from 1 Apr to 1 Jul is

  
    
      
        α
        =
        
          
            90
            180
          
        
        =
        0.50.
      
    
    {\displaystyle \alpha ={\frac {90}{180}}=0.50.}
  

Accrued interest is

  
    
      
        
          AI
        
        =
        C
        ×
        α
        =
        3.00
        ×
        0.50
        =
        1.50.
      
    
    {\displaystyle {\text{AI}}=C\times \alpha =3.00\times 0.50=1.50.}
  

If the quoted clean price is 98.20, then the dirty price is

  
    
      
        
          P
          
            dirty
          
        
        =
        
          P
          
            clean
          
        
        +
        
          AI
        
        =
        98.20
        +
        1.50
        =
        99.70.
      
    
    {\displaystyle P_{\text{dirty}}=P_{\text{clean}}+{\text{AI}}=98.20+1.50=99.70.}
  

In many markets quotes are on a clean-price basis. At settlement the accrued interest is added to the quoted clean price to obtain the amount paid.

## Yield and price relationships

Once the price is known, several yields can be calculated that relate the price to the bond's cash flows.

### Yield to maturity

The yield to maturity (YTM) is the discount rate that equates the present value of all promised cash flows to the observed market price for an option-free bond. It is the internal rate of return on the cash flows if they are received as scheduled and reinvested at the YTM. Because YTM can be used in pricing, bonds are often quoted by their YTM.
To realise a return equal to the quoted YTM the investor would need to:

buy the bond at the quoted price 
  
    
      
        P
      
    
    {\displaystyle P}
  
,
receive all coupons and principal as scheduled with no default, and
reinvest each coupon at the YTM until maturity.

### Coupon rate

The coupon rate is the stated annual coupon as a percentage of the face value 
  
    
      
        F
      
    
    {\displaystyle F}
  
. If coupons are paid 
  
    
      
        m
      
    
    {\displaystyle m}
  
 times per year and the per-period coupon is 
  
    
      
        C
      
    
    {\displaystyle C}
  
, then the annual coupon is 
  
    
      
        m
        C
      
    
    {\displaystyle mC}
  
 and

  
    
      
        
          Coupon rate
        
        
        =
        
        
          
            
              m
              C
            
            F
          
        
        .
      
    
    {\displaystyle {\text{Coupon rate}}\;=\;{\frac {mC}{F}}.}
  

The coupon rate is sometimes called the nominal coupon.

### Current yield

The current yield is the annual coupon divided by the (clean) price 
  
    
      
        P
      
    
    {\displaystyle P}
  
 at the valuation date:

  
    
      
        
          Current yield
        
        
        =
        
        
          
            
              m
              C
            
            P
          
        
        .
      
    
    {\displaystyle {\text{Current yield}}\;=\;{\frac {mC}{P}}.}

### Relationship

The concept of current yield is closely related to other bond concepts, including yield to maturity, and coupon yield. The relationship between yield to maturity and the coupon rate is as follows:

As price falls below par the yield to maturity rises, and it rises more than the current yield because it also reflects the capital gain realised at redemption.

## Price sensitivity

A bond's price sensitivity to yield changes is measured by duration for the first-order effect and by convexity for the second-order effect.
Duration (specifically, modified duration) is the first-order measure of price sensitivity. For a small parallel change in yield 
  
    
      
        Δ
        y
      
    
    {\displaystyle \Delta y}
  
,
the percentage price change is approximately the duration times 
  
    
      
        Δ
        y
      
    
    {\displaystyle \Delta y}
  
 in absolute value. For example, if a bond has duration 7, a 1 percentage-point rise in yield implies a price change of about 
  
    
      
        −
        7
        %
      
    
    {\displaystyle -7\%}
  
, ignoring convexity.

  
    
      
        
          
            
              Δ
              P
            
            P
          
        
        
        ≈
        
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
          
        
        .
      
    
    {\displaystyle {\frac {\Delta P}{P}}\;\approx \;-\,D\,\Delta y\;+\;{\tfrac {1}{2}}\,C\,(\Delta y)^{2}.}
  

Convexity measures the curvature of the price–yield relation. Price is not linear in yield, it is convex. Formally, duration is the first derivative of price with respect to yield, and convexity is the second derivative. Using both improves the estimate in the formula above.
For bonds with embedded options, see effective duration and effective convexity. For portfolio context, see Corporate bond § Risk analysis.

## Accounting treatment

In accounting for long-term liabilities, any bond discount or premium is amortized over the life of the bond. The standard approach is the effective interest method. Under IFRS it is required when instruments are measured at amortized cost. Under US GAAP it is required, although a straight-line method may be used only if the result is not materially different from the interest method.
Let 
  
    
      
        
          P
          
            0
          
        
      
    
    {\displaystyle P_{0}}
  
 be the issue-date carrying amount, 
  
    
      
        F
      
    
    {\displaystyle F}
  
 the face value, 
  
    
      
        C
      
    
    {\displaystyle C}
  
 the cash coupon per period, and 
  
    
      
        r
      
    
    {\displaystyle r}
  
 the effective periodic interest rate (the market yield at issuance). For periods 
  
    
      
        n
        =
        1
        ,
        …
        ,
        N
      
    
    {\displaystyle n=1,\dots ,N}
  
:

  
    
      
        
          I
          
            n
          
        
        
        =
        
        r
        
        
          P
          
            n
            −
            1
          
        
        .
      
    
    {\displaystyle I_{n}\;=\;r\,P_{n-1}.}
  

  
    
      
        
          A
          
            n
          
        
        
        =
        
        
          I
          
            n
          
        
        −
        C
        .
      
    
    {\displaystyle A_{n}\;=\;I_{n}-C.}
  

  
    
      
        
          P
          
            n
          
        
        
        =
        
        
          P
          
            n
            −
            1
          
        
        +
        
          A
          
            n
          
        
        
        =
        
        
          P
          
            n
            −
            1
          
        
        (
        1
        +
        r
        )
        −
        C
        .
      
    
    {\displaystyle P_{n}\;=\;P_{n-1}+A_{n}\;=\;P_{n-1}(1+r)-C.}
  

For a discount, 
  
    
      
        
          A
          
            n
          
        
        >
        0
      
    
    {\displaystyle A_{n}>0}
  
 so the carrying amount accretes up toward 
  
    
      
        F
      
    
    {\displaystyle F}
  
. For a premium, 
  
    
      
        
          A
          
            n
          
        
        <
        0
      
    
    {\displaystyle A_{n}<0}
  
 so the carrying amount amortizes down toward 
  
    
      
        F
      
    
    {\displaystyle F}
  
. At maturity 
  
    
      
        
          P
          
            N
          
        
        =
        F
      
    
    {\displaystyle P_{N}=F}
  
 if there are no issuance costs.

## Selected bibliography

Guillermo L. Dumrauf (2012). "Chapter 1: Pricing and Return". Bonds, a Step by Step Analysis with Excel. Kindle Edition.
Frank Fabozzi (1998). Valuation of fixed income securities and derivatives (3rd ed.). John Wiley. ISBN 978-1-883249-25-0.
Frank J. Fabozzi (2005). Fixed Income Mathematics: Analytical & Statistical Techniques (4th ed.). John Wiley. ISBN 978-0071460736.
R. Stafford Johnson (2010). Bond Evaluation, Selection, and Management (2nd ed.). John Wiley. ISBN 978-0470478356.
Mayle, Jan (1993), Standard Securities Calculation Methods: Fixed Income Securities Formulas for Price, Yield and Accrued Interest, vol. 1щВлП (3rd ed.), Securities Industry and Financial Markets Association, ISBN 1-882936-01-9
Donald J. Smith (2011). Bond Math: The Theory Behind the Formulas. John Wiley. ISBN 978-1576603062.
Bruce Tuckman (2011). Fixed Income Securities: Tools for Today's Markets (3rd ed.). John Wiley. ISBN 978-0470891698.
Pietro Veronesi (2010). Fixed Income Securities: Valuation, Risk, and Risk Management. John Wiley. ISBN 978-0470109106.
Burton Malkiel (1962). "Expectations, Bond Prices, and the Term Structure of Interest Rates". The Quarterly Journal of Economics.
Mark Mobius (2012). Bonds: An Introduction to the Core Concepts. John Wiley. ISBN 978-0470821473.
