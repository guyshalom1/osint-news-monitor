"""Tests for fetching, robots.txt, source health and database upkeep.

No test touches the network: HTTP replies are faked.
"""

import io
import sqlite3
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pytest

from osint_monitor import collector, http
from osint_monitor.collector import collect, connect, guess_origin, prune, save

FEED = Path(__file__).parent / "fixtures" / "sample_feed.xml"
NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)


class Reply:
    def __init__(self, body=b"ok", content_type="text/xml"):
        self.body, self.headers = body, {"Content-Type": content_type}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, headers=None):
    return urllib.error.HTTPError("http://x", code, "error", headers or {}, io.BytesIO())


def scripted(*steps):
    """An opener that plays back replies and errors in order, and records requests."""
    calls = []

    def opener(request, timeout=0):
        calls.append(request)
        step = steps[len(calls) - 1]
        if isinstance(step, Exception):
            raise step
        return step
    opener.calls = calls
    return opener


# --- fetch: retries and identification -----------------------------------------

def test_fetch_retries_a_server_error_then_succeeds():
    waits = []
    opener = scripted(http_error(503), TimeoutError("slow"), Reply(b"<rss/>"))
    reply = http.fetch("http://x/feed", opener=opener, sleep=waits.append)
    assert reply.body == b"<rss/>" and reply.content_type == "text/xml"
    assert len(waits) == 2 and waits[1] > waits[0]   # backoff grows


def test_fetch_does_not_retry_a_client_error():
    opener = scripted(http_error(404))
    with pytest.raises(http.FetchError, match="HTTP 404"):
        http.fetch("http://x/feed", opener=opener, sleep=lambda s: None)
    assert len(opener.calls) == 1


def test_fetch_gives_up_after_the_last_retry():
    opener = scripted(*[http_error(500)] * 3)
    with pytest.raises(http.FetchError, match="3 attempts"):
        http.fetch("http://x/feed", retries=2, opener=opener, sleep=lambda s: None)


def test_fetch_waits_as_long_as_the_server_asks():
    waits = []
    opener = scripted(http_error(429, {"Retry-After": "7"}), Reply())
    http.fetch("http://x/feed", opener=opener, sleep=waits.append)
    assert waits == [7.0]


def test_fetch_identifies_itself():
    opener = scripted(Reply())
    http.fetch("http://x/feed", opener=opener)
    agent = opener.calls[0].get_header("User-agent")
    assert agent.startswith("osint-news-monitor/") and "github.com" in agent


# --- robots.txt -------------------------------------------------------------------

def test_robots_disallow_is_respected():
    robots = http.Robots(scripted(Reply(b"User-agent: *\nDisallow: /private/")))
    assert not robots.allowed("http://x/private/feed.xml")
    assert robots.allowed("http://x/public/feed.xml")   # same site: no second request


def test_missing_robots_file_allows_everything():
    assert http.Robots(scripted(http_error(404))).allowed("http://x/feed.xml")


def test_unreachable_robots_file_disallows():
    assert not http.Robots(scripted(http_error(503))).allowed("http://x/feed.xml")
    assert not http.Robots(scripted(urllib.error.URLError("down"))).allowed("http://x/f")


def test_collect_skips_a_feed_that_robots_disallows(monkeypatch):
    monkeypatch.setattr(http, "fetch", lambda url: pytest.fail("must not fetch"))
    robots = http.Robots(scripted(Reply(b"User-agent: *\nDisallow: /")))
    result = collect(connect(":memory:"), {"Blocked": "http://x/feed.xml"}, robots=robots)
    assert "robots.txt" in result["Blocked"]["error"]


def test_collect_fetches_urls_through_the_polite_client(monkeypatch):
    monkeypatch.setattr(http, "fetch",
                        lambda url: http.Response(FEED.read_bytes(), "application/rss+xml"))
    result = collect(connect(":memory:"), {"Sample": "https://x/feed.xml"}, now=NOW)
    assert result["Sample"]["fetched"] == 4


# --- source health ------------------------------------------------------------------

def test_feed_that_turned_over_completely_is_flagged(monkeypatch):
    conn = connect(":memory:")
    first = collect(conn, {"Sample": str(FEED)}, now=NOW)["Sample"]
    assert "saturated" not in first        # a first run is all new by definition

    fresh = [{"id": f"n{i}", "source": "Sample", "title": f"New item {i}", "summary": "",
              "link": f"http://x/{i}", "published": NOW.isoformat(),
              "collected": NOW.isoformat()} for i in range(3)]
    monkeypatch.setattr(collector, "fetch_feed", lambda *args: fresh)
    assert collect(conn, {"Sample": "unused"}, now=NOW)["Sample"]["saturated"] is True


# --- database upkeep ------------------------------------------------------------------

def test_database_from_before_origin_column_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE articles (id TEXT PRIMARY KEY, source TEXT NOT NULL, "
                "title TEXT NOT NULL, summary TEXT, link TEXT, published TEXT, "
                "collected TEXT NOT NULL)")
    old.executemany("INSERT INTO articles VALUES (?, ?, 't', '', '', '2026-10-10', 'x')",
                    [("a", "Jerusalem Post"), ("b", "jpost.com")])
    old.commit()
    old.close()
    rows = dict(connect(path).execute("SELECT source, origin FROM articles"))
    assert rows == {"Jerusalem Post": "rss", "jpost.com": "gdelt"}
    connect(path)   # running the migration twice is harmless


def test_guess_origin():
    assert guess_origin("en.mehrnews.com") == "gdelt"
    assert guess_origin("The Guardian World") == "rss"


def test_prune_removes_only_old_articles():
    conn = connect(":memory:")
    save(conn, [
        {"id": "old", "source": "A", "title": "Old", "summary": "", "link": "o",
         "published": "2019-11-18T00:00:00+00:00", "collected": "x"},
        {"id": "new", "source": "A", "title": "New", "summary": "", "link": "n",
         "published": "2026-10-10T00:00:00+00:00", "collected": "x"},
    ])
    assert prune(conn, keep_days=180, now=NOW) == 1
    assert [r[0] for r in conn.execute("SELECT id FROM articles")] == ["new"]


def test_clean_text_removes_zero_width_characters():
    assert collector.clean_text("The ⁠US struck ​Iran") == "The US struck Iran"
