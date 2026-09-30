"""Seeded, redistributable fixtures. No agency or commercial vendor observations."""

import math
import random
from datetime import date

from . import db
from .analytics import characteristics, deterministic, payment
from .ingest import csv_for, ingest_csv, next_month
from .models import ReferenceRequest
from .reconcile import add_reference

POOL_NAMES = {
    "DEMO-ATLAS": "Atlas 6.5",
    "DEMO-HARBOR": "Harbor 5.25",
    "DEMO-CEDAR": "Cedar 4.25",
}


def generate():
    rng = random.Random(20260930)
    rows = []
    for pool, gross in zip(POOL_NAMES, [0.065, 0.0525, 0.0425]):
        for loan in range(24):
            balance = round(rng.uniform(180000, 750000), 2)
            age = rng.randint(10, 80)
            for m in range(24):
                period = date(2023 + m // 12, m % 12 + 1, 1).isoformat()
                refinance = 0.054 + 0.008 * math.sin(m / 5)
                scheduled = round(
                    min(
                        balance,
                        max(
                            0,
                            payment(balance, gross, 360 - age - m)
                            - balance * gross / 12,
                        ),
                    ),
                    2,
                )
                probability = 1 / (
                    1
                    + math.exp(
                        -(
                            -5.6
                            + (0.065 - refinance) * 100 * 0.5
                            + min(age + m, 60) / 60 * 0.8
                            + (gross - 0.055) * 45
                            + rng.gauss(0, 0.18)
                        )
                    )
                )
                prepay = round((balance - scheduled) * probability, 2)
                end = round(balance - scheduled - prepay, 2)
                row = {
                    "schema_version": "1.0",
                    "loan_id": f"{pool}-{loan:03}",
                    "pool_id": pool,
                    "period": period,
                    "beginning_balance": f"{balance:.2f}",
                    "ending_balance": f"{end:.2f}",
                    "scheduled_principal": f"{scheduled:.2f}",
                    "prepayment": f"{prepay:.2f}",
                    "other_reduction": "0.00",
                    "gross_rate": gross,
                    "net_rate": gross - 0.003,
                    "remaining_months": 360 - age - m,
                    "age_months": age + m,
                    "refinance_rate": refinance,
                    "event": "active",
                    "provenance": "synthetic",
                }
                rows.append(row)
                balance = end
    return rows


def missing_row(row):
    return row["loan_id"] == "DEMO-ATLAS-007" and row["period"] == "2024-05-01"


def seed():
    rows = generate()
    initial = [r for r in rows if not missing_row(r)]
    bad = dict(rows[0], loan_id="DEMO-INVALID", ending_balance="999999.00")
    result = ingest_csv(csv_for(initial + [bad]), "synthetic-demo")
    with db.connect() as con:
        count = con.execute("SELECT COUNT(*) FROM reference_metrics").fetchone()[0]
    if count == 0:
        for i, pool in enumerate(POOL_NAMES):
            info = characteristics(db.records(pool))
            ref_cpr = 0.12 if i == 0 else 0.08
            metrics = deterministic(info, ref_cpr, 0.045)
            # Inject a real residual in one synthetic reference. References are NOT independent market data.
            add_reference(
                ReferenceRequest(
                    pool_id=pool,
                    source="Synthetic reference scenario",
                    as_of=next_month(info["period"]),
                    price=metrics["price"] + (0.18 if i == 1 else 0),
                    wal=metrics["wal"],
                    duration=metrics["duration"],
                    cpr=ref_cpr,
                    discount_rate=0.045,
                )
            )
    with db.connect() as con:
        for pool in POOL_NAMES:
            if not con.execute(
                "SELECT 1 FROM identifiers WHERE pool_id=?", (pool,)
            ).fetchone():
                con.execute(
                    "INSERT INTO identifiers(pool_id,identifier,valid_from,known_from) VALUES(?,?,?,?)",
                    (pool, pool + "-A", "2023-01-01", db.now()),
                )
    return result


def backfill():
    rows = [r for r in generate() if missing_row(r)]
    return ingest_csv(csv_for(rows), "synthetic-demo")


def restate():
    row = next(
        r
        for r in generate()
        if r["loan_id"] == "DEMO-ATLAS-000" and r["period"] == "2024-12-01"
    )
    row["prepayment"] = f"{float(row['prepayment']) + 1750:.2f}"
    row["ending_balance"] = f"{float(row['ending_balance']) - 1750:.2f}"
    result = ingest_csv(csv_for([row]), "synthetic-demo")
    return result


def remap_identifier():
    timestamp = db.now()
    with db.connect() as con:
        if con.execute(
            "SELECT 1 FROM identifiers WHERE identifier='DEMO-ATLAS-B'"
        ).fetchone():
            return {"idempotent": True}
        old = con.execute(
            "SELECT * FROM identifiers WHERE pool_id='DEMO-ATLAS' AND known_to IS NULL"
        ).fetchone()
        if not old:
            raise ValueError("Load the demo first")
        con.execute(
            "UPDATE identifiers SET known_to=? WHERE id=?", (timestamp, old["id"])
        )
        con.execute(
            "INSERT INTO identifiers(pool_id,identifier,valid_from,valid_to,known_from) VALUES(?,?,?,?,?)",
            (
                "DEMO-ATLAS",
                old["identifier"],
                old["valid_from"],
                "2024-07-01",
                timestamp,
            ),
        )
        con.execute(
            "INSERT INTO identifiers(pool_id,identifier,valid_from,known_from) VALUES(?,?,?,?)",
            ("DEMO-ATLAS", "DEMO-ATLAS-B", "2024-07-01", timestamp),
        )
        db.event(
            con,
            "identifier.corrected.v1",
            {
                "pool_id": "DEMO-ATLAS",
                "from": old["identifier"],
                "to": "DEMO-ATLAS-B",
                "effective": "2024-07-01",
                "provenance": "synthetic",
            },
        )
    return {"idempotent": False, "known_from": timestamp}
