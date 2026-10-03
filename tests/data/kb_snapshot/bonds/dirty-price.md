# Dirty price

<!-- https://en.wikipedia.org/wiki/Dirty_price | revision 1334446870 -->

Dirty price is the total amount paid for a bond at settlement. It equals the quoted clean price plus the accrued interest that has built up since the previous coupon date. Many bond markets quote prices on a clean basis to aid comparison, while the cash exchanged at settlement uses the dirty price. Between coupon dates the dirty price rises as interest accrues and then drops on the coupon date when accrued interest resets to zero. For zero-coupon bonds there is no accrued interest, so the dirty and clean prices are the same.

## Concept and calculation

Let 
  
    
      
        
          P
          
            dirty
          
        
      
    
    {\displaystyle P_{\text{dirty}}}
  
 denote the settlement (total) price per 100 nominal, 
  
    
      
        
          P
          
            clean
          
        
      
    
    {\displaystyle P_{\text{clean}}}
  
 the quoted clean price, 
  
    
      
        
          AI
        
      
    
    {\displaystyle {\text{AI}}}
  
 the accrued interest since the previous coupon date, 
  
    
      
        C
      
    
    {\displaystyle C}
  
 the coupon for the period per 100 nominal, and 
  
    
      
        α
      
    
    {\displaystyle \alpha }
  
 the accrual fraction under the relevant day-count.
The relationship is

  
    
      
        
          P
          
            dirty
          
        
        =
        
          P
          
            clean
          
        
        +
        
          AI
        
      
    
    {\displaystyle P_{\text{dirty}}=P_{\text{clean}}+{\text{AI}}}
  
.
Accrued interest is commonly computed as the coupon for the period multiplied by a day-count fraction,

  
    
      
        
          AI
        
        =
        C
        ×
        α
      
    
    {\displaystyle {\text{AI}}=C\times \alpha }
  
,
so the dirty price rises between coupon dates as interest accrues and then drops on the coupon date when accrued interest resets to zero.
Prices are typically quoted per 100 nominal. For zero-coupon bonds there is no accrued interest, so the dirty and clean prices coincide.
In some markets inflation-linked bonds scale both the clean price and the accrued interest by an index ratio; see Special cases.

## Day-count conventions

The accrual fraction 
  
    
      
        α
      
    
    {\displaystyle \alpha }
  
 used to compute accrued interest depends on the instrument’s day-count convention and the market’s practice. A widely used method for fixed-rate non-USD bonds is Actual/Actual (ICMA), which defines how to count days and the year basis across coupon periods. In the United Kingdom gilt market, accrued interest is calculated using the convention set out in the official pricing formulae. In the United States municipal and many corporate markets, standardised methods such as 30/360 are prescribed for accrual and related calculations.

## Example

A bond pays semi-annual coupons on 15 January and 15 July and settles on 25 January 2025. Using the 30/360 US day-count and prices per 100 nominal:

Days accrued since the previous coupon date: 
  
    
      
        α
        =
        10
        
          /
        
        360
      
    
    {\displaystyle \alpha =10/360}
  
.
Coupon for the period (annual coupon rate 7.2%): 
  
    
      
        C
        =
        0.072
        ×
        100
        
          /
        
        2
        =
        3.60
      
    
    {\displaystyle C=0.072\times 100/2=3.60}
  
.
Accrued interest: 
  
    
      
        
          AI
        
        =
        C
        ×
        α
        =
        3.60
        ×
        10
        
          /
        
        360
        =
        0.10
      
    
    {\displaystyle {\text{AI}}=C\times \alpha =3.60\times 10/360=0.10}
  
.
If the quoted clean price is 98.90, then the settlement (dirty) price is 
  
    
      
        
          P
          
            dirty
          
        
        =
        98.90
        +
        0.10
        =
        99.00
      
    
    {\displaystyle P_{\text{dirty}}=98.90+0.10=99.00}
  
.

## Market practice and conventions

