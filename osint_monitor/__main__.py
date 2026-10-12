"""Command-line interface.

Usage:
    python -m osint_monitor collect
    python -m osint_monitor report --keywords Hezbollah Lebanon --days 7
"""

import argparse

from .analyzer import analyze
from .collector import collect, connect
from .report import make_report
from .sources import SOURCES


def main():
    parser = argparse.ArgumentParser(description="Monitor news coverage of a topic.")
    parser.add_argument("--db", default="articles.db", help="database file")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("collect", help="fetch new articles from all sources")

    rep = sub.add_parser("report", help="analyze coverage of keywords")
    rep.add_argument("--keywords", nargs="+", required=True)
    rep.add_argument("--days", type=int, default=7)
    rep.add_argument("--out", default="output")

    args = parser.parse_args()
    conn = connect(args.db)

    if args.command == "collect":
        for source, result in collect(conn, SOURCES).items():
            print(f"{source:<22} {result}")
    else:
        result = analyze(conn, args.keywords, args.days)
        path = make_report(result, args.out)
        print(f"{result['total']} matching articles. Report: {path}")


if __name__ == "__main__":
    main()
