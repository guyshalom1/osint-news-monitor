"""Collect articles from RSS feeds and store them in a local SQLite database.

Flow: fetch feed -> normalize each item into a simple dict -> save to the
database. Articles already in the database are skipped, so the collector
can run every few hours and only new items are added.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import feedparser

from . import http
from .models import Article, Origin, SourceHealth

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id          TEXT PRIMARY KEY,   -- hash of the link, used to skip duplicates
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT,
    link        TEXT,
    published   TEXT,               -- ISO date, UTC
    collected   TEXT NOT NULL,
    origin      TEXT                -- 'rss' (fixed feed) or 'gdelt' (backfill)
)
"""

BACKFILLS = """
CREATE TABLE IF NOT EXISTS backfills (
    query TEXT NOT NULL,            -- keyword set, see gdelt.query_key
    day   TEXT NOT NULL,            -- UTC date fully covered by a backfill
    PRIMARY KEY (query, day)
)
"""

# GDELT reports a website domain as the source ("jpost.com"); feeds have names.
DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


def guess_origin(source: str) -> Origin:
    """Where an article came from, for rows stored before `origin` existed."""
    return "gdelt" if DOMAIN.match(source.lower()) else "rss"


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the database, create the tables and apply the one schema migration."""
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    conn.execute(BACKFILLS)
    conn.execute("CREATE INDEX IF NOT EXISTS articles_published ON articles (published)")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
    if "origin" not in columns:   # database created before 1.0
        conn.execute("ALTER TABLE articles ADD COLUMN origin TEXT")
    missing = conn.execute("SELECT DISTINCT source FROM articles WHERE origin IS NULL").fetchall()
    for (source,) in missing:
        conn.execute("UPDATE articles SET origin = ? WHERE source = ? AND origin IS NULL",
                     (guess_origin(source), source))
    conn.commit()
    return conn


# Zero-width characters some sites put inside words. They are invisible but
# make "Iran" and "\u200bIran" two different strings.
INVISIBLE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")


def clean_text(text: str | None) -> str:
    """Remove HTML tags and extra whitespace from feed text."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = INVISIBLE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(entry: Mapping[str, Any]) -> str | None:
    """Return the item's publication time as an ISO string in UTC, or None."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    year, month, day, hour, minute, second = parsed[:6]
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).isoformat()


def normalize(entry: Mapping[str, Any], source: str, now: datetime | None = None) -> Article:
    """Turn one raw feed entry into a clean article dict."""
    now = now or datetime.now(timezone.utc)
    link = entry.get("link", "")
    title = clean_text(entry.get("title", ""))
    key = link or title  # some feeds omit links; fall back to the title
    return {
        "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
        "source": source,
        "title": title,
        "summary": clean_text(entry.get("summary", "")),
        "link": link,
        "published": parse_date(entry),   # type: ignore[typeddict-item]  # None: undated item
        "collected": now.isoformat(),
        "origin": "rss",
    }


def fetch_feed(source: str, url_or_path: str, now: datetime | None = None,
               robots: http.Robots | None = None) -> list[Article]:
    """Download and parse one feed. Accepts a URL or a local file path."""
    if url_or_path.startswith(("http://", "https://")):
        if robots is not None and not robots.allowed(url_or_path):
            raise PermissionError("disallowed by robots.txt")
        reply = http.fetch(url_or_path)
        feed = feedparser.parse(
            reply.body, response_headers={"content-type": reply.content_type})
    else:
        feed = feedparser.parse(url_or_path)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Could not read feed for {source}: {feed.bozo_exception}")
    return [normalize(entry, source, now) for entry in feed.entries if entry.get("title")]


def save(conn: sqlite3.Connection, articles: Iterable[Article]) -> int:
    """Insert articles, ignoring ones already stored. Returns how many were new."""
    rows = [{**a, "origin": a.get("origin") or guess_origin(a["source"])} for a in articles]
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO articles "
        "(id, source, title, summary, link, published, collected, origin) VALUES "
        "(:id, :source, :title, :summary, :link, :published, :collected, :origin)",
        rows,
    )
    conn.commit()
    return conn.total_changes - before


def collect(conn: sqlite3.Connection, sources: Mapping[str, str],
            now: datetime | None = None,
            robots: http.Robots | None = None) -> dict[str, SourceHealth]:
    """Fetch every source. One failing source does not stop the others.

    Returns the health of each source: items in the feed, how many were new,
    the newest item's date, and flags for a feed that stopped updating
    ("stale") or probably lost items between runs ("saturated"). A source
    that could not be read gets {"error": message}.
    """
    now = now or datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat()
    results: dict[str, SourceHealth] = {}
    for name, url in sources.items():
        try:
            articles = fetch_feed(name, url, now, robots)
            if not articles:
                raise ValueError("feed is empty")
            seen_before = conn.execute(
                "SELECT 1 FROM articles WHERE source = ? LIMIT 1", (name,)).fetchone()
            health: SourceHealth = {"fetched": len(articles), "new": save(conn, articles)}
            # A feed can respond normally but have stopped updating.
            dates = [a["published"] for a in articles if a["published"]]
            newest = max(dates) if dates else None
            health["newest"] = newest[:10] if newest else None
            if not newest or newest < week_ago:
                health["stale"] = True
            # Every item new on a source we already follow: the feed turned
            # over completely since the last run, so items in between were lost.
            if seen_before and health["new"] == health["fetched"]:
                health["saturated"] = True
            results[name] = health
            log.info("%-22s fetched %3d, new %3d", name, health["fetched"], health["new"])
        except Exception as err:  # network errors, blocked access, bad XML
            results[name] = {"error": str(err)[:200]}
            log.warning("%-22s failed: %s", name, results[name]["error"])
    return results


def prune(conn: sqlite3.Connection, keep_days: int, now: datetime | None = None) -> int:
    """Delete articles published more than `keep_days` ago. Returns how many.

    The database is committed to git, where files over 100 MB are rejected,
    so it cannot grow forever. Old feed items (some feeds carry years-old
    entries) and articles past the retention window are removed.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=keep_days)).isoformat()
    removed = conn.execute(
        "DELETE FROM articles WHERE published < ?", (cutoff,)).rowcount
    conn.execute("DELETE FROM backfills WHERE day < ?", (cutoff[:10],))
    conn.commit()
    if removed:
        conn.execute("VACUUM")
    return removed
