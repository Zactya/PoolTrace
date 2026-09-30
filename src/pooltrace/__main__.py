import argparse
import os
from pathlib import Path

from . import db, demo
from .ingest import ingest_csv


def main():
    parser = argparse.ArgumentParser(description="PoolTrace local workbench")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    sub.add_parser("demo")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("path")
    ingest.add_argument("--source", required=True)
    freddie = sub.add_parser("freddie")
    freddie.add_argument("path")
    freddie.add_argument("--source", default="freddie-sfll")
    freddie.add_argument("--release", choices=["r47", "pre-r47"], default="r47")
    args = parser.parse_args()
    db.initialize()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("pooltrace.api:app", host="127.0.0.1", port=args.port)
    elif args.command == "demo":
        print(demo.seed())
    elif args.command == "ingest":
        print(ingest_csv(Path(args.path).read_text(encoding="utf-8-sig"), args.source))
    elif args.command == "freddie":
        from .freddie import ingest_performance

        print(
            ingest_performance(
                Path(args.path).read_text(encoding="utf-8-sig"),
                args.release,
                args.source,
            )
        )


if __name__ == "__main__":
    main()
