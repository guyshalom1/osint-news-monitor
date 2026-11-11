"""Command-line interface.

Usage:
    osint-monitor collect
    osint-monitor backfill --keywords Iran Iranian Tehran --days 7
    osint-monitor report --keywords Iran Iranian Tehran --days 7
    osint-monitor prune --keep-days 180
    osint-monitor check
    osint-monitor evaluate

`python -m osint_monitor` works the same way.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__, entities, evaluate
from .analyzer import analyze, compare_countries
from .assessment import build_assessment
from .brief import make_brief
from .collector import collect, connect, prune
from .gdelt import backfill
from .http import Robots
from .report import make_report, update_readme
from .sources import SOURCES

log = logging.getLogger("osint_monitor")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="osint-monitor", description="Monitor news coverage of a topic.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--db", default="articles.db", help="database file")
    parser.add_argument("-v", "--verbose", action="store_true", help="log debug detail")
    parser.add_argument("-q", "--quiet", action="store_true", help="log warnings only")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("collect", help="fetch new articles from all sources")

    bf = sub.add_parser("backfill", help="fill past days for keywords from GDELT")
    bf.add_argument("--keywords", nargs="+", required=True)
    bf.add_argument("--days", type=int, default=7)

    rep = sub.add_parser("report", help="analyze coverage of keywords")
    rep.add_argument("--keywords", nargs="+", required=True)
    rep.add_argument("--days", type=int, default=7)
    rep.add_argument("--out", default="output", help="folder for the report, brief and charts")
    rep.add_argument("--ner", choices=["auto", "spacy", "regex"], default="auto",
                     help="name extraction: spaCy model, regex fallback, or auto-detect")
    rep.add_argument("--pdf", action="store_true", help="also write brief.pdf (needs WeasyPrint)")
    rep.add_argument("--readme", help="README file whose assessment block to refresh")

    pr = sub.add_parser("prune", help="delete articles older than the retention window")
    pr.add_argument("--keep-days", type=int, default=180)

    sub.add_parser("check", help="verify the database is intact and not empty")

    ev = sub.add_parser("evaluate", help="score name extraction and the tone word lists "
                                         "against hand-labeled articles")
    ev.add_argument("--sample", default="tests/fixtures/labeled_sample.json")
    return parser


def write_status(path: Path, payload: dict[str, Any]) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="minutes")
    path.write_text(json.dumps({"checked": stamp, **payload}, indent=2), encoding="utf-8")


def read_status(path: Path) -> dict[str, Any] | None:
    try:
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    except (OSError, ValueError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("fontTools", "weasyprint", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if args.command == "evaluate":
        print(evaluate.report(evaluate.load_sample(args.sample)))
        return 0
    conn = connect(args.db)
    data_dir = Path(args.db).parent

    if args.command == "collect":
        results = collect(conn, SOURCES, robots=Robots())
        failed = [name for name, r in results.items() if "error" in r]
        log.info("%d of %d sources collected, %d new articles",
                 len(results) - len(failed), len(results),
                 sum(r.get("new", 0) for r in results.values()))
        # Keep a record of which sources worked on this run (source health).
        write_status(data_dir / "source_status.json", {"sources": results})
        if len(failed) == len(results):
            log.error("every source failed; check the network")
            return 1
    elif args.command == "backfill":
        outcomes = backfill(conn, args.keywords, args.days)
        # Keep a record of what GDELT returned, so a failing day can be diagnosed.
        write_status(data_dir / "backfill_status.json",
                     {"keywords": args.keywords, "days": outcomes})
    elif args.command == "check":
        state = conn.execute("PRAGMA integrity_check").fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        log.info("integrity: %s, %d articles", state, count)
        if state != "ok" or count == 0:
            log.error("database failed the check; refusing to publish it")
            return 1
    elif args.command == "prune":
        log.info("removed %d articles older than %d days",
                 prune(conn, args.keep_days), args.keep_days)
    else:
        log.info("name extraction: %s", entities.use_backend(args.ner))
        now = datetime.now(timezone.utc)  # one clock for every part of the report
        result = analyze(conn, args.keywords, args.days, now=now)
        comparison = compare_countries(conn, args.keywords, args.days, now=now)
        assessment = build_assessment(result, comparison, now)
        path = make_report(result, args.out, comparison, assessment, now=now)
        log.info("%d matching articles. Report: %s", result["total"], path)
        if result["total"]:
            brief = make_brief(result, comparison, assessment, args.out, now,
                               health=read_status(data_dir / "source_status.json"),
                               backfill=read_status(data_dir / "backfill_status.json"),
                               pdf=args.pdf)
            log.info("Brief: %s", brief)
        if args.readme and result["total"]:
            stamp = now.strftime("%Y-%m-%d %H:%M UTC")
            if not update_readme(args.readme, assessment, stamp, result):
                log.warning("No assessment markers in %s; left unchanged.", args.readme)
    return 0
