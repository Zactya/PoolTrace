"""Local API, operational dashboard and versioned integration contracts."""

import hmac
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import db, demo
from .analytics import analyze, characteristics, fit_prepayment, historical
from .ingest import csv_for, gaps, ingest_csv
from .freddie import ingest_performance
from .models import (
    BreakUpdate,
    IngestRequest,
    PerformanceRequest,
    ReferenceRequest,
    Scenario,
    ToleranceUpdate,
)
from .reconcile import add_reference, list_breaks, reconcile, tolerances

WEB = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app):
    db.initialize()
    yield


app = FastAPI(
    title="PoolTrace API",
    version="1.0.0",
    description="Local mortgage analytics and reconciliation. Demo data is synthetic; commercial adapters require authorized input.",
    lifespan=lifespan,
)
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
)


@app.middleware("http")
async def protect(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        key = os.environ.get("POOLTRACE_API_KEY")
        if key and not hmac.compare_digest(
            request.headers.get("Authorization", ""), "Bearer " + key
        ):
            return JSONResponse({"detail": "API key required"}, status_code=401)
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and request.headers.get("X-PoolTrace-Client") != "local-demo"
        ):
            return JSONResponse(
                {"detail": "X-PoolTrace-Client header required"}, status_code=403
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path != "/docs"
        else "default-src 'self' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com"
    )
    return response


@app.exception_handler(ValueError)
async def bad_input(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


def timestamp(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Knowledge time requires a UTC offset")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "time": db.now(),
        "mode": "local-research",
    }


@app.get("/api/v1/overview")
def overview():
    rows = db.records()
    pool_ids = sorted({r["pool_id"] for r in rows})
    pools = []
    for pool in pool_ids:
        subset = [r for r in rows if r["pool_id"] == pool]
        try:
            info = characteristics(subset, allow_incomplete=True)
        except ValueError:
            continue
        pools.append(
            dict(
                info,
                pool_id=pool,
                name=demo.POOL_NAMES.get(pool, pool),
                observations=len(subset),
            )
        )
    with db.connect() as con:
        counts = {
            table: con.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in [
                "batches",
                "quarantine",
                "loan_versions",
                "analytics_runs",
                "performance_versions",
            ]
        }
        events = [
            dict(r, payload=json.loads(r["payload"]))
            for r in con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 8")
        ]
        batches = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM batches ORDER BY observed_at DESC LIMIT 20"
            )
        ]
        identifiers = [
            dict(r) for r in con.execute("SELECT * FROM identifiers ORDER BY id")
        ]
        runs = [
            dict(r, payload=json.loads(r["payload"]))
            for r in con.execute(
                "SELECT * FROM events WHERE kind='reconciliation.completed.v1' ORDER BY id DESC LIMIT 24"
            )
        ]
    return {
        "pools": pools,
        "counts": counts,
        "current_rows": len(rows),
        "gaps": gaps(rows),
        "breaks": list_breaks(),
        "events": events,
        "reconciliation_runs": runs,
        "batches": batches,
        "identifiers": identifiers,
        "tolerances": tolerances(),
        "provenance": sorted({r["provenance"] for r in rows}),
        "time": db.now(),
    }


@app.get("/api/v1/pools/{pool_id}/history")
def history(pool_id: str, knowledge_at: str | None = None):
    knowledge = timestamp(knowledge_at) or db.now()
    return {
        "pool_id": pool_id,
        "knowledge_at": knowledge,
        "series": historical(db.records(pool_id, knowledge)),
    }


@app.get("/api/v1/pools/{pool_id}/versions")
def versions(pool_id: str):
    with db.connect() as con:
        rows = con.execute(
            "SELECT v.* FROM loan_versions v WHERE v.pool_id=? AND EXISTS (SELECT 1 FROM loan_versions old WHERE old.source=v.source AND old.loan_id=v.loan_id AND old.valid_from=v.valid_from AND old.known_to IS NOT NULL) ORDER BY v.id DESC LIMIT 100",
            (pool_id,),
        ).fetchall()
    return [dict(r, payload=json.loads(r["payload"])) for r in rows]


@app.post("/api/v1/pools/{pool_id}/analyze")
def run_analysis(pool_id: str, scenario: Scenario, knowledge_at: str | None = None):
    return analyze(pool_id, scenario, timestamp(knowledge_at))


@app.post("/api/v1/pools/{pool_id}/reconcile")
def run_reconciliation(pool_id: str, scenario: Scenario):
    return reconcile(analyze(pool_id, scenario))


