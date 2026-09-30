"""Transparent educational analytics; no vendor analytics are emulated."""

import hashlib
import json
import math

import numpy as np

from . import db

CONVENTIONS = "monthly-net-coupon;current-balance;flat-continuous;no-accrual"


def smm(cpr):
    return 1 - (1 - cpr) ** (1 / 12)


def cpr(smm_value):
    return 1 - (1 - min(1, max(0, smm_value))) ** 12


def payment(balance, annual_rate, months):
    r = annual_rate / 12
    return balance / months if r == 0 else balance * r / (1 - (1 + r) ** (-months))


def historical(rows):
    buckets = {}
    for r in rows:
        b = buckets.setdefault(
            r["period"],
            {
                "period": r["period"],
                "beginning_balance": 0.0,
                "ending_balance": 0.0,
                "scheduled_principal": 0.0,
                "prepayment": 0.0,
                "other_reduction": 0.0,
                "net_interest": 0.0,
                "loan_count": 0,
                "provenance": set(),
            },
        )
        for key in [
            "beginning_balance",
            "ending_balance",
            "scheduled_principal",
            "prepayment",
            "other_reduction",
        ]:
            b[key] += float(r[key])
        b["net_interest"] += float(r["beginning_balance"]) * r["net_rate"] / 12
        b["loan_count"] += 1
        b["provenance"].add(r["provenance"])
    for b in buckets.values():
        # Other reductions are explicitly excluded from the voluntary-prepayment numerator.
        exposure = b["beginning_balance"] - b["scheduled_principal"]
        b["smm"] = b["prepayment"] / exposure if exposure > 0 else 0
        b["cpr"] = cpr(b["smm"])
        b["investor_cashflow_estimate"] = (
            b["scheduled_principal"] + b["prepayment"] + b["net_interest"]
        )
        b["provenance"] = sorted(b["provenance"])
    return sorted(buckets.values(), key=lambda b: b["period"])


def characteristics(rows, allow_incomplete=False):
    if not rows:
        raise ValueError("No observations at this knowledge time")
    period = max(r["period"] for r in rows)
    last_by_loan = {}
    for row in sorted(rows, key=lambda r: r["period"]):
        last_by_loan[row["loan_id"]] = row
    missing = [
        loan
        for loan, row in last_by_loan.items()
        if row["period"] < period and float(row["ending_balance"]) > 0
    ]
    if missing and not allow_incomplete:
        raise ValueError(
            f"Incomplete pool snapshot at {period}: {len(missing)} active loan(s) lack a current observation"
        )
    latest = [
        r for r in rows if r["period"] == period and float(r["ending_balance"]) > 0
    ]
    balance = sum(float(r["ending_balance"]) for r in latest)
    if balance <= 0:
        raise ValueError("Pool has no outstanding balance")

    def weighted(key):
        return sum(float(r["ending_balance"]) * float(r[key]) for r in latest) / balance

    return {
        "period": period,
        "balance": balance,
        "gross_rate": weighted("gross_rate"),
        "net_rate": weighted("net_rate"),
        "remaining_months": max(1, round(weighted("remaining_months")) - 1),
        "loan_count": len(latest),
        "age_months": weighted("age_months"),
        "refinance_rate": weighted("refinance_rate"),
        "snapshot_complete": not missing,
        "missing_loans": missing,
    }


def project(info, annual_cpr):
    balance = info["balance"]
    monthly_prepay = smm(annual_cpr)
    result = []
    for month in range(1, info["remaining_months"] + 1):
        remaining = info["remaining_months"] - month + 1
        principal = min(
            balance,
            max(
                0,
                payment(balance, info["gross_rate"], remaining)
                - balance * info["gross_rate"] / 12,
            ),
        )
        prepay = (balance - principal) * monthly_prepay if remaining > 1 else 0
        interest = balance * info["net_rate"] / 12
        result.append(
            {
                "month": month,
                "scheduled_principal": principal,
                "prepayment": prepay,
                "interest": interest,
                "principal": principal + prepay,
                "total": principal + prepay + interest,
            }
        )
        balance = max(0, balance - principal - prepay)
    return result


