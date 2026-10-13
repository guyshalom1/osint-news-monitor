"""Backfill history from the GDELT DOC 2.0 API.

RSS feeds only hold recent items, so a fresh database has a thin history.
GDELT indexes news from thousands of outlets and can be queried by day, which
lets the monitor fill the past days for a topic straight away.

Backfilled articles go into the same table as RSS articles (duplicates are
skipped by link). Each fully covered day is recorded per keyword set in the
`backfills` table, so the analyzer can treat those days as complete.
"""

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .collector import clean_text, save

API = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_RECORDS = 250      # the API's maximum per request
PAUSE_SECONDS = 5.5    # GDELT asks for at most one request per 5 seconds


def query_key(keywords):
    """Stable identifier for a keyword set, used to record covered days."""
    return " ".join(sorted(k.lower() for k in keywords))


def build_query(keywords):
    """GDELT query: any keyword, English only. Phrases are quoted."""
    terms = [f'"{k}"' if " " in k else k for k in keywords]
    return f"({' OR '.join(terms)}) sourcelang:english"


def day_params(day, keywords):
    """Request parameters for one UTC day (a date)."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return {
        "query": build_query(keywords),
        "mode": "artlist",
        "format": "json",
        "maxrecords": MAX_RECORDS,
        "sort": "datedesc",
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.strftime("%Y%m%d%H%M%S"),
    }


def parse_seendate(text):
    """GDELT dates look like 20261012T153000Z. Returns an ISO string in UTC."""
    return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(
        tzinfo=timezone.utc).isoformat()


def normalize(item, now):
    """Turn one GDELT article into the same dict the RSS collector produces."""
    url = item.get("url", "")
    title = clean_text(item.get("title", ""))
    if not url or not title:
        return None
    try:
        published = parse_seendate(item["seendate"])
    except (KeyError, ValueError):
        return None
    return {
        "id": hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
        "source": item.get("domain") or "unknown",
        "title": title,
        "summary": "",  # the article list carries titles only
        "link": url,
        "published": published,
        "collected": now.isoformat(),
    }


def fetch_day(params, opener=urllib.request.urlopen, retries=2,
              pause=PAUSE_SECONDS):
    """Download one day of results. Returns a list of raw GDELT items."""
    url = f"{API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "osint-news-monitor"})
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=30) as response:
                body = response.read().decode("utf-8", errors="replace")
            # Rate-limit and "no results" replies are plain text, not JSON.
            if body.lstrip().startswith("{"):
                return json.loads(body).get("articles", [])
            if "limit" in body.lower():
                raise RuntimeError("rate limited")
            return []
        except (urllib.error.URLError, RuntimeError, json.JSONDecodeError):
            if attempt == retries:
                raise
            time.sleep(pause * (attempt + 2))
    return []


def backfill(conn, keywords, days=7, now=None, opener=urllib.request.urlopen,
             pause=PAUSE_SECONDS):
    """Fill the last `days` days (including today) for a keyword set.

    Past days already recorded for these keywords are skipped; today is always
    refreshed because it is still incomplete. Returns {day: new articles} or
    {day: {"error": message}} for a day that failed.
    """
    now = now or datetime.now(timezone.utc)
    key = query_key(keywords)
    today = now.date()
    done = {row[0] for row in conn.execute(
        "SELECT day FROM backfills WHERE query = ?", (key,))}
    results = {}
    first_request = True
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        if day.isoformat() in done:
            continue
        if not first_request:
            time.sleep(pause)
        first_request = False
        try:
            items = fetch_day(day_params(day, keywords), opener, pause=pause)
        except Exception as err:  # one bad day should not stop the others
            results[day.isoformat()] = {"error": str(err)[:200]}
            continue
        articles = [a for a in (normalize(i, now) for i in items) if a]
        results[day.isoformat()] = save(conn, articles)
        # A day is only complete once it is over and the API did not truncate it.
        if day < today and len(items) < MAX_RECORDS:
            conn.execute("INSERT OR IGNORE INTO backfills VALUES (?, ?)",
                         (key, day.isoformat()))
            conn.commit()
    return results
