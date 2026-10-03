# Clean price

<!-- https://en.wikipedia.org/wiki/Clean_price | revision 1360637390 -->

Clean price is the quoted price of a bond that excludes accrued interest since the previous coupon date. The corresponding total that includes accrued interest is the dirty or full price. Let 
  
    
      
        
          P
          
            clean
          
        
      
    
    {\displaystyle P_{\text{clean}}}
  
 and 
  
    
      
        
          P
          
            dirty
          
        
      
    
    {\displaystyle P_{\text{dirty}}}
  
 denote prices per 100 of nominal amount, and let 
  
    
      
        
          A
          I
        
      
    
    {\displaystyle \mathrm {AI} }
  
 denote accrued interest for the current coupon period. Then 
  
    
      
        
          P
          
            dirty
          
        
        =
        
          P
          
            clean
          
        
        +
        
          A
          I
        
      
    
    {\displaystyle P_{\text{dirty}}=P_{\text{clean}}+\mathrm {AI} }
  
.
Accrued interest is commonly computed as the coupon for the period multiplied by a day-count fraction under the relevant day-count convention, for example Actual/Actual or 30/360. More complete definitions and formulae are given below.
In many cash markets prices are quoted on a clean basis for comparability across issues, while the cash paid at settlement equals the dirty price that adds accrued interest to the quote. This quoted-clean settled-dirty practice is reflected in official issuance and settlement rules and in index methodology, and clean prices are also used for valuing collateral in repo operations.
For zero-coupon bonds there is no accrued interest, so the clean and dirty prices coincide.

## Concept and calculation

Let prices be quoted per 100 of nominal amount. Let 
  
    
      
        
          A
          I
        
      
    
    {\displaystyle \mathrm {AI} }
  
 denote accrued interest for the current coupon period, 
  
    
      
        C
      
    
    {\displaystyle C}
  
 the coupon due for that period per 100, 
  
    
      
        α
      
    
    {\displaystyle \alpha }
  
 the day-count fraction, 
  
    
      
        d
      
    
    {\displaystyle d}
  
 the number of days since the previous coupon date up to but excluding the settlement date, and 
  
    
      
        D
      
    
    {\displaystyle D}
  
 the number of days in the coupon period under the relevant convention.
For standard coupon periods the accrued interest equals the period coupon multiplied by the elapsed fraction of the period.

  
    
      
        
          A
          I
        
        =
        C
        ×
        α
      
    
    {\displaystyle \mathrm {AI} =C\times \alpha }
  

  
    
      
        α
        =
        
          
            d
            D
          
        
      
    
    {\displaystyle \alpha ={\frac {d}{D}}}
  

Under this definition the dirty price equals the clean price plus accrued interest, and settlement amounts are computed on a per-100 basis accordingly.
The day-count inputs are specified by market rules. In municipal and many corporate markets, 30/360 methods are prescribed and the number of days between dates is computed by rule, with month-end adjustments as set out in Rule G-33. In international bond documentation, Actual/Actual ICMA is widely used, which defines the fraction by dividing days elapsed in the accrual period by the days in the corresponding coupon period, with extensions for long or short periods.

## Market practice and conventions

In most cash bond markets prices are quoted on a clean basis for comparability across issues, while the amount paid at settlement equals the dirty price that adds accrued interest to the quote. This treatment is codified in official rules. In the United States the settlement amount for Treasury notes and bonds includes any accrued interest. In the United Kingdom the gilt market’s published formulae set out how accrued interest is calculated for settlement on a per 100 basis.
In the UK an official end of day set of reference prices is produced for gilts. Tradeweb and FTSE Russell jointly calculate benchmark closing bid, mid and offer prices, which feed the FTSE Actuaries UK Gilts Index Series. The index calculation guide lists the analytics calculated each day, including a gross or dirty price index and accrued interest, and assumes replication at closing middle market prices.
For repo operations it is best practice to value fixed income collateral using the middle clean price in the appropriate market and to include accrued interest up to but excluding the margin delivery date when fixing the collateral market value.

