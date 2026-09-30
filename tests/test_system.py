import json
import math
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from pooltrace import db, demo
from pooltrace.analytics import (
    analyze,
    characteristics,
    cpr,
    deterministic,
    fit_prepayment,
    historical,
    project,
    smm,
)
from pooltrace.api import app
from pooltrace.freddie import ingest_performance, parse_row
from pooltrace.ingest import csv_for, gaps, ingest_csv
from pooltrace.models import LoanMonth, ReferenceRequest, Scenario
from pooltrace.reconcile import add_reference, list_breaks, reconcile


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv("POOLTRACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("POOLTRACE_API_KEY", raising=False)
    db.initialize()


def test_seed_is_idempotent_and_quarantines_bad_balance():
    first = demo.seed()
    second = demo.seed()
    assert first["accepted"] == 1727 and first["rejected"] == 1
    assert second["idempotent"] and second["changed"] == 0
    assert len(db.records()) == 1727
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0] == 1


def test_restatement_preserves_previous_knowledge_and_receipt_time():
    initial = demo.seed()
    before = db.records("DEMO-ATLAS", initial["observed_at"])
    correction = demo.restate()
    old = db.records("DEMO-ATLAS", initial["observed_at"])
    new = db.records("DEMO-ATLAS", correction["observed_at"])
    key = lambda r: r["loan_id"] == "DEMO-ATLAS-000" and r["period"] == "2024-12-01"
    assert (
        next(r for r in old if key(r))["prepayment"]
        == next(r for r in before if key(r))["prepayment"]
    )
    assert (
        Decimal(next(r for r in new if key(r))["prepayment"])
        - Decimal(next(r for r in old if key(r))["prepayment"])
        == 1750
    )
    assert len(old) == len(new)
    assert demo.restate()["idempotent"]
    assert len(
        db.records("DEMO-ATLAS", correction["observed_at"].replace("Z", "+00:00"))
    ) == len(new)


def test_backfill_recovers_actual_fixture_without_estimating():
    demo.seed()
    assert len(gaps(db.records())) == 1
    assert demo.backfill()["changed"] == 1
    assert gaps(db.records()) == []
    assert demo.backfill()["idempotent"]


def test_balance_identity_and_nonvoluntary_exit():
    row = demo.generate()[0]
    with pytest.raises(ValueError):
        LoanMonth.model_validate(dict(row, ending_balance="0"))
    with pytest.raises(ValueError):
        LoanMonth.model_validate(dict(row, event="liquidated"))
    with pytest.raises(ValueError):
        LoanMonth.model_validate(dict(row, gross_rate=float("nan")))


def test_duplicate_rows_and_cross_source_collision_cannot_double_count():
    row = demo.generate()[0]
    assert ingest_csv(csv_for([row, row]), "duplicate")["rejected"] == 2
    assert not db.records()
    ingest_csv(csv_for([row]), "source-a")
    assert ingest_csv(csv_for([row]), "source-b")["rejected"] == 1
    assert len(db.records()) == 1


def test_incomplete_latest_month_blocks_valuation():
    rows = demo.generate()[:2] + demo.generate()[24:26]
    rows = [
        r
        for r in rows
        if not (r["loan_id"] == "DEMO-ATLAS-001" and r["period"] == "2023-02-01")
    ]
    ingest_csv(csv_for(rows), "partial")
    with pytest.raises(ValueError, match="Incomplete pool snapshot"):
        characteristics(db.records())
    assert any(g["kind"] == "missing_latest_observation" for g in gaps(db.records()))


@pytest.mark.parametrize("speed", [0, 0.06, 0.5, 0.8])
def test_projected_principal_conservation_and_nonnegative_cashflows(speed):
    info = {
        "balance": 123456.78,
        "gross_rate": 0.065,
        "net_rate": 0.06,
        "remaining_months": 300,
    }
    flows = project(info, speed)
    assert sum(f["principal"] for f in flows) == pytest.approx(
        info["balance"], abs=0.00001
    )
    assert all(min(f["principal"], f["interest"], f["prepayment"]) >= 0 for f in flows)


def test_independent_zero_coupon_golden_case_and_cpr_roundtrip():
    info = {"balance": 1200, "gross_rate": 0, "net_rate": 0, "remaining_months": 12}
    result = deterministic(info, 0, 0)
    assert result["price"] == pytest.approx(100)
    assert result["wal"] == pytest.approx(6.5 / 12)
    assert result["duration"] == pytest.approx(6.5 / 12, rel=1e-7)
    for speed in [0, 0.03, 0.4, 1]:
        assert cpr(smm(speed)) == pytest.approx(speed)


