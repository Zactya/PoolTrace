# Financial and temporal methodology

## Instrument boundary

The demonstrator uses fixed-rate synthetic mortgage pools. A canonical record is a loan-month observation with explicit scheduled principal, voluntary prepayment and other reductions. It is not a complete agency security record. Fees, guarantees, advances, remittances, contractual payment lags, holidays, loan removals and REMIC waterfalls are not modeled.

Each loan-month must satisfy, within $0.02:

`beginning_balance = ending_balance + scheduled_principal + prepayment + other_reduction`

Rates must be finite and bounded; net coupon cannot exceed gross borrower rate. A liquidation or repurchase cannot simultaneously be classified as voluntary prepayment. Exit events require zero ending balance. Duplicates inside one file are quarantined, and an overlapping loan-month from another source cannot silently double the pool.

Input amounts use decimal validation. Analytical projections use double-precision arithmetic without intermediate cent rounding. This is a research convention, not a claim of issuer cent-level agreement.

## Historical cashflow estimates

For an observation, net interest is estimated as beginning balance × annual net rate / 12. The displayed investor cashflow estimate is scheduled principal + voluntary prepayment + net interest. Other reductions remain visible separately and are not assumed to be cash paid to investors.

SMM = voluntary prepayment / (beginning balance − scheduled principal). CPR = 1 − (1 − SMM)^12. Event classification is essential: a zero balance or falling UPB does not itself establish voluntary prepayment. Observed values remain unmodified; clipping is only used for the training logit.

The UI aggregates reported rows. Coverage findings remain visible; historical totals with a gap are partial. A latest snapshot missing an earlier active loan blocks valuation rather than silently shrinking the portfolio.

## Projection, price, WAL and duration

The current pool is approximated by a representative loan using ending-balance-weighted gross rate, net rate and remaining maturity. This approximation is intentional and disclosed; heterogeneity and loan-level waterfalls are not preserved.

Each future month:

1. Recalculate the level amortization payment from remaining balance, gross rate and remaining term.
2. Derive scheduled principal after gross interest.
3. Apply SMM to the balance after scheduled principal.
4. Calculate investor interest from the net coupon.

Principal is conserved across the projection. At zero rates, level principal provides an independent analytic test with a known price and WAL.

- **Price:** present value / current balance × 100. Flat continuously compounded discount rate; monthly payments at month-end; no accrued interest.
- **WAL:** sum of principal × years to payment / current balance. Interest is excluded.
- **Duration:** central ±1 bp shift of the discount rate with cashflows held fixed. It is named `fixed_cashflow_parallel_rate`, not effective mortgage duration.
- **Convexity:** central second difference under the same fixed-cashflow convention.

The valuation date is the first day following the latest reporting month. References must match it and the basis string before numerical comparisons can be treated as comparable.

## Illustrative OAS

The optional educational OAS calculation assumes monthly Vasicek short-rate dynamics, mean reversion of 0.25, a long-run mean equal to the supplied flat discount rate, and a user-selected volatility. Antithetic random paths share a fixed seed. The CPR responds exponentially to the simulated rate deviation and is capped at 80%.

The engine solves a spread in the [-20%, +50%] annual range so that the average discounted cashflows equal the supplied target price. A price outside the bracket returns an unavailable result. Rates can be negative under Vasicek.

**No market curve, volatility surface, risk-neutral calibration or empirical refinance function has been fitted.** The result demonstrates an option-sensitive algorithm; it is not a market quote or a PolyPaths-equivalent valuation. Standard error is calculated across antithetic pair averages and is expressed in **price points per 100**, not OAS basis points. Paths must be even. External OAS comparisons always require a model-basis review.

## Reconciliation and review

Dates, conventions and duration definitions are checked before tolerance. Incompatible inputs produce review exceptions even when their numerical values coincide.

For comparable price/WAL/duration differences, the engine substitutes the reference CPR and discount rate and recomputes the metric. `assumptions_explained` requires the resulting residual to be within tolerance. Otherwise an assumption mismatch and remaining residual are both retained. Small differences are not automatically called rounding errors.

Tolerances are absolute metric units: price points, years and OAS basis points. A stable evidence fingerprint includes input versions, reference identity, classification, assumptions, delta and tolerance. A repeated run with unchanged evidence preserves a manual resolution. Changed evidence reopens the exception. Auto-resolution stores the current run evidence. Reviews require an owner and note; the local prototype does not authenticate the person behind that owner label.

The most recently imported reference per pool is active. Importing a new reference marks older exceptions `superseded` and preserves their evidence. Superseded is distinct from financially reconciled; those exceptions cannot be edited as current cases.

## Valid time, system time and publication history

- **Valid time:** the monthly interval `[period, next_month)` to which an observation applies.
- **System time:** `[known_from, known_to)` during which this system considered that version current.
- **Published time:** optional source-supplied publication timestamp; stored separately from receipt time.

System timestamps are assigned after obtaining the write lock. The old version is closed and the replacement inserted in one transaction. Queries normalize timezone offsets to fixed-width UTC. Raw source content is retained by hash.

Downloading a revised history today cannot establish what users knew years ago. The demo's economic periods are historical; its receipt timestamps are actual current execution times. Publication-vintage backtests remain a future capability once dated original publications are available.

Identifier aliases use both effective intervals and knowledge intervals. Synthetic identifiers deliberately do not resemble claims of verified CUSIP/ISIN mapping.

## Prepayment model

The benchmark regresses logit(SMM) on an intercept, refinance incentive in percentage points and loan seasoning capped at 60 months. It uses exposure weights and a small ridge penalty. The earliest 70% of distinct months train the coefficients; later months form a holdout. No random row split is used. A test proves that changing holdout targets does not change fitted coefficients.

Outputs show observed and predicted CPR and percentage-point mean absolute error, alongside a training-period average-SMM baseline. This is a temporal split of the supplied vintage, not a point-in-time vintage backtest. Synthetic performance is not evidence of out-of-sample skill on real mortgages. Portfolio selection, survivor bias, missing observations and publication delays need explicit treatment before a research claim on actual data.
