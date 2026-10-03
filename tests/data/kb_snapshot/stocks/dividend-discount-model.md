# Dividend discount model

<!-- https://en.wikipedia.org/wiki/Dividend_discount_model | revision 1345461329 -->

In financial economics, the dividend discount model (DDM) is a method of valuing the price of a company's capital stock or business value based on the assertion that intrinsic value is determined by the sum of future cash flows from dividend payments to shareholders, discounted back to their present value. The constant-growth form of the DDM is sometimes referred to as the Gordon growth model (GGM), after Myron J. Gordon of the Massachusetts Institute of Technology, the University of Rochester, and the University of Toronto, who published it along with Eli Shapiro in 1956 and made reference to it in 1959. Their work borrowed heavily from the theoretical and mathematical ideas found in John Burr Williams 1938 book "The Theory of Investment Value," which put forth the dividend discount model 18 years before Gordon and Shapiro.
When dividends are assumed to grow at a constant rate, the variables are: 
  
    
      
        P
      
    
    {\displaystyle P}
  
 is the current stock price. 
  
    
      
        g
      
    
    {\displaystyle g}
  
 is the constant growth rate in perpetuity expected for the dividends. 
  
    
      
        r
      
    
    {\displaystyle r}
  
 is the constant cost of equity capital for that company. 
  
    
      
        
          D
          
            1
          
        
      
    
    {\displaystyle D_{1}}
  
 is the value of dividends at the end of the first period.

  
    
      
        P
        =
        
          
            
              D
              
                1
              
            
            
              r
              −
              g
            
          
        
      
    
    {\displaystyle P={\frac {D_{1}}{r-g}}}

## Derivation of equation

The model uses the fact that the current value of the dividend payment 
  
    
      
        
          D
          
            0
          
        
        (
        1
        +
        g
        
          )
          
            t
          
        
      
    
    {\displaystyle D_{0}(1+g)^{t}}
  
 at (discrete) time 
  
    
      
        t
      
    
    {\displaystyle t}
  
 is 
  
    
      
        
          
            
              
                D
                
                  0
                
              
              (
              1
              +
              g
              
                )
                
                  t
                
              
            
            
              
                (
                1
                +
                r
                )
              
              
                t
              
            
          
        
      
    
    {\displaystyle {\frac {D_{0}(1+g)^{t}}{{(1+r)}^{t}}}}
  
, and so the current value of all the future dividend payments, which is the current price 
  
    
      
        P
      
    
    {\displaystyle P}
  
, is the sum of the infinite series 

  
    
      
        
          P
          
            0
          
        
        =
        
          ∑
          
            t
            =
            1
          
          
            ∞
          
        
        
          
            D
            
              0
            
          
        
        
          
            
              (
              1
              +
              g
              
                )
                
                  t
                
              
            
            
              (
              1
              +
              r
              
                )
                
                  t
                
              
            
          
        
      
    
    {\displaystyle P_{0}=\sum _{t=1}^{\infty }{D_{0}}{\frac {(1+g)^{t}}{(1+r)^{t}}}}
  

This summation can be rewritten as

  
    
      
        
          P
          
            0
          
        
        =
        
          
            D
            
              0
            
          
        
        
          r
          ′
        
        (
        1
        +
        
          r
          ′
        
        +
        
          
            
              r
              ′
            
          
          
            2
          
        
        +
        
          
            
              r
              ′
            
          
          
            3
          
        
        +
        .
        .
        .
        .
        )
      
    
    {\displaystyle P_{0}={D_{0}}r'(1+r'+{r'}^{2}+{r'}^{3}+....)}
  

