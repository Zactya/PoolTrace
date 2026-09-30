"""Run the full scenario in an isolated temporary directory and emit real evidence."""

import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pooltrace.api import app


def run():
    with tempfile.TemporaryDirectory(prefix="pooltrace-evidence-") as folder:
        previous = os.environ.get("POOLTRACE_DATA_DIR")
        os.environ["POOLTRACE_DATA_DIR"] = folder
        try:
            with TestClient(app) as client:
                headers = {"X-PoolTrace-Client": "local-demo"}

                def post(path, body=None):
                    response = client.post(
                        "/api/v1" + path, headers=headers, json=body or {}
                    )
                    response.raise_for_status()
                    return response.json()

                initial = post("/demo/seed")
                reimport = post("/demo/seed")
                before = client.get("/api/v1/overview").json()
                backfill = post("/demo/backfill")
                correction = post("/demo/restate")
                post("/demo/remap")
                comparison = post("/pools/DEMO-ATLAS/reconcile")
                after = client.get("/api/v1/overview").json()
                original = client.get(
                    "/api/v1/pools/DEMO-ATLAS/history",
                    params={"knowledge_at": initial["observed_at"]},
                ).json()
                revised = client.get("/api/v1/pools/DEMO-ATLAS/history").json()
                evidence = {
                    "actual_execution_time": after["time"],
                    "data": "deterministic synthetic fixtures; not issuer or vendor validation",
                    "initial_accepted": initial["accepted"],
                    "initial_quarantined": initial["rejected"],
                    "reimport_changed": reimport["changed"],
                    "initial_coverage_findings": len(before["gaps"]),
                    "backfill_changed": backfill["changed"],
                    "final_coverage_findings": len(after["gaps"]),
                    "correction_versions": len(correction["revisions"]),
                    "historical_prepayment_delta": round(
                        revised["series"][-1]["prepayment"]
                        - original["series"][-1]["prepayment"],
                        2,
                    ),
                    "reconciliation": comparison,
                    "events": client.get("/api/v1/events").json()["next_cursor"],
                    "current_rows": after["current_rows"],
                    "versioned_rows": after["counts"]["loan_versions"],
                }
        finally:
            if previous is None:
                os.environ.pop("POOLTRACE_DATA_DIR", None)
            else:
                os.environ["POOLTRACE_DATA_DIR"] = previous
    target = Path(__file__).resolve().parents[1] / "docs" / "demo-evidence.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    run()
