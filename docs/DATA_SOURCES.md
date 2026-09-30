# Data access and source boundaries

Source documentation reviewed on September 30, 2026. Bundled datasets are synthetic. External loan-level files and commercial reference exports are supplied separately by the operator under the applicable access terms.

| Source | Appropriate use | Current implementation |
|---|---|---|
| [Freddie SFLLD](https://www.freddiemac.com/research/datasets/sf-loanlevel-dataset) | Credit-performance observations and prepayment research; explicitly not securities disclosure | Local pipe-file importer with separate performance storage. |
| [Fannie loan performance](https://capitalmarkets.fanniemae.com/credit-risk-transfer/single-family-credit-risk-transfer/fannie-mae-single-family-loan-performance-data) | Selected historical credit performance; source-specific terms and registration | Researched, adapter not implemented. |
| [Freddie MBS disclosures](https://capitalmarkets.freddiemac.com/mbs/docs/disclosure_guide.pdf) | Security identity, loan/pool relationship, factors and corrections | Planned for a real fixed-rate UMBS pass-through reconciliation. |
| [Freddie payment calculations](https://capitalmarkets.freddiemac.com/mbs/docs/fs_paymentcalc.pdf) | Official principal/interest and payment convention reference | Methodological reference; contractual engine not implemented. |
| [Ginnie disclosures](https://bulk.ginniemae.gov/) | Loan/pool/security disclosures and factors | Researched only; access workflow and redistribution rights not established. |
| [Fannie Benchmark CPR](https://capitalmarkets.fanniemae.com/mortgage-backed-securities/single-family-mbs/benchmark-cpr-methodology-overview) | Official prepayment methodology reference | Research reference; the educational model is not a reproduction of their benchmark. |
| [PolyPaths products](https://polypaths.com/products/) | Licensed valuation, OAS and risk analytics | Generic external-reference contract only. No SDK/API integration or vendor comparison tested. |

## Why the demo is synthetic

Public accessibility is not a redistribution license. Review [Freddie's current terms](https://www.freddiemac.com/terms) and the terms accepted when obtaining any dataset. Access may require registration, and automated collection or redistribution may need additional authorization. PoolTrace supplies a local importer; it does not scrape agency sites or automate acceptance of terms.

Keep obtained files in `private/` or `data/`, both ignored by Git. Do not publish their rows, screenshots or derived exports unless the applicable agreement permits it. An MIT code license cannot relicense external data.

## Freddie performance profiles

Layout sources:

- [July 2026 General User Guide](https://www.freddiemac.com/fmac-resources/research/pdf/general_user_guide_july_2026.pdf), file format and field definitions.
- [Disclosure Changes Summary](https://www.freddiemac.com/fmac-resources/research/pdf/disclosure-changes-summary.pdf), page 4, R47 performance layout.

No header; delimiter `|`. `r47` expects 35 fields. `pre-r47` expects 32. Positions below are one-based:

| Position | Parsed field |
|---|---|
| 1 | Loan identifier |
| 2 | Reporting month, YYYYMM |
| 3 | Current actual UPB |
| 4 | Delinquency status |
| 5 | Loan age |
| 6 | Remaining months to legal maturity |
| 8 | Modification flag |
| 9 | Zero-balance code |
| 10 | Zero-balance effective month |
| 11 | Current interest rate, **percentage units** |
| 12 | Non-interest-bearing UPB |
| 13 | Last-paid-installment month |
| 27 | Zero-balance removal UPB |
| 32 | Interest-bearing UPB |

All original fields remain in the raw file. Blank values remain unknown, not zero. Exit `01` means payoff **or maturity**, so the importer labels it `voluntary_payoff_or_maturity` and does not manufacture a prepayment measure. Balance rounding, modifications, delinquency and liquidations prevent a naïve balance-difference inference. No loan-to-pool/CUSIP mapping is assumed.

The fixture validates field alignment and behavior against a constructed record. Testing against an actual authorized tape and source totals is an explicit next acceptance step.
