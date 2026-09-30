# Product roadmap

PoolTrace v0.1 provides seven working views for ingestion, historical analysis and reconciliation. The next milestones extend source coverage, model validation and shared operations.

## 1. First real-data acceptance

- Obtain one authorized Freddie SFLLD sample locally and record the exact release, guide, publication date and checksum.
- Compare parser counts, balances, missingness and exit codes with source totals. Add sanitized aggregate evidence only if permitted.
- Keep credit observations separate from a security pool. Validate the reference contract with a real permitted export when one is available.

## 2. First actual agency pool

- Choose a fixed-rate pass-through pool and obtain its dated loan/security disclosures, membership, factors, coupon, fees and payment terms.
- Implement the source-specific mapping with versioned schema fixtures. Add loan-level scheduled/remittance calculations and contractual payment dates.
- Reconcile at least several periods to published issuer factors and cashflows. Explain rounding, removals, missing fields and unresolved residuals.
- Publish only allowed evidence and explicitly separate synthetic demonstrations from independently validated results.

## 3. Models and research

- Calibrate prepayment on authorized historical observations with publication lags, explicit cohort definitions, survivorship controls and a held-out period.
- Add a fitted market curve and a documented rate/volatility calibration before making a market OAS claim.
- Add effective duration with scenario-dependent prepayments; retain the existing fixed-cashflow duration under its own definition.
- Evaluate real dated vintages; a temporal row split alone is insufficient for a historical knowledge claim.

## 4. Integration and operations

- Map a permitted PolyPaths export/SDK response to the reference contract and compare matching conventions. Add Bloomberg/Intex only when access and redistribution terms permit.
- Implement authorized download/feed discovery, retries, manifests and release monitoring for each agency, subject to source access terms.
- Add PostgreSQL, columnar raw/normalized storage, a job queue and scheduled incremental processing if scale calls for them.
- Introduce actual analyst identities, role-based access, service ownership, notifications and deployment controls for shared use.
- Benchmark throughput, recovery and resource usage against documented workload sizes.

## 5. Documentation and reproducibility

- Extend the executable walkthrough with source-specific reconciliation examples.
- Maintain generated contracts and regression fixtures alongside each adapter.
- Add architecture decision records as storage, processing and deployment requirements evolve.