def test_higher_prepayment_reduces_wal():
    info = {
        "balance": 100000,
        "gross_rate": 0.06,
        "net_rate": 0.055,
        "remaining_months": 300,
    }
    assert (
        deterministic(info, 0.2, 0.04)["wal"] < deterministic(info, 0.05, 0.04)["wal"]
    )


def test_seeded_oas_and_financial_lineage():
    demo.seed()
    scenario = Scenario(paths=32)
    a = analyze("DEMO-ATLAS", scenario)
    b = analyze("DEMO-ATLAS", scenario)
    assert a["oas"] == b["oas"]
    assert math.isfinite(a["oas"]["oas_bps"])
    assert a["inputs_hash"] == b["inputs_hash"]
    demo.restate()
    c = analyze("DEMO-ATLAS", scenario)
    assert a["inputs_hash"] != c["inputs_hash"]
    with pytest.raises(ValueError):
        Scenario(paths=33)


def test_reconciliation_measures_assumptions_and_retains_unexplained_residual():
    demo.seed()
    for pool in ["DEMO-ATLAS", "DEMO-HARBOR"]:
        reconcile(analyze(pool, Scenario(paths=32)))
    breaks = list_breaks()
    assert any(
        b["classification"] == "assumptions_explained"
        and abs(b["evidence"]["after_matching_assumptions"]) < b["tolerance"]
        for b in breaks
    )
    assert any(
        b["pool_id"] == "DEMO-HARBOR" and b["classification"] == "unexplained_residual"
        for b in breaks
    )
    count = len(breaks)
    for pool in ["DEMO-ATLAS", "DEMO-HARBOR"]:
        reconcile(analyze(pool, Scenario(paths=32)))
    assert len(list_breaks()) == count


def test_model_temporal_holdout_does_not_fit_later_targets():
    demo.seed()
    rows = db.records("DEMO-ATLAS")
    a = fit_prepayment(rows)
    changed = [
        dict(r, prepayment="0") if r["period"] >= a["split_period"] else r for r in rows
    ]
    b = fit_prepayment(changed)
    assert a["coefficients"] == b["coefficients"]
    assert all(s["observed_cpr"] == 0 for s in b["series"] if s["split"] == "test")
    assert a["test_rows"] > 0 and a["training_rows"] > a["test_rows"]


def test_identifier_restatement_preserves_old_knowledge():
    demo.seed()
    result = demo.remap_identifier()
    with db.connect() as con:
        records = [
            dict(r)
            for r in con.execute("SELECT * FROM identifiers WHERE pool_id='DEMO-ATLAS'")
        ]
    assert len(records) == 3
    assert any(r["known_to"] == result["known_from"] for r in records)
    assert demo.remap_identifier()["idempotent"]


def test_concurrent_revisions_have_non_inverted_intervals():
    row = demo.generate()[0]
    ingest_csv(csv_for([row]), "concurrent")
    a = dict(
        row,
        prepayment=f"{float(row['prepayment']) + 1:.2f}",
        ending_balance=f"{float(row['ending_balance']) - 1:.2f}",
    )
    b = dict(
        row,
        prepayment=f"{float(row['prepayment']) + 2:.2f}",
        ending_balance=f"{float(row['ending_balance']) - 2:.2f}",
    )
    with ThreadPoolExecutor(2) as executor:
        list(executor.map(lambda r: ingest_csv(csv_for([r]), "concurrent"), [a, b]))
    with db.connect() as con:
        rows = con.execute("SELECT known_from,known_to FROM loan_versions").fetchall()
    assert len(rows) == 3 and all(
        r["known_to"] is None or r["known_from"] <= r["known_to"] for r in rows
    )


def test_freddie_contract_preserves_measurements_without_inventing_pool():
    f = [""] * 35
    f[0] = "SYNTHETIC-FREDDIE-01"
    f[1] = "202501"
    f[2] = "123000"
    f[4] = "24"
    f[5] = "336"
    f[8] = "01"
    f[9] = "202501"
    f[10] = "6.25"
    f[11] = "0"
    f[12] = "202412"
    f[26] = "123000"
    f[31] = "123000"
    row = parse_row(f, "r47")
    assert row["current_rate_pct"] == 6.25
    assert (
        row["pool_mapping"] is None
        and row["exit_label"] == "voluntary_payoff_or_maturity"
    )
    tape = "|".join(f) + "\n"
    first = ingest_performance(tape)
    assert first["accepted"] == 1 and ingest_performance(tape)["idempotent"]
    assert not db.records()
    with pytest.raises(ValueError):
        parse_row(f, "pre-r47")


