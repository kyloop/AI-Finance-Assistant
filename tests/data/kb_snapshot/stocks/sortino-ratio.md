# Sortino ratio

<!-- https://en.wikipedia.org/wiki/Sortino_ratio | revision 1371465720 -->

The Sortino ratio measures the risk-adjusted return of an investment asset, portfolio, or strategy. It is a modification of the Sharpe ratio but penalizes only those returns falling below a user-specified target or required rate of return, while the Sharpe ratio penalizes both upside and downside variance equally. Though both ratios measure an investment's risk-adjusted return, they do so in significantly different ways that will frequently lead to differing conclusions as to the true nature of the investment's return-generating efficiency.
The Sortino ratio is used as a way to compare the risk-adjusted performance of programs with differing risk and return profiles. As such, risk-adjusted returns normalize risks across programs.

## Definition

The ratio 
  
    
      
        S
      
    
    {\displaystyle S}
  
 is calculated as

  
    
      
        S
        =
        
          
            
              R
              −
              T
            
            
              D
              R
            
          
        
      
    
    {\displaystyle S={\frac {R-T}{DR}}}
  
 ,
where 
  
    
      
        R
      
    
    {\displaystyle R}
  
 is the asset or portfolio average annual total return, 
  
    
      
        T
      
    
    {\displaystyle T}
  
 is the target or required rate of return for the investment strategy under consideration (originally called the minimum acceptable return MAR), and 
  
    
      
        D
        R
      
    
    {\displaystyle DR}
  
 is the target semi-deviation (the square root of target semi-variance), termed downside deviation. 
An intuitive way to view downside risk is the annualized standard deviation of returns below the target. Another is the square root of the probability-weighted squared below-target returns. The squaring of the below-target returns has the effect of penalizing failures at a quadratic rate. This is consistent with observations made on the behavior of individual decision making under uncertainty.

  
    
      
        D
        R
        =
        
          
            
              ∫
              
                −
                ∞
              
              
                T
              
            
            (
            T
            −
            r
            
              )
              
                2
              
            
            f
            (
            r
            )
            
            d
            r
          
        
      
    
    {\displaystyle DR={\sqrt {\int _{-\infty }^{T}(T-r)^{2}f(r)\,dr}}}
  

Here

  
    
      
        D
        R
      
    
    {\displaystyle DR}
  
 = downside deviation or (commonly known in the financial community) "downside risk" (by extension, 
  
    
      
        D
        
          R
          
            2
          
        
      
    
    {\displaystyle DR^{2}}
  
 = downside variance),

  
    
      
        T
      
    
    {\displaystyle T}
  
 = the annual target return, originally termed the minimum acceptable return MAR,

  
    
      
        r
      
    
    {\displaystyle r}
  
 = the random variable representing the return for the distribution of annual returns 
  
    
      
        f
        (
        r
        )
      
    
    {\displaystyle f(r)}
  
, and

  
    
      
        f
        (
        r
        )
      
    
    {\displaystyle f(r)}
  
 = the distribution for the annual returns.  The 3-parameter lognormal distribution is used by Sortino and Rom.
For the reasons provided below, this continuous formula is preferred over a simpler discrete version that determines the standard deviation of below-target periodic returns taken from the return series.

The continuous form permits all subsequent calculations to be made using annual returns, the natural way for investors to specify their investment goals. The discrete form requires monthly returns for there to be sufficient data points to make a meaningful calculation, which in turn requires converting the annual target into a monthly target. This significantly affects the amount of risk that is identified. For example, a goal of earning 1% in every month of one year results in a greater risk than the seemingly equivalent goal of earning 12% in one year.
A second reason for strongly preferring the continuous form to the discrete form has been proposed by Sortino & Forsey (1996):

"Before we make an investment, we don't know what the outcome will be... After the investment is made, and we want to measure its performance, all we know is what the outcome was, not what it could have been. To cope with this uncertainty, we assume that a reasonable estimate of the range of possible returns, as well as the probabilities associated with estimation of those returns...In statistical terms, the shape of [this] uncertainty is called a probability distribution. In other words, looking at just the discrete monthly or annual values does not tell the whole story."

Using the observed points to create a distribution is a staple of conventional performance measurement. For example, monthly returns are used to calculate a fund's mean and standard deviation. Using these values and the properties of the normal distribution, we can make statements such as the likelihood of losing money (even though no negative returns may actually have been observed) or the range within which two-thirds of all returns lies (even though the specific returns identifying this range have not necessarily occurred). Our ability to make these statements comes from the process of assuming the continuous form of the normal distribution and certain of its well-known properties.
In post-modern portfolio theory an analogous process is followed.

Observe the monthly returns.
Fit a distribution that permits asymmetry to the observations.
Annualize the monthly returns, making sure the shape characteristics of the distribution are retained.
Apply integral calculus to the resultant distribution to calculate the appropriate statistics.
As a caveat, some practitioners have fallen into the habit of using discrete periodic returns to compute downside risk. This method is conceptually and operationally incorrect and negates the foundational statistic of post-modern portfolio theory as developed by Brian M. Rom.

## Usage

The Sortino ratio is used to score a portfolio's risk-adjusted returns relative to an investment target using downside risk. This is analogous to the Sharpe ratio, which scores risk-adjusted returns relative to the risk-free rate using standard deviation. When return distributions are near symmetrical and the target return is close to the distribution median, these two measures will produce similar results. As skewness increases and targets vary from the median, results can be expected to show dramatic differences.  From the preceding it therefore follows that these metrics will not produce accurate results for the short term, such as asset-trading.
Practitioners who use a lower partial Standard Deviation (LPSD) instead of a standard deviation also tend to use the Sortino ratio instead of the Sharpe ratio.
