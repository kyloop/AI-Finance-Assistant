# Tracking error

<!-- https://en.wikipedia.org/wiki/Tracking_error | revision 1304010316 -->

In finance, tracking error or active risk is a measure of the risk in an investment portfolio that is due to active management decisions made by the portfolio manager; it indicates how closely a portfolio follows the index to which it is benchmarked. The best measure is the standard deviation of the difference between the portfolio and index returns.
Many portfolios are managed to a benchmark, typically an index. Some portfolios, notably index funds, are expected to replicate, before trading and other costs, the returns of an index exactly, while others 'actively manage' the portfolio by deviating from the index in order to generate active returns. Tracking error measures the deviation from the benchmark: an index fund has a near-zero tracking error, while an actively managed portfolio would normally have a higher tracking error. Thus the tracking error does not include any risk (return) that is merely a function of the market's movement. In addition to risk (return) from specific stock selection or industry and factor "betas", it can also include risk (return) from market timing decisions.
Dividing portfolio active return by portfolio tracking error gives the information ratio, which is a risk adjusted performance measure.

## Definition

If tracking error is measured historically, it is called 'realized' or 'ex post' tracking error. If a model is used to predict tracking error, it is called 'ex ante' tracking error. Ex-post tracking error is more useful for reporting performance, whereas ex-ante tracking error is generally used by portfolio managers to control risk. Various types of ex-ante tracking error models exist, from simple equity models which use beta as a primary determinant to more complicated multi-factor fixed income models. In a factor model of a portfolio, the non-systematic risk (i.e., the standard deviation of the residuals) is called "tracking error" in the investment field. The latter way to compute the tracking error complements the formulas below but results can vary (sometimes by a factor of 2).

### Formulas

The ex-post tracking error formula is the standard deviation of the active returns, given by:

  
    
      
        T
        E
        =
        ω
        =
        
          
            Var
            ⁡
            (
            
              r
              
                p
              
            
            −
            
              r
              
                b
              
            
            )
          
        
        =
        
          
            
              E
            
            [
            (
            
              r
              
                p
              
            
            −
            
              r
              
                b
              
            
            
              )
              
                2
              
            
            ]
            −
            (
            
              E
            
            [
            
              r
              
                p
              
            
            −
            
              r
              
                b
              
            
            ]
            
              )
              
                2
              
            
          
        
        =
        
          
            (
            
              w
              
                p
              
            
            −
            
              w
              
                b
              
            
            
              )
              
                T
              
            
            Σ
            (
            
              w
              
                p
              
            
            −
            
              w
              
                b
              
            
            )
          
        
      
    
    {\displaystyle TE=\omega ={\sqrt {\operatorname {Var} (r_{p}-r_{b})}}={\sqrt {{E}[(r_{p}-r_{b})^{2}]-({E}[r_{p}-r_{b}])^{2}}}={\sqrt {(w_{p}-w_{b})^{T}\Sigma (w_{p}-w_{b})}}}
  

where 
  
    
      
        
          r
          
            p
          
        
        −
        
          r
          
            b
          
        
      
    
    {\displaystyle r_{p}-r_{b}}
  
 is the active return, i.e., the difference between the portfolio return and the benchmark return and  
  
    
      
        (
        
          w
          
            p
          
        
        −
        
          w
          
            b
          
        
        )
      
    
    {\displaystyle (w_{p}-w_{b})}
  
 is the vector of active portfolio weights relative to the benchmark. The optimization problem of maximizing the return, subject to tracking error and linear constraints, may be solved using second-order cone programming:
  
    
      
        
          
            argmax
            w
          
        
        
        
          μ
          
            T
          
        
        (
        w
        −
        
          w
          
            b
          
        
        )
        ,
        
        
          s.t.
        
        
        (
        w
        −
        
          w
          
            b
          
        
        
          )
          
            T
          
        
        Σ
        (
        w
        −
        
          w
          
            b
          
        
        )
        ≤
        
          ω
          
            2
          
        
        ,
        
        A
        x
        ≤
        b
        ,
        
        C
        x
        =
        d
      
    
    {\displaystyle {\underset {w}{\operatorname {argmax} }}\;\mu ^{T}(w-w_{b}),\quad {\text{s.t.}}\;(w-w_{b})^{T}\Sigma (w-w_{b})\leq \omega ^{2},\;Ax\leq b,\;Cx=d}

