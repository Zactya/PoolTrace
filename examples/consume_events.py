"""Minimal external consumer with durable, transactional deduplication.

Run after starting PoolTrace: python examples/consume_events.py
The consumer database stays under ignored data/. It is separate from the app database.
"""

import argparse
import json
import os
import sqlite3
import urllib.request
from pathlib import Path


def consume(base_url="http://127.0.0.1:8765", database="data/consumer.db"):
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS processed_events(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        cursor = con.execute(
            "SELECT COALESCE(MAX(id),0) FROM processed_events"
        ).fetchone()[0]
        request = urllib.request.Request(
            base_url + f"/api/v1/events?after={cursor}&limit=500"
        )
        if os.environ.get("POOLTRACE_API_KEY"):
            request.add_header(
                "Authorization", "Bearer " + os.environ["POOLTRACE_API_KEY"]
            )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        count = 0
        for event in result["events"]:
            inserted = con.execute(
                "INSERT OR IGNORE INTO processed_events VALUES(?,?,?)",
                (event["id"], event["kind"], json.dumps(event["payload"])),
            )
            count += inserted.rowcount
        # Processing here is writing the received event. A real consumer must atomically
        # coordinate business side effects with its checkpoint or make them idempotent.
    return {
        "new_events": count,
        "next_cursor": result["next_cursor"],
        "consumer_database": str(path),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    print(json.dumps(consume(args.url), indent=2))