In many bond markets prices are quoted on a clean basis to aid comparison across issues, while settlement amounts are paid on a dirty basis that includes accrued interest.
In the United Kingdom gilt market, trades that settle within the ex-dividend period follow special rules: a buyer whose trade settles in this period does not pay accrued interest and instead receives rebate interest as set out in official guidance. 
In repo markets, best practice for collateral valuation is to use the middle clean price rather than a dirty price.
In the United States municipal and many corporate markets, standardised methods (such as 30/360) are prescribed for day-count and accrued-interest calculations used in settlement.
In exchange-traded bond futures, the conversion-factor system scales the futures price to a clean price; accrued interest is then added to determine the cash invoice at delivery.
In distressed situations some bonds may trade “flat”, with no accrued interest added to the clean price; see Special cases.
Some sources use “gross” and “net” as synonyms for dirty and clean prices; repo documentation commonly expresses these conventions explicitly.

## Futures and delivery invoice

For bond futures the delivery payment uses a conversion-factor system. The invoice amount for delivery equals the futures settlement price multiplied by the contract’s conversion factor, with accrued interest on the delivered bond added separately: 
  
    
      
        
          Invoice amount
        
        =
        F
        ×
        
          CF
        
        +
        
          AI
        
      
    
    {\displaystyle {\text{Invoice amount}}=F\times {\text{CF}}+{\text{AI}}}
  
 (per 100 nominal).
In US Treasury futures, the conversion factor is defined so that the delivered security is priced to a notional yield of 6 per cent; exchanges publish factors and the calculation method. This mirrors cash-bond practice: the scaled futures price corresponds to a clean price, while accrued interest is added to obtain the cash amount paid at delivery.
UK gilt futures apply the same principle: the invoicing amount is determined by a published price-factor system with an adjustment for full coupon interest accruing at settlement.

## Special cases

Some instruments or trading situations modify how accrued interest is calculated or whether it is included in settlement.

### Index-linked bonds

For inflation-indexed securities, both price and accrued interest are scaled by an index ratio that reflects inflation over a defined lag. In the United Kingdom, index-linked gilts with a three-month lag use a daily index ratio; accrued interest is computed on real amounts and then converted to nominal using that ratio. Similar treatment applies in other markets; for example, Canadian real return bonds calculate real accrued interest and then apply an index ratio to obtain nominal settlement amounts.

### Trading flat (no accrued interest)

Some distressed or defaulted bonds are quoted and settled “flat”, meaning without adding accrued interest. In such cases the price represents the whole consideration.

### Zero-coupon bonds and STRIPS

For zero-coupon securities there is no accrued interest; the dirty and clean prices coincide. U.S. Treasury STRIPS are zero-coupon pieces created by separating coupons and principal from coupon bonds and therefore also have no accrued interest.

### Floating-rate notes

For a floating-rate note the coupon for the accrual period is set at the most recent reset and interest accrues each day at that period’s rate; settlement conventions follow the market’s day-count (often Actual/360 in money markets).

### Amortising and mortgage-backed securities

Amortising securities, including many mortgage-backed instruments, accrue interest on the outstanding principal and typically use money-market day-count bases in US practice; industry rules specify clearance and settlement, including accrued-interest conventions for to-be-announced (TBA) trading.

### Irregular first/last coupon periods

Where a bond has a long or short first or last coupon (a “stub” period), the accrual fraction is computed under the applicable day-count rules by splitting into notional periods defined by the normal payment schedule.

## History and terminology

Bond markets have long distinguished between the quoted price that excludes accrued interest (the clean price) and the settlement amount that includes it (the dirty price). In the United Kingdom gilt market this practice is documented at least as far back as the 1990s: clean prices are usually quoted for comparison, while transactions occur at the dirty price, which is the clean price plus accrued interest.
Different publications and markets use near-synonyms for these terms. The dirty price is also called the full, gross or invoice price; the clean price is also called the flat, net or quoted price. Macroeconomic and statistical manuals similarly value debt securities at dirty prices because the change from clean to dirty between coupon dates reflects the accrual of interest.
Conventions have varied across markets and over time. For example, an SEC no-action letter on the Cairo & Alexandria Stock Exchanges recorded that bonds were quoted on a dirty basis with an intention to move to clean quoting, illustrating that “clean quoted, dirty paid” is the prevailing but not universal convention. For inflation-linked bonds, some European Central Bank publications describe quoted prices as “double clean” (excluding both interest accrual and contemporaneous inflation indexation), with settlement reflecting the addition of both components.

## Data and indices

Fixed-income indices typically store or convert constituent prices to clean prices (excluding accrued interest) for comparability, while market value and returns use full (dirty) prices that add accrued interest.
