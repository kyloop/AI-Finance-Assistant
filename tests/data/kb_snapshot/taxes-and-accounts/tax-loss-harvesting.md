# Tax loss harvesting

<!-- https://en.wikipedia.org/wiki/Tax_loss_harvesting | revision 1369509731 -->

Tax loss harvesting (TLH) refers to a category of tax-efficient investment strategies that seek to accelerate the realization of capital losses and defer the realization of capital gains.  
In its most basic form, it occurs when an investor sells a security that has depreciated in value only for the tax losses. The effectiveness of this approach is dependent of the tax rules in a particular jurisdiction. In the United States CBS News describes tax loss harvesting specifically as "selling an investment at a loss with the intention of ultimately repurchasing the same investment after the IRS's 30 day window on wash sales has expired." This allows investors to lower their tax amount with the use of investment losses.

## Overview

Tax loss harvesting can be done throughout the fiscal year but historically has been performed in December. Tax-loss harvesting is still most common in the year's fourth quarter. This allows investors to "offset capital gains with capital losses."  Under United States tax rules, if an investor has more capital losses than gains in a year, that year they can use up to $3,000 as a deduction to "offset ordinary income", with the remainder carrying over into future years if unused. 
In the United Kingdom, a similar practice which specifically takes place at the end of a calendar year is known as bed and breakfasting. In a bed-and-breakfasting transaction, a position is sold on the last trading day of the year (typically late in the trading session) to establish a tax loss. The same position is then repurchased early on the first session of the new trading year, to restore the position (albeit at a lower cost basis). The term, therefore, derives its name from the late sale and early morning repurchase.
Loss harvesting defers taxes, but does not eliminate them, and is essentially receiving a loan without interest from the federal government, assuming marginal tax rates are the same. If marginal rates are different, then there can be additional tax savings (e.g., deducting excess losses against a higher ordinary income rate in one year in exchange for additional long term capital gains tax at a lower rate in a later year) or even a tax penalty (e.g., deducting at a lower capital gains tax rate in several years in exchange for a much larger gain in one later year that puts one in a higher capital gains tax and Medicare investment income tax bracket.)
The practice of tax loss harvesting has been both praised and criticized by investors, as deferring the taxes can result in higher rates later on relating to capital gains.

## Risks

Most simply, if "tax-loss harvesting is not done properly, it will create a wash-sale that will eliminate the tax benefits of the buying and selling". The investor can employ a number of techniques to avoid triggering the wash sale rule. 

The investor can wait 30 days to repurchase the security.
The investor can purchase a security that is similar to the original, but that does not meet the IRS's definition of "substantially identical". For example, an investor can sell an ETF and buy another with similar investment objectives.

## Investment companies

The United States Internal Revenue Service (IRS) has published no exact definition of what constitutes a "substantially identical" security. Therefore, it is not clear whether or not the securities of different investment companies can be "substantially identical", even if their investment objectives are identical. As a result, if an investor trades in and out of exchange-traded funds (ETFs) or mutual funds with almost identical holdings, some have held that it does not trigger the wash sale rule.
For example, State Street's SPDR S&P 500 ETF Trust (NYSE Arca: SPY) and iShares Core S&P 500 ETF (NYSE Arca: IVV) both track the S&P 500. If an investor purchases shares in SPY and the market price declines, the IRS has not provided guidance on whether the investor can sell their shares in SPY, purchase shares in IVV, and claim a capital loss without triggering the wash sale rule, despite the fact that the two ETFs have nearly identical returns.

## Methods

Mean-variance portfolio optimization
One method is to use an initial set of portfolio weights 
  
    
      
        
          w
          
            0
          
        
      
    
    {\displaystyle w_{0}}
  
 and benchmark weights 
  
    
      
        
          w
          
            B
          
        
      
    
    {\displaystyle w_{B}}
  
, it is possible to do TLH within the confines of mean-variance optimization by developing an objective function that maximizes the difference between tax alpha and the portfolio's tracking error:
  
    
      
        
          max
          
            w
          
        
        
        
          
            
              
                
                  α
                  
                    
                      T
                    
                  
                
                (
                w
                −
                
                  w
                  
                    0
                  
                
                )
              
              ⏟
            
          
          
            Tax Alpha
          
        
        −
        
          
            
              
                
                  
                    λ
                    
                      2
                    
                  
                
                (
                w
                −
                
                  w
                  
                    B
                  
                
                
                  )
                  
                    
                      T
                    
                  
                
                Σ
                (
                w
                −
                
                  w
                  
                    B
                  
                
                )
              
              ⏟
            
          
          
            Tracking Error
          
        
      
    
    {\displaystyle \max _{w}\;\underbrace {\alpha ^{\mathrm {T} }(w-w_{0})} _{\text{Tax Alpha}}-\underbrace {{\lambda  \over {2}}(w-w_{B})^{\mathrm {T} }\Sigma (w-w_{B})} _{\text{Tracking Error}}}
  

where 
  
    
      
        λ
      
    
    {\displaystyle \lambda }
  
 is a penalty term for excess tracking error and 
  
    
      
        Σ
      
    
    {\displaystyle \Sigma }
  
 is the covariance matrix of asset returns. For each asset that is bought/sold, it is necessary to include the constraints:
  
    
      
        
          
            {
            
              
                
                  
                    w
                    
                      j
                    
                  
                  ≥
                  
                    w
                    
                      0
                      ,
                      j
                    
                  
                  ,
                  
                
                
                  (
                  
                    buy trades
                  
                  )
                
              
              
                
                  
                    w
                    
                      j
                    
                  
                  ≤
                  
                    w
                    
                      0
                      ,
                      j
                    
                  
                  ,
                  
                
                
                  (
                  
                    sell trades
                  
                  )
                
              
            
            
          
        
      
    
    {\displaystyle {\begin{cases}w_{j}\geq w_{0,j},\quad &({\text{buy trades}})\\w_{j}\leq w_{0,j},\quad &({\text{sell trades}})\end{cases}}}
  

With this formulation, the TLH optimization may be applied within a mean-variance framework. The solution is readily computed using quadratic programming.
