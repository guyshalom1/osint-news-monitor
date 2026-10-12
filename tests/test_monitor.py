"""Tests run on a local sample feed, so they need no internet connection."""

from datetime import datetime, timezone
from pathlib import Path

from osint_monitor.analyzer import analyze, find_spikes, top_entities
from osint_monitor.collector import clean_text, collect, connect
from osint_monitor.report import make_report

FEED = str(Path(__file__).parent / "fixtures" / "sample_feed.xml")
NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)


def make_db():
    conn = connect(":memory:")
    collect(conn, {"Sample": FEED})
    return conn


def test_clean_text_strips_html():
    assert clean_text("<p>Hello &amp; welcome</p>") == "Hello & welcome"


def test_collect_skips_duplicates():
    conn = connect(":memory:")
    first = collect(conn, {"Sample": FEED})
    second = collect(conn, {"Sample": FEED})
    assert (first["Sample"]["fetched"], first["Sample"]["new"]) == (4, 4)
    assert (second["Sample"]["fetched"], second["Sample"]["new"]) == (4, 0)


def test_newest_item_date_recorded():
    conn = connect(":memory:")
    result = collect(conn, {"Sample": FEED})["Sample"]
    assert result["newest"] == "2026-10-10"


def test_bad_source_does_not_stop_others():
    conn = connect(":memory:")
    results = collect(conn, {"Broken": "/no/such/file.xml", "Sample": FEED})
    assert "error" in results["Broken"]
    assert results["Sample"]["new"] == 4


def test_keyword_match_uses_whole_words():
    result = analyze(make_db(), ["Hezbollah"], days=7, now=NOW)
    titles = [a["title"] for a in result["articles"]]
    assert result["total"] == 2
    assert not any("word-boundary" in t for t in titles)


def test_daily_counts():
    result = analyze(make_db(), ["Hezbollah"], days=7, now=NOW)
    assert result["by_day"]["2026-10-09"] == 1
    assert result["by_day"]["2026-10-10"] == 1
    assert result["by_day"]["2026-10-11"] == 0  # empty days are kept
    assert len(result["by_day"]) == 7


def test_find_spikes():
    counts = {"d1": 2, "d2": 3, "d3": 2, "d4": 2, "d5": 12}
    assert find_spikes(counts) == ["d5"]


def test_entities_exclude_keyword():
    result = analyze(make_db(), ["Hezbollah"], days=7, now=NOW)
    names = dict(result["entities"])
    assert "Hezbollah" not in names
    assert "Security Council" in names


def test_report_written(tmp_path):
    result = analyze(make_db(), ["Hezbollah"], days=7, now=NOW)
    path = make_report(result, tmp_path)
    text = path.read_text()
    assert "Hezbollah" in text
    assert (tmp_path / "coverage.png").exists()


def test_entities_exclude_source_names():
    articles = [{"source": "BBC Middle East", "title": "BBC finds UN and Iran link",
                 "summary": "", "published": "2026-10-10"}]
    names = dict(top_entities(articles, ["link"]))
    assert "BBC" not in names
    assert "Iran" in names
    assert "UN" in names