### Interpretation

Under the assumption of normality of returns, an active risk of x per cent would mean that approximately 2/3 of the portfolio's active returns (one standard deviation from the mean) can be expected to fall between +x and -x per cent of the mean excess return and about 95% of the portfolio's active returns (two standard deviations from the mean) can be expected to fall between +2x and -2x per cent of the mean excess return.

## Examples

Index funds are expected to have minimal tracking errors.
Inverse exchange-traded funds are designed to perform as the inverse of an index or other benchmark, and thus reflect tracking errors relative to short positions in the underlying index or benchmark.

### Index fund creation

Index funds are expected to minimize the tracking error with respect to the index they are attempting to replicate, and this problem may be solved using standard optimization techniques. To begin, define 
  
    
      
        
          ω
          
            2
          
        
      
    
    {\displaystyle \omega ^{2}}
  
 to be:
  
    
      
        
          ω
          
            2
          
        
        =
        (
        w
        −
        
          w
          
            b
          
        
        
          )
          
            T
          
        
        Σ
        (
        w
        −
        
          w
          
            b
          
        
        )
      
    
    {\displaystyle \omega ^{2}=(w-w_{b})^{T}\Sigma (w-w_{b})}
  
where 
  
    
      
        w
        −
        
          w
          
            b
          
        
      
    
    {\displaystyle w-w_{b}}
  
 is the vector of active weights for each asset relative to the benchmark index and 
  
    
      
        Σ
      
    
    {\displaystyle \Sigma }
  
 is the covariance matrix for the assets in the index. While creating an index fund could involve holding all 
  
    
      
        N
      
    
    {\displaystyle N}
  
 investable assets in the index, it is sometimes better practice to only invest in a subset 
  
    
      
        K
      
    
    {\displaystyle K}
  
 of the assets. These considerations lead to the following mixed-integer quadratic programming (MIQP) problem:
  
    
      
        
          
            
              
                
                  
                    argmin
                    w
                  
                
              
              
                
                
                  ω
                  
                    2
                  
                
              
            
            
              
                
                  s.t.
                
              
              
                
                
                  w
                  
                    j
                  
                
                ≤
                
                  y
                  
                    j
                  
                
                ,
                
                
                  ∑
                  
                    j
                    =
                    1
                  
                  
                    N
                  
                
                
                  y
                  
                    j
                  
                
                ≤
                K
              
            
            
              
              
                
                
                  ℓ
                  
                    j
                  
                
                
                  y
                  
                    j
                  
                
                ≤
                
                  w
                  
                    j
                  
                
                ≤
                
                  u
                  
                    j
                  
                
                
                  y
                  
                    j
                  
                
                ,
                
                
                  y
                  
                    j
                  
                
                ∈
                {
                0
                ,
                1
                }
                ,
                
                
                  ℓ
                  
                    j
                  
                
                ,
                
                
                  u
                  
                    j
                  
                
                ≥
                0
              
            
          
        
      
    
    {\displaystyle {\begin{aligned}{\underset {w}{\operatorname {argmin} }}&\quad \omega ^{2}\\{\text{s.t.}}&\quad w_{j}\leq y_{j},\quad \sum _{j=1}^{N}y_{j}\leq K\\&\quad \ell _{j}y_{j}\leq w_{j}\leq u_{j}y_{j},\quad y_{j}\in \{0,1\},\quad \ell _{j},\;u_{j}\geq 0\end{aligned}}}
  
where 
  
    
      
        
          y
          
            j
          
        
      
    
    {\displaystyle y_{j}}
  
 is the logical condition of whether or not an asset is included in the index fund, and is defined as:
  
    
      
        
          y
          
            j
          
        
        =
        
          
            {
            
              
                
                  1
                  ,
                  
                
                
                  
                    w
                    
                      j
                    
                  
                  >
                  0
                
              
              
                
                  0
                  ,
                  
                
                
                  
                    otherwise
                  
                
              
            
            
          
        
      
    
    {\displaystyle y_{j}={\begin{cases}1,\quad &w_{j}>0\\0,\quad &{\text{otherwise}}\end{cases}}}
