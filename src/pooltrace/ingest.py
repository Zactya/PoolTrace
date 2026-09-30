"""Canonical CSV ingestion: immutable raw bytes, validation, quarantine and revisions."""

import csv
import hashlib
import io
import json
from collections import Counter
from datetime import date, datetime, timezone

from . import db
from .models import LoanMonth


def next_month(value):
    d = date.fromisoformat(str(value))
    return date(
        d.year + (d.month == 12), 1 if d.month == 12 else d.month + 1, 1
    ).isoformat()


def csv_for(rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(LoanMonth.model_fields))
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in LoanMonth.model_fields})
    return out.getvalue()


def ingest_csv(content, source, published_at=None):
    if not content or len(content.encode("utf-8")) > 2_000_000:
        raise ValueError("CSV must be nonempty and no larger than 2 MB")
    observed = db.now()
    if published_at:
        parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("published_at requires a timezone")
        published_at = (
            parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        if parsed > datetime.fromisoformat(observed.replace("Z", "+00:00")):
            raise ValueError("published_at cannot be in the future")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    batch_id = hashlib.sha256((source + ":" + digest).encode()).hexdigest()[:24]
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    if (
        not reader.fieldnames
        or "loan_id" not in reader.fieldnames
        or len(set(reader.fieldnames)) != len(reader.fieldnames)
    ):
        raise ValueError(
            "CSV requires unique headers including loan_id; see the canonical contract"
        )
    raw_rows = list(reader)
    if len(raw_rows) > 10000:
        raise ValueError("Demo ingestion limit: 10,000 rows per request")
    keys = Counter((r.get("loan_id"), r.get("period")) for r in raw_rows)
    validated, rejected = [], []
    for i, raw in enumerate(raw_rows, 2):
        try:
            if keys[(raw.get("loan_id"), raw.get("period"))] > 1:
                raise ValueError(
                    "duplicate loan/month inside file; all copies quarantined"
                )
            record = LoanMonth.model_validate(raw)
            payload = record.model_dump(mode="json")
            serialized = json.dumps(payload, sort_keys=True)
            validated.append(
                (
                    i,
                    payload,
                    serialized,
                    hashlib.sha256(serialized.encode()).hexdigest(),
                )
            )
        except ValueError as exc:
            rejected.append((i, json.dumps(raw), str(exc)[:2000]))
    raw_path = db.data_dir() / "raw" / (digest + ".csv")
    raw_path.parent.mkdir(exist_ok=True)
    try:
        with raw_path.open("x", encoding="utf-8", newline="") as file:
            file.write(content)
    except FileExistsError:
        pass
    changed = unchanged = 0
    revisions = []
    affected_pools = set()
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute(
            "SELECT * FROM batches WHERE id=?", (batch_id,)
        ).fetchone()
        if existing:
            return dict(
                existing, idempotent=True, changed=0, unchanged=existing["accepted"]
            )
        # Establish system-time order only after acquiring the serialized write lock.
        observed = db.now()
        con.execute(
            "INSERT INTO batches VALUES(?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                source,
                digest,
                "1.0",
                observed,
                published_at,
                0,
                0,
                str(raw_path.relative_to(db.data_dir())),
            ),
        )
        for line, payload, serialized, row_hash in validated:
            other = con.execute(
                "SELECT source FROM loan_versions WHERE loan_id=? AND valid_from=? AND source<>? AND known_to IS NULL",
                (payload["loan_id"], payload["period"], source),
            ).fetchone()
            if other:
                rejected.append(
                    (
                        line,
                        serialized,
                        "source collision: use the original source for revisions; namespace distinct loans",
                    )
                )
                continue
            previous = con.execute(
                "SELECT id,row_hash,pool_id FROM loan_versions WHERE source=? AND loan_id=? AND valid_from=? AND known_to IS NULL",
                (source, payload["loan_id"], payload["period"]),
            ).fetchone()
            if previous and previous["row_hash"] == row_hash:
                unchanged += 1
                continue
            if previous:
                con.execute(
                    "UPDATE loan_versions SET known_to=? WHERE id=?",
                    (observed, previous["id"]),
                )
                revisions.append(
                    {
                        "loan_id": payload["loan_id"],
                        "period": payload["period"],
                        "previous_version": previous["id"],
                    }
                )
                affected_pools.add(previous["pool_id"])
            affected_pools.add(payload["pool_id"])
            con.execute(
                "INSERT INTO loan_versions(source,loan_id,pool_id,valid_from,valid_to,known_from,payload,row_hash,batch_id) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    source,
                    payload["loan_id"],
                    payload["pool_id"],
                    payload["period"],
                    next_month(payload["period"]),
                    observed,
                    serialized,
                    row_hash,
                    batch_id,
                ),
            )
            changed += 1
        for line, payload, reason in rejected:
            con.execute(
                "INSERT INTO quarantine(batch_id,row_number,payload,reason) VALUES(?,?,?,?)",
                (batch_id, line, payload, reason),
            )
        con.execute(
            "UPDATE batches SET accepted=?,rejected=? WHERE id=?",
            (changed + unchanged, len(rejected), batch_id),
        )
        db.event(
            con,
            "ingestion.completed.v1",
            {
                "batch_id": batch_id,
                "source": source,
                "changed": changed,
                "unchanged": unchanged,
                "rejected": len(rejected),
                "revisions": revisions,
                "affected_pools": sorted(affected_pools),
            },
        )
    return {
        "id": batch_id,
        "sha256": digest,
        "observed_at": observed,
        "accepted": changed + unchanged,
        "rejected": len(rejected),
        "changed": changed,
        "unchanged": unchanged,
        "idempotent": False,
        "revisions": revisions,
    }


def gaps(rows):
    grouped = {}
    latest_by_pool = {}
    for row in rows:
        grouped.setdefault((row["source"], row["loan_id"]), []).append(row)
        latest_by_pool[row["pool_id"]] = max(
            latest_by_pool.get(row["pool_id"], ""), row["period"]
        )
    result = []
    for (_, loan_id), entries in grouped.items():
        entries.sort(key=lambda r: r["period"])
        for a, b in zip(entries, entries[1:]):
            candidate = next_month(a["period"])
            while candidate < b["period"]:
                result.append(
                    {
                        "loan_id": loan_id,
                        "pool_id": a["pool_id"],
                        "period": candidate,
                        "kind": "missing_month",
                    }
                )
                candidate = next_month(candidate)
            if (
                next_month(a["period"]) == b["period"]
                and abs(float(a["ending_balance"]) - float(b["beginning_balance"]))
                > 0.02
            ):
                result.append(
                    {
                        "loan_id": loan_id,
                        "pool_id": a["pool_id"],
                        "period": b["period"],
                        "kind": "balance_discontinuity",
                    }
                )
        last = entries[-1]
        candidate = next_month(last["period"])
        while (
            float(last["ending_balance"]) > 0
            and candidate <= latest_by_pool[last["pool_id"]]
        ):
            result.append(
                {
                    "loan_id": loan_id,
                    "pool_id": last["pool_id"],
                    "period": candidate,
                    "kind": "missing_latest_observation",
                }
            )
            candidate = next_month(candidate)
    return result
