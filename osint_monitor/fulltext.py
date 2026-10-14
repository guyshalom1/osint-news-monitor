"""Fetch the full text of articles that match a topic.

RSS items carry only a headline and a short summary. For the articles that
matter (the ones matching the keywords), this step downloads the page and
extracts the article body with trafilatura, so the analysis can use more
than the headline. It is a separate step from collection: it makes one web
request per article, so it only runs for matching articles and waits
between requests.

Pages that cannot be fetched or are paywalled are marked with an empty
string, so the next run does not try them again.
"""

import time
from datetime import datetime, timezone

import trafilatura

from .analyzer import load_articles, matches

MAX_CHARS = 20000   # keeps the database small; the analysis reads the lead only


def extract_text(url):
    """Download one page and return its article text, or "" if unavailable."""
    html = trafilatura.fetch_url(url)
    if not html:
        return ""
    text = trafilatura.extract(html, include_comments=False, include_tables=False)
    return (text or "")[:MAX_CHARS]


def enrich(conn, keywords, days=7, limit=40, delay=1.0, fetch=extract_text, now=None):
    """Fetch full text for matching articles that do not have it yet.

    Returns {"fetched": with text, "empty": no text found, "remaining": still
    to do after this run}. `limit` caps requests per run, so a scheduled run
    stays short; the rest is picked up by the next run.
    """
    now = now or datetime.now(timezone.utc)
    rows = conn.execute("SELECT link FROM articles WHERE fulltext IS NOT NULL").fetchall()
    done = {row[0] for row in rows}
    todo = [
        a for a in load_articles(conn, days, now)
        if a["link"] and a["link"] not in done and matches(a, keywords)
    ]
    fetched = empty = 0
    for article in todo[:limit]:
        try:
            text = fetch(article["link"])
        except Exception:  # a broken page must not stop the run
            text = ""
        conn.execute("UPDATE articles SET fulltext = ? WHERE link = ?",
                     (text, article["link"]))
        conn.commit()
        if text:
            fetched += 1
        else:
            empty += 1
        time.sleep(delay)
    return {"fetched": fetched, "empty": empty, "remaining": max(0, len(todo) - limit)}
