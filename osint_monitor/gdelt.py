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
PAUSE_SECONDS = 10     # GDELT asks for one request per 5 seconds; shared CI IPs get 429s, so be slower
MAX_CONSECUTIVE_ERRORS = 2


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


def fetch_day(params, opener=urllib.request.urlopen, retries=3,
              pause=PAUSE_SECONDS):
    """Download one day of results. Returns a list of raw GDELT items."""
    url = f"{API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "osint-news-monitor"})
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=30) as response:
                body = response.read().decode("utf-8", errors="replace")
            if body.lstrip().startswith("{"):
                return json.loads(body).get("articles", [])
            if not body.strip():
                return []  # an empty reply means no matches
            # Anything else is plain text: a rate-limit notice or a query error.
            # Never treat it as "no results", or a day would look covered.
            if "limit" in body.lower():
                raise RuntimeError("rate limited")
            raise ValueError(f"unexpected reply: {body.strip()[:150]}")
        except ValueError:
            raise
        except (urllib.error.URLError, RuntimeError):
            if attempt == retries:
                raise
            time.sleep(pause * 3 * (attempt + 1))
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
    errors_in_a_row = 0
    first_request = True
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        if day.isoformat() in done:
            continue
        if errors_in_a_row >= MAX_CONSECUTIVE_ERRORS:
            results[day.isoformat()] = {"skipped": "stopped after repeated errors"}
            continue
        if not first_request:
            time.sleep(pause)
        first_request = False
        try:
            items = fetch_day(day_params(day, keywords), opener, pause=pause)
        except Exception as err:  # one bad day should not stop the others
            results[day.isoformat()] = {"error": str(err)[:200]}
            errors_in_a_row += 1
            continue
        errors_in_a_row = 0
        articles = [a for a in (normalize(i, now) for i in items) if a]
        results[day.isoformat()] = save(conn, articles)
        # A day is complete once it is over, was not truncated by the API, and
        # returned something (an empty day for a real topic means a bad reply).
        if day < today and 0 < len(items) < MAX_RECORDS:
            conn.execute("INSERT OR IGNORE INTO backfills VALUES (?, ?)",
                         (key, day.isoformat()))
            conn.commit()
    return results