where

  
    
      
        
          r
          ′
        
        =
        
          
            
              1
              +
              g
            
            
              1
              +
              r
            
          
        
        .
      
    
    {\displaystyle r'={\frac {1+g}{1+r}}.}
  

The series in parentheses is the geometric series with common ratio 
  
    
      
        
          r
          ′
        
      
    
    {\displaystyle r'}
  
 so it sums to 
  
    
      
        
          
            1
            
              1
              −
              
                r
                ′
              
            
          
        
      
    
    {\displaystyle {\frac {1}{1-r'}}}
  
 if 
  
    
      
        ∣
        
          r
          ′
        
        ∣<
        1
      
    
    {\displaystyle \mid r'\mid <1}
  
. Thus,

  
    
      
        
          P
          
            0
          
        
        =
        
          
            
              
                D
                
                  0
                
              
              
                r
                ′
              
            
            
              1
              −
              
                r
                ′
              
            
          
        
      
    
    {\displaystyle P_{0}={\frac {D_{0}r'}{1-r'}}}
  

Substituting the value for 
  
    
      
        
          r
          ′
        
      
    
    {\displaystyle r'}
  
 leads to

  
    
      
        
          P
          
            0
          
        
        =
        
          
            
              
                D
                
                  0
                
              
              
                
                  
                    1
                    +
                    g
                  
                  
                    1
                    +
                    r
                  
                
              
            
            
              1
              −
              
                
                  
                    1
                    +
                    g
                  
                  
                    1
                    +
                    r
                  
                
              
            
          
        
      
    
    {\displaystyle P_{0}={\frac {D_{0}{\frac {1+g}{1+r}}}{1-{\frac {1+g}{1+r}}}}}
  
,
which is simplified by multiplying by 
  
    
      
        
          
            
              1
              +
              r
            
            
              1
              +
              r
            
          
        
      
    
    {\displaystyle {\frac {1+r}{1+r}}}
  
, so that

  
    
      
        
          P
          
            0
          
        
        =
        
          
            
              
                D
                
                  0
                
              
              (
              1
              +
              g
              )
            
            
              r
              −
              g
            
          
        
        =
        
          
            
              D
              
                1
              
            
            
              r
              −
              g
            
          
        
      
    
    {\displaystyle P_{0}={\frac {D_{0}(1+g)}{r-g}}={\frac {D_{1}}{r-g}}}

## Income plus capital gains equals total return

The DDM equation can also be understood to state simply that a stock's total return equals the sum of its income and capital gains. 

  
    
      
        
          
            
              D
              
                1
              
            
            
              r
              −
              g
            
          
        
        =
        
          P
          
            0
          
        
      
    
    {\displaystyle {\frac {D_{1}}{r-g}}=P_{0}}
  
 is rearranged to give 
  
    
      
        
          
            
              D
              
                1
              
            
            
              P
              
                0
              
            
          
        
        +
        g
        =
        r
      
    
    {\displaystyle {\frac {D_{1}}{P_{0}}}+g=r}
  

So the dividend yield 
  
    
      
        (
        
          D
          
            1
          
        
        
          /
        
        
          P
          
            0
          
        
        )
      
    
    {\displaystyle (D_{1}/P_{0})}
  
 plus the growth 
  
    
      
        (
        g
        )
      
    
    {\displaystyle (g)}
  
 equals cost of equity 
  
    
      
        (
        r
        )
      
    
    {\displaystyle (r)}
  
.
Consider the dividend growth rate in the DDM model as a proxy for the growth of earnings and by extension the stock price and capital gains. Consider the DDM's cost of equity capital as a proxy for the investor's required total return.

  
    
      
        
          Income
        
        +
        
          Capital Gain
        
        =
        
          Total Return
        
      
    
    {\displaystyle {\text{Income}}+{\text{Capital Gain}}={\text{Total Return}}}

## Growth cannot exceed cost of equity

From the first equation, one might notice that 
  
    
      
        r
        −
        g
      
    
    {\displaystyle r-g}
  
 cannot be negative. When growth is expected to exceed the cost of equity in the short run, then usually a two-stage DDM is used:

  
    
      
        P
        =
        
          ∑
          
            t
            =
            1
          
          
            N
          
        
        
          
            
              
                D
                
                  0
                
              
              
                
                  (
                  
                    1
                    +
                    g
                  
                  )
                
                
                  t
                
              
            
            
              
                (
                
                  1
                  +
                  r
                
                )
              
              
                t
              
            
          
        
        +
        
          
            
              P
              
                N
              
            
            
              
                (
                
                  1
                  +
                  r
                
                )
              
              
                N
              
            
          
        
      
    
    {\displaystyle P=\sum _{t=1}^{N}{\frac {D_{0}\left(1+g\right)^{t}}{\left(1+r\right)^{t}}}+{\frac {P_{N}}{\left(1+r\right)^{N}}}}
  

Therefore,

  
    
      
        P
        =
        
          
            
              
                D
                
                  0
                
              
              
                (
                
                  1
                  +
                  g
                
                )
              
            
            
              r
              −
              g
            
          
        
        
          [
          
            1
            −
            
              
                
                  
                    (
                    
                      1
                      +
                      g
                    
                    )
                  
                  
                    N
                  
                
                
                  
                    (
                    
                      1
                      +
                      r
                    
                    )
                  
                  
                    N
                  
                
              
            
          
          ]
        
        +
        
          
            
              
                D
                
                  0
                
              
              
                
                  (
                  
                    1
                    +
                    g
                  
                  )
                
                
                  N
                
              
              
                (
                
                  1
                  +
                  
                    g
                    
                      ∞
                    
                  
                
                )
              
            
            
              
                
                  (
                  
                    1
                    +
                    r
                  
                  )
                
                
                  N
                
              
              
                (
                
                  r
                  −
                  
                    g
                    
                      ∞
                    
                  
                
                )
              
            
          
        
        ,
      
    
    {\displaystyle P={\frac {D_{0}\left(1+g\right)}{r-g}}\left[1-{\frac {\left(1+g\right)^{N}}{\left(1+r\right)^{N}}}\right]+{\frac {D_{0}\left(1+g\right)^{N}\left(1+g_{\infty }\right)}{\left(1+r\right)^{N}\left(r-g_{\infty }\right)}},}
  

where 
  
    
      
        g
      
    
    {\displaystyle g}
  
 denotes the short-run expected growth rate, 
  
    
      
        
          g
          
            ∞
          
        
      
    
    {\displaystyle g_{\infty }}
  
 denotes the long-run growth rate, and 
  
    
      
        N
      
    
    {\displaystyle N}
  
 is the period (number of years), over which the short-run growth rate is applied.
Even when g is very close to r, P approaches infinity, so the model becomes meaningless.

## Some properties of the model

a)
When the growth g is zero, the dividend is capitalized.

  
    
      
        
          P
          
            0
          
        
        =
        
          
            
              D
              
                1
              
            
            r
          
        
      
    
    {\displaystyle P_{0}={\frac {D_{1}}{r}}}
  
.
 b)
This equation is also used to estimate the cost of capital by solving for 
  
    
      
        r
      
    
    {\displaystyle r}
  
.

  
    
      
        r
        =
        
          
            
              D
              
                1
              
            
            
              P
              
                0
              
            
          
        
        +
        g
        .
      
    
    {\displaystyle r={\frac {D_{1}}{P_{0}}}+g.}
  

 c)
which is equivalent to the formula of the Gordon Growth Model  (or Yield-plus-growth Model):

  
    
      
        
          P
          
            0
          
        
      
    
    {\displaystyle P_{0}}
  
 = 
  
    
      
        
          
            
              D
              
                1
              
            
            
              k
              −
              g
            
          
        
      
    
    {\displaystyle {\frac {D_{1}}{k-g}}}
  

where “
  
    
      
        
          P
          
            0
          
        
      
    
    {\displaystyle P_{0}}
  
” stands for the present stock value, “
  
    
      
        
          D
          
            1
          
        
      
    
    {\displaystyle D_{1}}
  
” stands for expected dividend per share one year from the present time, “g” stands for rate of growth of dividends, and “k” represents the required return rate for the equity investor.

## Problems with the constant-growth form of the model

The following shortcomings have been noted;
See also Discounted cash flow § Shortcomings.

The presumption of a steady and perpetual growth rate less than the cost of capital may not be reasonable.
If the stock does not currently pay a dividend, like many growth stocks, more general versions of the discounted dividend model must be used to value the stock. One common technique is to assume that the Modigliani–Miller hypothesis of dividend irrelevance is true, and therefore replace the stock's dividend D with E earnings per share. However, this requires the use of earnings growth rather than dividend growth, which might be different. This approach is especially useful for computing the residual value of future periods.
The stock price resulting from the Gordon model is sensitive to the growth rate 
  
    
      
        g
      
    
    {\displaystyle g}
  
 chosen; see Sustainable growth rate § From a financial perspective

## Related methods

The dividend discount model does not include projected cash flow from the sale of the stock at the end of the investment time horizon. A related approach, known as a discounted cash flow analysis, can be used to calculate the intrinsic value of a stock including both expected future dividends and the expected sale price at the end of the holding period. If the intrinsic value exceeds the stock's current market price, the stock is an attractive investment.
