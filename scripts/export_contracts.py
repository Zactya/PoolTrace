"""Generate reviewable contracts directly from the running code (no server required)."""

import json
from pathlib import Path
from pooltrace.api import app
from pooltrace.models import LoanMonth, ReferenceRequest, Scenario

destination = Path(__file__).resolve().parents[1] / "contracts"
destination.mkdir(exist_ok=True)
for name, document in [
    ("openapi", app.openapi()),
    ("loan-month-v1", LoanMonth.model_json_schema()),
    ("reference-v1", ReferenceRequest.model_json_schema()),
    ("scenario-v1", Scenario.model_json_schema()),
]:
    (destination / (name + ".json")).write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
print("Exported OpenAPI and 3 versioned JSON schemas.")
