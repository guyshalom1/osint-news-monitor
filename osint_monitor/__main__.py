"""Command-line interface.

Usage:
    python -m osint_monitor collect
    python -m osint_monitor backfill --keywords Iran Iranian Tehran --days 7
    python -m osint_monitor report --keywords Iran Iranian Tehran --days 7
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .analyzer import analyze, compare_countries
from .collector import collect, connect
from .gdelt import backfill
from .report import make_report
from .sources import SOURCES


def main():
    parser = argparse.ArgumentParser(description="Monitor news coverage of a topic.")
    parser.add_argument("--db", default="articles.db", help="database file")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("collect", help="fetch new articles from all sources")

    bf = sub.add_parser("backfill", help="fill past days for keywords from GDELT")
    bf.add_argument("--keywords", nargs="+", required=True)
    bf.add_argument("--days", type=int, default=7)

    rep = sub.add_parser("report", help="analyze coverage of keywords")
    rep.add_argument("--keywords", nargs="+", required=True)
    rep.add_argument("--days", type=int, default=7)
    rep.add_argument("--out", default="output")

    args = parser.parse_args()
    conn = connect(args.db)

    if args.command == "collect":
        results = collect(conn, SOURCES)
        for source, result in results.items():
            print(f"{source:<22} {result}")
        # Keep a record of which sources worked on this run (source health).
        status = Path(args.db).parent / "source_status.json"
        status.write_text(json.dumps({
            "checked": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "sources": results,
        }, indent=2), encoding="utf-8")
    elif args.command == "backfill":
        outcomes = backfill(conn, args.keywords, args.days)
        for day, outcome in outcomes.items():
            print(f"{day}  {outcome}")
        # Keep a record of what GDELT returned, so a failing day can be diagnosed.
        status = Path(args.db).parent / "backfill_status.json"
        status.write_text(json.dumps({
            "checked": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "keywords": args.keywords,
            "days": outcomes,
        }, indent=2), encoding="utf-8")
    else:
        result = analyze(conn, args.keywords, args.days)
        comparison = compare_countries(conn, args.keywords, args.days)
        path = make_report(result, args.out, comparison)
        print(f"{result['total']} matching articles. Report: {path}")


if __name__ == "__main__":
    main()