## Worked examples

Assume a bond with a 6% annual coupon paid semiannually, so the coupon per period is 
  
    
      
        C
        =
        3
      
    
    {\displaystyle C=3}
  
 per 100 of nominal, and use the 30/360 US convention for accrual. The day-count fraction is 
  
    
      
        α
        =
        d
        
          /
        
        D
      
    
    {\displaystyle \alpha =d/D}
  
, where 
  
    
      
        D
        =
        180
      
    
    {\displaystyle D=180}
  
 for a half-year and 
  
    
      
        d
      
    
    {\displaystyle d}
  
 is the 30/360 US day count from the last coupon to the settlement date. Accrued interest is 
  
    
      
        
          A
          I
        
        =
        C
        ×
        α
      
    
    {\displaystyle \mathrm {AI} =C\times \alpha }
  
, and the settlement price per 100 equals 
  
    
      
        
          P
          
            dirty
          
        
        =
        
          P
          
            clean
          
        
        +
        
          A
          I
        
      
    
    {\displaystyle P_{\text{dirty}}=P_{\text{clean}}+\mathrm {AI} }
  
.

### Example A: mid-period accrual

Coupons pay on 15 January and 15 July 2025. Settlement is 16 April 2025. Under 30/360 US, the day count is 
  
    
      
        d
        =
        30
        ×
        (
        4
        −
        1
        )
        +
        (
        16
        −
        15
        )
        =
        91
      
    
    {\displaystyle d=30\times (4-1)+(16-15)=91}
  
, so 
  
    
      
        α
        =
        91
        
          /
        
        180
        ≈
        0.5056
      
    
    {\displaystyle \alpha =91/180\approx 0.5056}
  
. The accrued interest is

  
    
      
        
          A
          I
        
        
        =
        
        3
        ×
        
          
            91
            180
          
        
        
        =
        
        1.516
        
          
            6
            ¯
          
        
        
        ≈
        
        1.5167
        
           per 100.
        
      
    
    {\displaystyle \mathrm {AI} \;=\;3\times {\frac {91}{180}}\;=\;1.516{\overline {6}}\;\approx \;1.5167{\text{ per 100.}}}
  

If the quoted clean price is 102.40, the dirty settlement price is 
  
    
      
        102.40
        +
        1.5167
        =
        103.9167
      
    
    {\displaystyle 102.40+1.5167=103.9167}
  
 per 100. This illustrates that clean prices compare issues on a like-for-like basis while cash paid reflects time since the last coupon.

### Example B: eve of coupon

Using the same schedule, take settlement as 14 July 2025. The day count is 
  
    
      
        d
        =
        30
        ×
        (
        7
        −
        1
        )
        +
        (
        14
        −
        15
        )
        =
        179
      
    
    {\displaystyle d=30\times (7-1)+(14-15)=179}
  
, so 
  
    
      
        α
        =
        179
        
          /
        
        180
        ≈
        0.9944
      
    
    {\displaystyle \alpha =179/180\approx 0.9944}
  
 and

  
    
      
        
          A
          I
        
        
        =
        
        3
        ×
        
          
            179
            180
          
        
        
        =
        
        2.983
        
          
            3
            ¯
          
        
        
        ≈
        
        2.9833
        
           per 100.
        
      
    
    {\displaystyle \mathrm {AI} \;=\;3\times {\frac {179}{180}}\;=\;2.983{\overline {3}}\;\approx \;2.9833{\text{ per 100.}}}
  

The dirty price is therefore almost the clean price plus the full coupon, and on the 15 July coupon date the accrued interest resets to zero so the dirty price drops by approximately the coupon while the clean price remains smooth apart from market movements.

### Zero-coupon special case

For a zero-coupon bond, 
  
    
      
        C
        =
        0
      
    
    {\displaystyle C=0}
  
 in every period, so 
  
    
      
        
          A
          I
        
        =
        0
      
    
    {\displaystyle \mathrm {AI} =0}
  
 and the clean and dirty prices are identical by definition.
