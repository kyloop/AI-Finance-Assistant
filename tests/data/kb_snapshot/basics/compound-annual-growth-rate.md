# Compound annual growth rate

<!-- https://en.wikipedia.org/wiki/Compound_annual_growth_rate | revision 1372668502 -->

Compound annual growth rate (CAGR) is a business, economics and investing term representing the mean annualized growth rate for compounding values over a given time period. CAGR smooths the effect of volatility of periodic values that can render arithmetic means less meaningful. It is particularly useful to compare growth rates of various data values, such as revenue growth of companies, or of economic values, over time.

## Equation

For annual values, CAGR is defined as:

  
    
      
        
          C
          A
          G
          R
        
        (
        
          t
          
            0
          
        
        ,
        
          t
          
            n
          
        
        )
        =
        
          
            (
            
              
                
                  V
                  (
                  
                    t
                    
                      n
                    
                  
                  )
                
                
                  V
                  (
                  
                    t
                    
                      0
                    
                  
                  )
                
              
            
            )
          
          
            
              1
              
                
                  t
                  
                    n
                  
                
                −
                
                  t
                  
                    0
                  
                
              
            
          
        
        −
        1
      
    
    {\displaystyle \mathrm {CAGR} (t_{0},t_{n})=\left({\frac {V(t_{n})}{V(t_{0})}}\right)^{\frac {1}{t_{n}-t_{0}}}-1}
  

where 
  
    
      
        V
        (
        
          t
          
            0
          
        
        )
      
    
    {\displaystyle V(t_{0})}
  
 is the initial value, 
  
    
      
        V
        (
        
          t
          
            n
          
        
        )
      
    
    {\displaystyle V(t_{n})}
  
 is the end value, and 
  
    
      
        
          t
          
            n
          
        
        −
        
          t
          
            0
          
        
      
    
    {\displaystyle t_{n}-t_{0}}
  
 is the number of years.
CAGR can also be used to calculate mean annualized growth rates on quarterly or monthly values. The numerator of the exponent would be the value of 4 in the case of quarterly, and 12 in the case of monthly, with the denominator being the number of corresponding periods involved.
In practice, CAGR calculations are often performed in Microsoft Excel. A convenient built-in function is 
  
    
      
        =
        R
        R
        I
        (
        n
        p
        e
        r
        ,
        p
        v
        ,
        f
        v
        )
      
    
    {\displaystyle =RRI(nper,pv,fv)}
  
, where 
  
    
      
        n
        p
        e
        r
      
    
    {\displaystyle nper}
  
 represents the number of periods, 
  
    
      
        p
        v
      
    
    {\displaystyle pv}
  
 denotes the present value (initial investment), and 
  
    
      
        f
        v
      
    
    {\displaystyle fv}
  
 represents the future value (final value of the investment). The RRI function (Return Rate on Investment) returns the equivalent constant interest rate per period, effectively matching the CAGR when applied over a specified period. It is also possible to use the IRR function on a range of cells where the first cell is set to the present value as a negative number, the last cell is set to the future value, and all other cells are set to zero.
CAGR is a good method to compare returns of 2 investment instruments (Bonds/stocks/Gsecs etc) over a multi-year period.

## Applications

These are some of the common CAGR applications:

Calculating and communicating the mean returns of investment funds
Demonstrating and comparing the performance of investment advisors
Comparing the historical returns of stocks with bonds or with a savings account
Forecasting future values based on the CAGR of a data series (you find future values by multiplying the last datum of the series by (1 + CAGR) as many times as years required). As with every forecasting method, this method has a calculation error associated.
Analyzing and communicating the behavior, over a series of years, of different business measures such as sales, market share, costs, customer satisfaction, and performance.
Calculating mean annualized growth rates of economic data, such as gross domestic product, over annual, quarterly or monthly time intervals.
