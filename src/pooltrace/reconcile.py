"""Metric breaks with tolerances, measured counterfactuals and an auditable workflow."""

import json
import hashlib

from . import db
from .analytics import CONVENTIONS, characteristics, deterministic
from .ingest import next_month


def tolerances():
    with db.connect() as con:
        return json.loads(
            con.execute("SELECT value FROM settings WHERE key='tolerances'").fetchone()[
                0
            ]
        )


def add_reference(reference):
    payload = reference.model_dump(mode="json")
    if not db.records(reference.pool_id):
        raise ValueError("Unknown pool")
    with db.connect() as con:
        cursor = con.execute(
            "INSERT INTO reference_metrics(pool_id,source,as_of,payload,created_at) VALUES(?,?,?,?,?)",
            (
                reference.pool_id,
                reference.source,
                str(reference.as_of),
                json.dumps(payload),
                db.now(),
            ),
        )
        superseded = con.execute(
            "UPDATE breaks SET status='superseded',updated_at=? WHERE pool_id=? AND status<>'superseded'",
            (db.now(), reference.pool_id),
        ).rowcount
        db.event(
            con,
            "reference.imported.v1",
            {
                "reference_id": cursor.lastrowid,
                "source": reference.source,
                "superseded_breaks": superseded,
            },
        )
    return {"reference_id": cursor.lastrowid}


def reconcile(analysis):
    pool_id = analysis["pool_id"]
    with db.connect() as con:
        ref = con.execute(
            "SELECT * FROM reference_metrics WHERE pool_id=? ORDER BY id DESC LIMIT 1",
            (pool_id,),
        ).fetchone()
    if not ref:
        return {
            "pool_id": pool_id,
            "compared": 0,
            "breaks": [],
            "message": "Import a reference to compare this pool",
        }
    reference = json.loads(ref["payload"])
    tol = tolerances()
    metrics = dict(analysis["metrics"], oas_bps=analysis["oas"]["oas_bps"])
    counterfactual = deterministic(
        analysis["characteristics"], reference["cpr"], reference["discount_rate"]
    )
    new_breaks = []
    compared = 0
    not_comparable = 0
    with db.connect() as con:
        for metric in ["price", "wal", "duration", "oas_bps"]:
            ours, theirs = metrics.get(metric), reference.get(metric)
            if ours is None or theirs is None:
                continue
            compared += 1
            delta = ours - theirs
            previous = con.execute(
                "SELECT * FROM breaks WHERE reference_id=? AND metric=?",
                (ref["id"], metric),
            ).fetchone()
            incompatible = None
            if reference["as_of"] != next_month(analysis["characteristics"]["period"]):
                incompatible = (
                    "valuation_date_mismatch",
                    "Dates differ; values are not directly comparable. Cause is a candidate.",
                )
            elif reference["conventions"] != CONVENTIONS:
                incompatible = (
                    "convention_mismatch",
                    "Conventions differ; no numerical attribution established.",
                )
            elif (
                metric == "duration"
                and reference.get("duration_type", "fixed_cashflow_parallel_rate")
                != analysis["duration_type"]
            ):
                incompatible = (
                    "duration_definition_mismatch",
                    "Fixed-cashflow and effective durations are not interchangeable.",
                )
            elif metric == "oas_bps":
                incompatible = (
                    "model_basis_review",
                    "Our OAS uses an assumed educational model. Verify reference model and market inputs.",
                )
            evidence = {
                "reference_source": reference["source"],
                "knowledge_at": analysis["knowledge_at"],
                "inputs_hash": analysis["inputs_hash"],
                "run_id": analysis.get("run_id"),
                "reference_id": ref["id"],
            }
            if abs(delta) <= tol[metric] and not incompatible:
                if previous:
                    evidence["basis"] = (
                        "Compared on a compatible basis; current result is within tolerance."
                    )
                    con.execute(
                        "UPDATE breaks SET ours=?,theirs=?,delta=?,tolerance=?,status='resolved',classification='within_tolerance',evidence=?,note='Within tolerance on recalculation',updated_at=? WHERE id=?",
                        (
                            ours,
                            theirs,
                            delta,
                            tol[metric],
                            json.dumps(evidence, sort_keys=True),
                            db.now(),
                            previous["id"],
                        ),
                    )
                    if previous["status"] != "resolved":
                        db.event(
                            con,
                            "break.resolved.v1",
                            {
                                "break_id": previous["id"],
                                "reason": "within tolerance",
                                "evidence": evidence,
                            },
                        )
                continue
            classification = "unexplained_residual"
            if incompatible:
                classification, evidence["basis"] = incompatible
                not_comparable += 1
            elif (
                reference["cpr"] != analysis["scenario"]["cpr"]
                or reference["discount_rate"] != analysis["scenario"]["discount_rate"]
            ):
                residual = counterfactual[metric] - theirs
                classification = (
                    "assumptions_explained"
                    if abs(residual) <= tol[metric]
                    else "assumptions_and_residual"
                )
                evidence.update(
                    {
                        "original_delta": delta,
                        "after_matching_assumptions": residual,
                        "reference_cpr": reference["cpr"],
                        "reference_discount_rate": reference["discount_rate"],
                    }
                )
            elif abs(delta) < tol[metric] * 2:
                evidence["candidate"] = (
                    "Small residual; inspect rounding. Rounding has not been established as the cause."
                )
            # Reopen only when the evidence changes; a reviewed, identical break stays resolved.
            stable = {
                k: v for k, v in evidence.items() if k not in ("knowledge_at", "run_id")
            }
            stable.update(
                {
                    "classification": classification,
                    "delta": delta,
                    "tolerance": tol[metric],
                }
            )
            evidence["fingerprint"] = hashlib.sha256(
                json.dumps(stable, sort_keys=True).encode()
            ).hexdigest()
            evidence_text = json.dumps(evidence, sort_keys=True)
            status = (
                previous["status"]
                if previous
                and json.loads(previous["evidence"]).get("fingerprint")
                == evidence["fingerprint"]
                else "open"
            )
            con.execute(
                "INSERT INTO breaks(reference_id,pool_id,metric,ours,theirs,delta,tolerance,classification,evidence,opened_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(reference_id,metric) DO UPDATE SET ours=excluded.ours,theirs=excluded.theirs,delta=excluded.delta,tolerance=excluded.tolerance,classification=excluded.classification,evidence=excluded.evidence,status=?,updated_at=excluded.updated_at",
                (
                    ref["id"],
                    pool_id,
                    metric,
                    ours,
                    theirs,
                    delta,
                    tol[metric],
                    classification,
                    evidence_text,
                    db.now(),
                    db.now(),
                    status,
                ),
            )
            new_breaks.append(
                {"metric": metric, "delta": delta, "classification": classification}
            )
        db.event(
            con,
            "reconciliation.completed.v1",
            {
                "pool_id": pool_id,
                "reference_id": ref["id"],
                "compared": compared,
                "exceptions": len(new_breaks),
                "not_comparable": not_comparable,
                "run_id": analysis.get("run_id"),
            },
        )
    return {
        "pool_id": pool_id,
        "compared": compared,
        "not_comparable": not_comparable,
        "breaks": new_breaks,
    }


def list_breaks():
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM breaks ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'investigating' THEN 1 ELSE 2 END,id DESC"
        ).fetchall()
    return [dict(r, evidence=json.loads(r["evidence"])) for r in rows]
