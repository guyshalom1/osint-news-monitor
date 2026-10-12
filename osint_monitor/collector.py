"""Collect articles from RSS feeds and store them in a local SQLite database.

Flow: fetch feed -> normalize each item into a simple dict -> save to the
database. Articles already in the database are skipped, so the collector
can run every few hours and only new items are added.
"""

import hashlib
import html
import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import feedparser

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id          TEXT PRIMARY KEY,   -- hash of the link, used to skip duplicates
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT,
    link        TEXT,
    published   TEXT,               -- ISO date, UTC
    collected   TEXT NOT NULL
)
"""


def connect(db_path):
    """Open the database and make sure the table exists."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    return conn


def clean_text(text):
    """Remove HTML tags and extra whitespace from feed text."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(entry):
    """Return the item's publication time as an ISO string in UTC, or None."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()


def normalize(entry, source):
    """Turn one raw feed entry into a clean article dict."""
    link = entry.get("link", "")
    title = clean_text(entry.get("title", ""))
    key = link or title  # some feeds omit links; fall back to the title
    return {
        "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
        "source": source,
        "title": title,
        "summary": clean_text(entry.get("summary", "")),
        "link": link,
        "published": parse_date(entry),
        "collected": datetime.now(timezone.utc).isoformat(),
    }


def fetch_feed(source, url_or_path):
    """Download and parse one feed. Accepts a URL or a local file path."""
    feed = feedparser.parse(url_or_path)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Could not read feed for {source}: {feed.bozo_exception}")
    return [normalize(entry, source) for entry in feed.entries if entry.get("title")]


def save(conn, articles):
    """Insert articles, ignoring ones already stored. Returns how many were new."""
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO articles VALUES "
        "(:id, :source, :title, :summary, :link, :published, :collected)",
        articles,
    )
    conn.commit()
    return conn.total_changes - before


def collect(conn, sources):
    """Fetch every source. One failing source does not stop the others.

    Returns a dict per source: {"fetched": items in the feed, "new": items
    not seen before}, or {"error": message} if the source could not be read.
    """
    results = {}
    for name, url in sources.items():
        try:
            articles = fetch_feed(name, url)
            if not articles:
                raise ValueError("feed is empty")
            results[name] = {"fetched": len(articles), "new": save(conn, articles)}
        except Exception as err:  # network errors, blocked access, bad XML
            results[name] = {"error": str(err)[:200]}
    return results