def deterministic(info, annual_cpr, discount_rate):
    flows = project(info, annual_cpr)
    times = np.array([f["month"] / 12 for f in flows])
    totals = np.array([f["total"] for f in flows])
    principal = np.array([f["principal"] for f in flows])

    def price(rate):
        return float(np.sum(totals * np.exp(-rate * times)) / info["balance"] * 100)

    p = price(discount_rate)
    bump = 0.0001
    return {
        "price": p,
        "wal": float(np.sum(principal * times) / info["balance"]),
        "duration": (price(discount_rate - bump) - price(discount_rate + bump))
        / (2 * p * bump),
        "convexity": (price(discount_rate - bump) + price(discount_rate + bump) - 2 * p)
        / (p * bump * bump),
        "flows": flows,
    }


def stochastic_oas(info, scenario):
    """Antithetic Vasicek paths + rate-responsive CPR. Assumed, NOT market-calibrated."""
    n, months = scenario.paths, info["remaining_months"]
    rng = np.random.default_rng(scenario.seed)
    shocks = rng.normal(size=((n + 1) // 2, months))
    shocks = np.concatenate([shocks, -shocks], axis=0)[:n]
    rate = np.full(n, scenario.discount_rate)
    balance = np.full(n, info["balance"])
    cumulative_rate = np.zeros(n)
    discounted = []
    for m in range(months):
        # Risk-neutral dynamics assumed. Monthly simulation, no fitted market term structure.
        rate = (
            rate
            + 0.25 * (scenario.discount_rate - rate) / 12
            + scenario.volatility / math.sqrt(12) * shocks[:, m]
        )
        annual_cpr = np.clip(
            scenario.cpr * np.exp(8 * (scenario.discount_rate - rate)), 0, 0.8
        )
        prepay_rate = 1 - (1 - annual_cpr) ** (1 / 12)
        remaining = months - m
        r = info["gross_rate"] / 12
        pmt = (
            balance / remaining
            if r == 0
            else balance * r / (1 - (1 + r) ** (-remaining))
        )
        scheduled = np.minimum(balance, np.maximum(0, pmt - balance * r))
        prepay = (balance - scheduled) * prepay_rate if remaining > 1 else np.zeros(n)
        cf = scheduled + prepay + balance * info["net_rate"] / 12
        cumulative_rate += rate / 12
        discounted.append(cf * np.exp(-cumulative_rate))
        balance = np.maximum(0, balance - scheduled - prepay)
    discounted = np.array(discounted)
    times = np.arange(1, months + 1) / 12

    def prices(spread):
        return (
            (discounted * np.exp(-spread * times[:, None])).sum(axis=0)
            / info["balance"]
            * 100
        )

    lo, hi = -0.2, 0.5
    if not prices(hi).mean() <= scenario.market_price <= prices(lo).mean():
        return {
            "oas_bps": None,
            "price_standard_error": None,
            "label": "Target price outside solver bracket",
        }
    for _ in range(55):
        mid = (lo + hi) / 2
        if prices(mid).mean() > scenario.market_price:
            lo = mid
        else:
            hi = mid
    fitted = prices((lo + hi) / 2)
    # Antithetic observations are dependent; use pair averages for the error estimate.
    half = n // 2
    pairs = (fitted[:half] + fitted[(n + 1) // 2 : (n + 1) // 2 + half]) / 2
    return {
        "oas_bps": (lo + hi) / 2 * 10000,
        "price_standard_error": float(np.std(pairs, ddof=1) / math.sqrt(half)),
        "error_unit": "price points per 100 of current balance",
        "label": "Illustrative OAS · assumed Vasicek + rate-responsive CPR; not market calibrated",
    }


def analyze(pool_id, scenario, knowledge_at=None, persist=True):
    knowledge_at = knowledge_at or db.now()
    rows = db.records(pool_id, knowledge_at)
    info = characteristics(rows)
    metrics = deterministic(info, scenario.cpr, scenario.discount_rate)
    oas = stochastic_oas(info, scenario)
    inputs_hash = hashlib.sha256(
        json.dumps(
            {
                "versions": [r["version_id"] for r in rows],
                "scenario": scenario.model_dump(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    result = {
        "pool_id": pool_id,
        "characteristics": info,
        "scenario": scenario.model_dump(),
        "knowledge_at": knowledge_at,
        "inputs_hash": inputs_hash,
        "metrics": {k: v for k, v in metrics.items() if k != "flows"},
        "projection": metrics["flows"],
        "oas": oas,
        "conventions": CONVENTIONS,
        "duration_type": "fixed_cashflow_parallel_rate",
        "projection_method": "representative weighted-average loan; monthly at par start; not a contractual agency payment engine",
    }
    if persist:
        with db.connect() as con:
            cursor = con.execute(
                "INSERT INTO analytics_runs(pool_id,created_at,knowledge_at,inputs_hash,payload) VALUES(?,?,?,?,?)",
                (pool_id, db.now(), knowledge_at, inputs_hash, json.dumps(result)),
            )
            result["run_id"] = cursor.lastrowid
            db.event(
                con,
                "analytics.completed.v1",
                {
                    "pool_id": pool_id,
                    "run_id": cursor.lastrowid,
                    "inputs_hash": inputs_hash,
                },
            )
    return result


def fit_prepayment(rows):
    months = sorted({r["period"] for r in rows})
    if len(months) < 8:
        raise ValueError(
            "At least eight reporting months required for a temporal holdout"
        )
    split = months[max(1, int(len(months) * 0.7))]
    samples = []
    for r in rows:
        exposure = float(r["beginning_balance"]) - float(r["scheduled_principal"])
        if exposure <= 0 or r["event"] in ("liquidated", "repurchased"):
            continue
        observed = float(r["prepayment"]) / exposure
        x = [
            1,
            (r["gross_rate"] - r["refinance_rate"]) * 100,
            min(r["age_months"], 60) / 60,
        ]
        samples.append((r["period"], x, observed, exposure))
    training = [s for s in samples if s[0] < split]
    testing = [s for s in samples if s[0] >= split]
    if len(training) < 3 or not testing:
        raise ValueError("Insufficient eligible observations")
    X = np.array([s[1] for s in training])
    clipped = np.clip([s[2] for s in training], 0.00001, 0.9999)
    y = np.log(clipped / (1 - clipped))
    weights = np.array([s[3] for s in training])
    weights /= weights.mean()
    coefficients = np.linalg.solve(
        X.T @ (X * weights[:, None]) + np.diag([0.000001, 0.1, 0.1]),
        X.T @ (weights * y),
    )
    baseline = sum(s[2] * s[3] for s in training) / sum(s[3] for s in training)
    buckets = {}
    for period, x, observed, exposure in samples:
        predicted = 1 / (1 + math.exp(-float(np.dot(x, coefficients))))
        b = buckets.setdefault(
            period,
            {
                "period": period,
                "observed": 0.0,
                "predicted": 0.0,
                "weight": 0.0,
                "split": "test" if period >= split else "train",
            },
        )
        b["observed"] += observed * exposure
        b["predicted"] += predicted * exposure
        b["weight"] += exposure
    for b in buckets.values():
        b["observed_cpr"] = cpr(b.pop("observed") / b["weight"])
        b["predicted_cpr"] = cpr(b.pop("predicted") / b["weight"])
        b["baseline_cpr"] = cpr(baseline)
    holdout = [b for b in buckets.values() if b["split"] == "test"]
    return {
        "method": "Exposure-weighted ridge regression on logit(SMM)",
        "features": [
            "intercept",
            "refinance incentive (percentage points)",
            "seasoning capped at 60 months",
        ],
        "coefficients": coefficients.tolist(),
        "split_period": split,
        "training_rows": len(training),
        "test_rows": len(testing),
        "test_mae_cpr_pp": float(
            np.mean(
                [abs(b["observed_cpr"] - b["predicted_cpr"]) * 100 for b in holdout]
            )
        ),
        "baseline_mae_cpr_pp": float(
            np.mean([abs(b["observed_cpr"] - b["baseline_cpr"]) * 100 for b in holdout])
        ),
        "series": sorted(buckets.values(), key=lambda b: b["period"]),
        "limitation": "Temporal split of the supplied vintage, not a historical-vintage backtest. Synthetic data performance is not evidence of market predictive skill.",
    }