@app.get("/api/v1/pools/{pool_id}/prepayment")
def prepayment(pool_id: str, knowledge_at: str | None = None):
    return fit_prepayment(db.records(pool_id, timestamp(knowledge_at)))


@app.post("/api/v1/ingest")
def ingest(request: IngestRequest):
    return ingest_csv(request.csv_text, request.source, request.published_at)


@app.post("/api/v1/references")
def reference(request: ReferenceRequest):
    return add_reference(request)


@app.post("/api/v1/freddie/performance")
def import_freddie(request: PerformanceRequest):
    return ingest_performance(request.text, request.release, request.source)


@app.get("/api/v1/freddie/performance")
def read_freddie(
    knowledge_at: str | None = None, limit: int = Query(100, ge=1, le=1000)
):
    knowledge = timestamp(knowledge_at) or db.now()
    with db.connect() as con:
        count = con.execute(
            "SELECT COUNT(*) FROM performance_versions WHERE known_from<=? AND (known_to IS NULL OR known_to>?)",
            (knowledge, knowledge),
        ).fetchone()[0]
        rows = con.execute(
            "SELECT * FROM performance_versions WHERE known_from<=? AND (known_to IS NULL OR known_to>?) ORDER BY period,loan_id LIMIT ?",
            (knowledge, knowledge, limit),
        ).fetchall()
    return {
        "count": count,
        "knowledge_at": knowledge,
        "rows": [dict(r, payload=json.loads(r["payload"])) for r in rows],
        "basis": "Credit performance, not MBS disclosure",
    }


@app.get("/api/v1/quarantine")
def quarantine():
    with db.connect() as con:
        return [
            dict(r)
            for r in con.execute("SELECT * FROM quarantine ORDER BY id DESC LIMIT 100")
        ]


@app.patch("/api/v1/breaks/{break_id}")
def update_break(break_id: int, request: BreakUpdate):
    with db.connect() as con:
        previous = con.execute(
            "SELECT * FROM breaks WHERE id=?", (break_id,)
        ).fetchone()
        if not previous:
            raise HTTPException(404, "Break not found")
        if previous["status"] == "superseded":
            raise HTTPException(
                409,
                "This break belongs to a superseded reference; reconcile the latest reference",
            )
        con.execute(
            "UPDATE breaks SET owner=?,status=?,note=?,updated_at=? WHERE id=?",
            (request.owner, request.status, request.note, db.now(), break_id),
        )
        db.event(
            con,
            "break.updated.v1",
            {
                "break_id": break_id,
                "before": {
                    "owner": previous["owner"],
                    "status": previous["status"],
                    "note": previous["note"],
                },
                "after": request.model_dump(),
            },
        )
    return {"id": break_id, **request.model_dump()}


@app.put("/api/v1/tolerances")
def set_tolerances(request: ToleranceUpdate):
    with db.connect() as con:
        previous = tolerances()
        con.execute(
            "UPDATE settings SET value=? WHERE key='tolerances'",
            (json.dumps(request.model_dump()),),
        )
        db.event(
            con,
            "tolerances.updated.v1",
            {"before": previous, "after": request.model_dump()},
        )
    return request.model_dump()


@app.get("/api/v1/events")
def events(after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?", (after, limit)
        ).fetchall()
    result = [dict(r, payload=json.loads(r["payload"])) for r in rows]
    return {
        "events": result,
        "next_cursor": result[-1]["id"] if result else after,
        "delivery": "ordered pull; persist cursor after successful processing",
    }


@app.get("/api/v1/export/{pool_id}")
def export(pool_id: str, knowledge_at: str | None = None):
    rows = db.records(pool_id, timestamp(knowledge_at))
    if not rows:
        raise HTTPException(404, "No records")
    return Response(
        csv_for(rows),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pooltrace-export.csv"},
    )


@app.get("/api/v1/template")
def template():
    return Response(
        csv_for(demo.generate()[:2]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=canonical-example.csv"},
    )


@app.post("/api/v1/demo/{action}")
def demo_action(action: str):
    handlers = {
        "seed": demo.seed,
        "backfill": demo.backfill,
        "restate": demo.restate,
        "remap": demo.remap_identifier,
    }
    if action not in handlers:
        raise HTTPException(404, "Unknown demo action")
    return handlers[action]()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/assets", StaticFiles(directory=WEB), name="assets")