def test_api_workflow_security_and_consumer_cursor():
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.post("/api/v1/demo/seed", json={}).status_code == 403
        headers = {"X-PoolTrace-Client": "local-demo"}
        assert (
            client.post("/api/v1/demo/seed", json={}, headers=headers).status_code
            == 200
        )
        result = client.post(
            "/api/v1/pools/DEMO-ATLAS/reconcile", json={"paths": 32}, headers=headers
        )
        assert result.status_code == 200
        overview = client.get("/api/v1/overview").json()
        first_break = overview["breaks"][0]
        update = client.patch(
            "/api/v1/breaks/" + str(first_break["id"]),
            json={
                "owner": "Demo analyst",
                "status": "resolved",
                "note": "Compared matched assumptions and reviewed residual.",
            },
            headers=headers,
        )
        assert update.status_code == 200
        events = client.get("/api/v1/events?limit=2").json()
        next_page = client.get(
            "/api/v1/events?after=" + str(events["next_cursor"])
        ).json()
        assert all(e["id"] > events["next_cursor"] for e in next_page["events"])
        assert (
            client.post(
                "/api/v1/pools/DEMO-ATLAS/analyze", json={"cpr": 1.5}, headers=headers
            ).status_code
            == 422
        )
        assert client.get("/api/v1/export/DEMO-ATLAS").status_code == 200
        assert client.get("/openapi.json").json()["info"]["title"] == "PoolTrace API"


def test_optional_key_enforced(monkeypatch):
    monkeypatch.setenv("POOLTRACE_API_KEY", "test-only-key")
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 401
        assert (
            client.get(
                "/api/v1/health", headers={"Authorization": "Bearer test-only-key"}
            ).status_code
            == 200
        )


def test_matching_numbers_with_wrong_date_are_not_reconciled():
    demo.seed()
    analysis = analyze("DEMO-ATLAS", Scenario(paths=32))
    add_reference(
        ReferenceRequest(
            pool_id="DEMO-ATLAS",
            source="Synthetic wrong date",
            as_of="2024-01-01",
            price=analysis["metrics"]["price"],
            wal=analysis["metrics"]["wal"],
            duration=analysis["metrics"]["duration"],
            cpr=0.08,
            discount_rate=0.045,
        )
    )
    result = reconcile(analysis)
    assert result["not_comparable"] == 3
    assert all(
        b["classification"] == "valuation_date_mismatch" for b in result["breaks"]
    )


def test_manual_resolution_reopens_on_changed_evidence_not_new_run():
    demo.seed()
    reconcile(analyze("DEMO-ATLAS", Scenario(paths=32)))
    with db.connect() as con:
        con.execute("UPDATE breaks SET status='resolved'")
    reconcile(analyze("DEMO-ATLAS", Scenario(paths=32)))
    assert all(b["status"] == "resolved" for b in list_breaks())
    demo.backfill()  # Historical input changes; latest balances/metrics do not.
    reconcile(analyze("DEMO-ATLAS", Scenario(paths=32)))
    assert all(b["status"] == "open" for b in list_breaks())


def test_automatic_resolution_records_current_evidence():
    demo.seed()
    reconcile(analyze("DEMO-ATLAS", Scenario(paths=32)))
    closing = analyze("DEMO-ATLAS", Scenario(cpr=0.12, paths=32))
    reconcile(closing)
    assert all(
        b["status"] == "resolved" and b["evidence"]["run_id"] == closing["run_id"]
        for b in list_breaks()
    )


def test_new_reference_supersedes_older_exceptions_without_deleting_evidence():
    demo.seed()
    analysis = analyze("DEMO-ATLAS", Scenario(paths=32))
    reconcile(analysis)
    old_ids = {b["id"] for b in list_breaks()}
    add_reference(
        ReferenceRequest(
            pool_id="DEMO-ATLAS",
            source="Updated synthetic reference",
            as_of="2025-01-01",
            price=analysis["metrics"]["price"],
            wal=analysis["metrics"]["wal"],
            duration=analysis["metrics"]["duration"],
            cpr=0.08,
            discount_rate=0.045,
        )
    )
    reconcile(analysis)
    assert {b["id"] for b in list_breaks()} == old_ids
    assert all(b["status"] == "superseded" for b in list_breaks())
