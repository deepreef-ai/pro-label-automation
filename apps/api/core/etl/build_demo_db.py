"""CLI: build the demo database.

    PYTHONPATH=apps/api python -m core.etl.build_demo_db [--raw data/raw] [--db sqlite:///data/demo.db] [--synthetic]

``--raw`` may also point at a folder of extract CSVs (``data/extract``). Without client files,
or with ``--synthetic``, a synthetic-only database is built.
"""
from __future__ import annotations

import argparse
import json
import sys

from core.db import database_url
from core.etl.build import build_database


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the demo database (drops and recreates every table)")
    ap.add_argument("--raw", default="data/raw", help="client files (System/, Review/) or extract CSV folder")
    ap.add_argument("--db", default=None, help="database URL (default: DATABASE_URL or sqlite:///data/demo.db)")
    ap.add_argument("--synthetic", action="store_true", help="ignore client files; synthetic data only")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    a = ap.parse_args(argv)
    summary = build_database(database_url(a.db), None if a.synthetic else a.raw)
    if a.json:
        print(json.dumps(summary, indent=2))
        return 0
    print(f"{summary['mode']} build -> {summary['db_url']} in {summary['seconds']} s")
    print(f"{'table':<22}{'rows':>8}{'demo':>8}")
    for name, n in sorted(summary["tables"].items()):
        demo = summary["demo_rows"].get(name, "")
        print(f"{name:<22}{n:>8}{demo:>8}")
    print(f"{'total':<22}{summary['total_rows']:>8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
