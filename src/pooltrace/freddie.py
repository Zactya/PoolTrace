"""Freddie SFLLD performance tape adapter. Credit observations are NOT MBS disclosures.

Source: July 2026 General User Guide and Disclosure Changes Summary, page 4.
This imports a user-obtained local tape. It does not scrape, download or redistribute data.
"""

import csv
import hashlib
import io
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation

from . import db

GUIDE = "https://www.freddiemac.com/fmac-resources/research/pdf/general_user_guide_july_2026.pdf"


def month(value):
    if not value.strip():
        return None
    return datetime.strptime(value.strip(), "%Y%m").date().replace(day=1).isoformat()


def amount(value):
    if not value.strip():
        return None
    number = Decimal(value)
    if not number.is_finite() or number < 0:
        raise ValueError("balance must be finite and nonnegative")
    return str(number)


def parse_row(fields, release):
    expected = 35 if release == "r47" else 32
    if len(fields) != expected:
        raise ValueError(
            f"{release} requires {expected} pipe-delimited fields, got {len(fields)}"
        )
    loan_id = fields[0].strip()
    period = month(fields[1])
    if not loan_id or len(loan_id) > 80 or not period:
        raise ValueError("loan identifier and reporting month are required")
    rate = float(fields[10]) if fields[10].strip() else None
    if rate is not None and not 0 <= rate <= 30:
        raise ValueError("current interest rate must be a percentage between 0 and 30")
    age = int(fields[4]) if fields[4].strip() else None
    remaining = int(fields[5]) if fields[5].strip() else None
    # Negative remaining terms can be reported; preserve them rather than manufacture a schedule.
    code = fields[8].strip()
    return {
        "schema": "freddie_sfll_performance_" + release,
        "loan_id": loan_id,
        "period": period,
        "current_actual_upb": amount(fields[2]),
        "delinquency_status": fields[3].strip(),
        "loan_age_months": age,
        "remaining_legal_months": remaining,
        "modification_flag": fields[7].strip(),
        "zero_balance_code": code,
        "zero_balance_month": month(fields[9]),
        "current_rate_pct": rate,
        "noninterest_bearing_upb": amount(fields[11]),
        "last_paid_installment_month": month(fields[12]),
        "zero_balance_removal_upb": amount(fields[26]),
        "interest_bearing_upb": amount(fields[31]),
        "exit_label": "voluntary_payoff_or_maturity"
        if code == "01"
        else "other_or_unknown_exit"
        if code
        else "no_reported_exit",
        "pool_mapping": None,
        "provenance": "user_supplied",
        "guide": GUIDE,
    }


def ingest_performance(text, release="r47", source="freddie-sfll"):
    if release not in ("r47", "pre-r47"):
        raise ValueError("Unsupported release")
    if len(text.encode("utf-8")) > 2_000_000:
        raise ValueError("Maximum import size: 2 MB")
    digest = hashlib.sha256(text.encode()).hexdigest()
    batch_id = hashlib.sha256(
        (source + ":" + release + ":" + digest).encode()
    ).hexdigest()[:24]
    fields = list(csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter="|"))
    if not fields or len(fields) > 10000:
        raise ValueError("Performance imports require 1–10,000 rows")
    counts = Counter((f[0], f[1]) for f in fields if len(f) > 1)
    good = []
    bad = []
    for line, f in enumerate(fields, 1):
        try:
            payload = parse_row(f, release)
            if counts[(f[0], f[1])] > 1:
                raise ValueError("duplicate loan/month; all copies quarantined")
            good.append((line, payload))
        except (ValueError, InvalidOperation) as exc:
            bad.append((line, json.dumps(f), str(exc)))
    raw = db.data_dir() / "raw" / (digest + ".txt")
    raw.parent.mkdir(exist_ok=True)
    try:
        with raw.open("x", encoding="utf-8", newline="") as file:
            file.write(text)
    except FileExistsError:
        pass
    changed = unchanged = 0
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute(
            "SELECT * FROM batches WHERE id=?", (batch_id,)
        ).fetchone()
        if existing:
            return dict(existing, idempotent=True, changed=0)
        observed = db.now()
        # Release belongs to batch identity; logical observation source stays stable
        # across releases so later releases can revise earlier observations.
        con.execute(
            "INSERT INTO batches VALUES(?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                source + ":" + release,
                digest,
                "freddie-" + release,
                observed,
                None,
                len(good),
                len(bad),
                str(raw.relative_to(db.data_dir())),
            ),
        )
        for line, payload in good:
            serialized = json.dumps(payload, sort_keys=True)
            row_hash = hashlib.sha256(serialized.encode()).hexdigest()
            previous = con.execute(
                "SELECT id,row_hash FROM performance_versions WHERE source=? AND loan_id=? AND period=? AND known_to IS NULL",
                (source, payload["loan_id"], payload["period"]),
            ).fetchone()
            if previous and previous["row_hash"] == row_hash:
                unchanged += 1
                continue
            if previous:
                con.execute(
                    "UPDATE performance_versions SET known_to=? WHERE id=?",
                    (observed, previous["id"]),
                )
            con.execute(
                "INSERT INTO performance_versions(source,loan_id,period,known_from,payload,row_hash,batch_id) VALUES(?,?,?,?,?,?,?)",
                (
                    source,
                    payload["loan_id"],
                    payload["period"],
                    observed,
                    serialized,
                    row_hash,
                    batch_id,
                ),
            )
            changed += 1
        for line, payload, reason in bad:
            con.execute(
                "INSERT INTO quarantine(batch_id,row_number,payload,reason) VALUES(?,?,?,?)",
                (batch_id, line, payload, reason),
            )
        db.event(
            con,
            "performance.ingested.v1",
            {
                "batch_id": batch_id,
                "schema": "freddie-" + release,
                "changed": changed,
                "unchanged": unchanged,
                "rejected": len(bad),
                "basis": "credit performance; not securities disclosure",
            },
        )
    return {
        "id": batch_id,
        "accepted": len(good),
        "rejected": len(bad),
        "changed": changed,
        "unchanged": unchanged,
        "idempotent": False,
        "basis": "credit performance; no pool mapping or inferred voluntary prepayments",
    }
