# Validation report

Local validation on Windows with Python 3.10, September 30, 2026.

The release package passes **24 automated tests**. The frontend also passes `node --check`. Browser observations below describe the recorded walkthrough captured in this release's screenshots.

- Installed the project into a fresh `.venv` from its declared dependencies, then recorded transitive versions in `requirements-lock.txt`.
- The financial/data/API suite verifies idempotence, quarantine, concurrent revisions, old knowledge, backfill, incomplete snapshots, principal conservation, a zero-rate analytic case, CPR/SMM conversion, seeded OAS, measured reconciliation attribution, compatibility before tolerance, resolution evidence, reference supersession and time-separated model fitting.
- The standalone evidence script runs against an isolated temporary database. Its machine-readable output is `demo-evidence.json`.
- A separate consumer successfully imported 17 app events on its first local run and zero on the second unchanged run. Those were execution-specific event counts, not a fixed performance benchmark.
- The browser walkthrough verified a CPR change from 8% to 12% changed projected price from about 110.410 to 108.382 and WAL from about 8.02 to 6.20 years on the synthetic Atlas pool.
- The UI backfill recovered its missing month. The time-machine view showed both the $9,380 and $11,130 rounded loan-prepayment values after a $1,750 correction.
- A supported browser registered the read-only workspace WebMCP tool. Valid input returned current state; unexpected input was rejected.
- The browser workflow saved an analyst and investigation note and showed the persisted review. A mobile viewport check returned equal body and viewport widths (375 px), with no page-level horizontal overflow; tables retain their own horizontal scrolling.
- Real product captures are in `screenshots/overview.jpg`, `screenshots/time-machine.jpg`, `screenshots/reconciliation.jpg` and `screenshots/mobile.jpg`. The browser console had no captured errors in this walkthrough.

## Not executed or not established

- No actual agency tape, issuer cashflow comparison or PolyPaths/Bloomberg/Intex run.
- No predictive validation on real loans or market calibration of OAS.
- Docker execution has not been validated.
- The local report does not cover hosted CI results, public deployment, a multi-user security audit or throughput benchmarks.

The dependency stack emits one upstream Starlette/AnyIO deprecation warning during local tests. It does not fail those tests.
