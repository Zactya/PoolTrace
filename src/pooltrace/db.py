"""SQLite ledger. Valid time is a monthly interval; system time is receipt time."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batches(
 id TEXT PRIMARY KEY, source TEXT NOT NULL, sha256 TEXT NOT NULL, schema_version TEXT NOT NULL,
 observed_at TEXT NOT NULL, published_at TEXT, accepted INTEGER NOT NULL, rejected INTEGER NOT NULL,
 raw_path TEXT NOT NULL, UNIQUE(source,sha256));
CREATE TABLE IF NOT EXISTS loan_versions(
 id INTEGER PRIMARY KEY, source TEXT NOT NULL, loan_id TEXT NOT NULL, pool_id TEXT NOT NULL,
 valid_from TEXT NOT NULL, valid_to TEXT NOT NULL, known_from TEXT NOT NULL, known_to TEXT,
 payload TEXT NOT NULL, row_hash TEXT NOT NULL, batch_id TEXT NOT NULL REFERENCES batches(id));
CREATE UNIQUE INDEX IF NOT EXISTS idx_loans_current ON loan_versions(source,loan_id,valid_from) WHERE known_to IS NULL;
CREATE INDEX IF NOT EXISTS idx_loans_pool_time ON loan_versions(pool_id,valid_from,known_from,known_to);
CREATE TABLE IF NOT EXISTS quarantine(id INTEGER PRIMARY KEY,batch_id TEXT NOT NULL REFERENCES batches(id),row_number INTEGER NOT NULL,payload TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reference_metrics(id INTEGER PRIMARY KEY,pool_id TEXT NOT NULL,source TEXT NOT NULL,as_of TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS breaks(
 id INTEGER PRIMARY KEY,reference_id INTEGER NOT NULL REFERENCES reference_metrics(id),pool_id TEXT NOT NULL,
 metric TEXT NOT NULL,ours REAL NOT NULL,theirs REAL NOT NULL,delta REAL NOT NULL,tolerance REAL NOT NULL,
 classification TEXT NOT NULL,evidence TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',owner TEXT NOT NULL DEFAULT 'Unassigned',
 opened_at TEXT NOT NULL,updated_at TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',UNIQUE(reference_id,metric));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS identifiers(id INTEGER PRIMARY KEY,pool_id TEXT NOT NULL,identifier TEXT NOT NULL,
 valid_from TEXT NOT NULL,valid_to TEXT,known_from TEXT NOT NULL,known_to TEXT);
CREATE TABLE IF NOT EXISTS analytics_runs(id INTEGER PRIMARY KEY,pool_id TEXT NOT NULL,created_at TEXT NOT NULL,
 knowledge_at TEXT NOT NULL,inputs_hash TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS performance_versions(id INTEGER PRIMARY KEY,source TEXT NOT NULL,loan_id TEXT NOT NULL,
 period TEXT NOT NULL,known_from TEXT NOT NULL,known_to TEXT,payload TEXT NOT NULL,row_hash TEXT NOT NULL,
 batch_id TEXT NOT NULL REFERENCES batches(id));
CREATE UNIQUE INDEX IF NOT EXISTS idx_performance_current ON performance_versions(source,loan_id,period) WHERE known_to IS NULL;
"""


def now():
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def data_dir():
    path = Path(os.environ.get("POOLTRACE_DATA_DIR", "data")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect():
    con = sqlite3.connect(data_dir() / "pooltrace.db", timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    try:
        with con:
            yield con
    finally:
        con.close()


def initialize():
    with connect() as con:
        con.executescript(SCHEMA)
        con.execute("INSERT OR IGNORE INTO schema_versions VALUES(1,?)", (now(),))
        con.execute(
            "INSERT OR IGNORE INTO settings VALUES('tolerances',?)",
            (json.dumps({"price": 0.03, "wal": 0.03, "duration": 0.03, "oas_bps": 3}),),
        )


def event(con, kind, payload):
    con.execute(
        "INSERT INTO events(kind,created_at,payload) VALUES(?,?,?)",
        (kind, now(), json.dumps(payload, sort_keys=True)),
    )


def records(pool_id=None, knowledge_at=None, period=None):
    conditions, params = [], []
    if knowledge_at:
        parsed = datetime.fromisoformat(knowledge_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Knowledge time requires a UTC offset")
        knowledge_at = (
            parsed.astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        conditions += ["known_from <= ?", "(known_to IS NULL OR known_to > ?)"]
        params += [knowledge_at, knowledge_at]
    else:
        conditions += ["known_to IS NULL"]
    if pool_id:
        conditions += ["pool_id=?"]
        params += [pool_id]
    if period:
        conditions += ["valid_from=?"]
        params += [period]
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM loan_versions WHERE "
            + " AND ".join(conditions)
            + " ORDER BY valid_from,loan_id",
            params,
        ).fetchall()
    return [
        dict(
            json.loads(r["payload"]),
            version_id=r["id"],
            batch_id=r["batch_id"],
            known_from=r["known_from"],
            known_to=r["known_to"],
            source=r["source"],
        )
        for r in rows
    ]
