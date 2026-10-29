"""Tests run on a local sample feed, so they need no internet connection."""

import json
from datetime import datetime, timezone
from pathlib import Path

from osint_monitor.analyzer import analyze, clean_name, find_spikes, top_entities
from osint_monitor.collector import clean_text, collect, connect, save
from osint_monitor.dedupe import remove_reprints, story_clusters, title_words
from osint_monitor.gdelt import backfill, build_query, normalize, query_key
from osint_monitor.report import make_report
from osint_monitor.sources import COUNTRY, outlet_name

FEED = str(Path(__file__).parent / "fixtures" / "sample_feed.xml")
NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)


def make_db():
    conn = connect(":memory:")
    collect(conn, {"Sample": FEED}, now=NOW)
    return conn


def test_clean_text_strips_html():
    assert clean_text("<p>Hello &amp; welcome</p>") == "Hello & welcome"


def test_collect_skips_duplicates():
    conn = connect(":memory:")
    first = collect(conn, {"Sample": FEED}, now=NOW)
    second = collect(conn, {"Sample": FEED}, now=NOW)
    assert (first["Sample"]["fetched"], first["Sample"]["new"]) == (4, 4)
    assert (second["Sample"]["fetched"], second["Sample"]["new"]) == (4, 0)


def test_newest_item_date_recorded():
    conn = connect(":memory:")
    result = collect(conn, {"Sample": FEED}, now=NOW)["Sample"]
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


def test_clean_name():
    skip = {"iran"}
    assert clean_name("Riyadh's", skip) == "Riyadh"
    assert clean_name("Iran's Houthi", skip) == "Houthi"
    assert clean_name("Iran-backed Houthis", skip) == "Houthis"


def test_plurals_merged():
    articles = [
        {"source": "X", "title": "Houthi attack", "summary": "", "published": "2026-10-10"},
        {"source": "X", "title": "Houthis claim strike", "summary": "", "published": "2026-10-10"},
    ]
    assert dict(top_entities(articles, ["strike"]))["Houthi"] == 2


def test_report_written_when_all_days_partial(tmp_path):
    """Collection that started after the whole window must not crash the report."""
    later = datetime(2026, 10, 20, tzinfo=timezone.utc)
    conn = connect(":memory:")
    collect(conn, {"Sample": FEED}, now=later)
    result = analyze(conn, ["Hezbollah"], days=7, now=NOW)
    path = make_report(result, tmp_path)
    assert "Not enough complete days" in path.read_text()


# --- GDELT backfill (no internet: responses are faked) ---


class FakeResponse:
    def __init__(self, body):
        self.body = body.encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_opener(items):
    def opener(request, timeout=0):
        return FakeResponse(json.dumps({"articles": items}))
    return opener


GDELT_ITEM = {"url": "https://example.com/a", "title": "Iran talks resume",
              "seendate": "20261010T120000Z", "domain": "example.com"}


def test_build_query_quotes_phrases():
    assert build_query(["Iran", "Security Council"]) == \
        '(Iran OR "Security Council") sourcelang:english'


def test_gdelt_normalize():
    article = normalize(GDELT_ITEM, NOW)
    assert article["source"] == "example.com"
    assert article["published"].startswith("2026-10-10")
    assert normalize({"url": "", "title": "x", "seendate": "bad"}, NOW) is None


def test_backfill_marks_past_days_complete_and_dedupes():
    conn = connect(":memory:")
    opener = fake_opener([GDELT_ITEM])
    first = backfill(conn, ["Iran"], days=3, now=NOW, opener=opener, pause=0)
    assert sum(first.values()) == 1          # same link on every day: saved once
    covered = {r[0] for r in conn.execute(
        "SELECT day FROM backfills WHERE query = ?", (query_key(["Iran"]),))}
    assert covered == {"2026-10-10", "2026-10-11"}   # today is never marked
    second = backfill(conn, ["Iran"], days=3, now=NOW, opener=opener, pause=0)
    assert list(second) == ["2026-10-12"]    # only today is refreshed


def test_backfilled_days_are_not_partial():
    conn = connect(":memory:")
    backfill(conn, ["Iran"], days=3, now=NOW, opener=fake_opener([GDELT_ITEM]), pause=0)
    result = analyze(conn, ["Iran"], days=3, now=NOW)
    assert result["partial_days"] == []


def test_backfill_survives_a_failing_day():
    conn = connect(":memory:")

    def broken(request, timeout=0):
        raise RuntimeError("rate limited")
    out = backfill(conn, ["Iran"], days=2, now=NOW, opener=broken, pause=0)
    assert all("error" in v for v in out.values())


def test_plain_text_reply_is_an_error_not_an_empty_day():
    conn = connect(":memory:")

    def text_reply(request, timeout=0):
        return FakeResponse("The specified phrase is too short.")
    out = backfill(conn, ["Iran"], days=2, now=NOW, opener=text_reply, pause=0)
    assert all("unexpected reply" in v["error"] for v in out.values())
    assert conn.execute("SELECT COUNT(*) FROM backfills").fetchone()[0] == 0


def test_backfill_stops_after_repeated_errors_and_skips_empty_days_as_complete():
    conn = connect(":memory:")

    def broken(request, timeout=0):
        raise RuntimeError("rate limited")
    out = backfill(conn, ["Iran"], days=5, now=NOW, opener=broken, pause=0)
    assert sum("error" in v for v in out.values()) == 2
    assert sum("skipped" in v for v in out.values()) == 3

    backfill(conn, ["Iran"], days=2, now=NOW, opener=fake_opener([]), pause=0)
    assert conn.execute("SELECT COUNT(*) FROM backfills").fetchone()[0] == 0


# --- reprints and story clusters ---


def art(source, title, day="2026-10-10"):
    return {"source": source, "title": title, "summary": "", "link": title + source,
            "published": f"{day}T10:00:00+00:00"}


def test_title_words_ignores_outlet_tag_and_stopwords():
    assert title_words("Iran talks resume in Geneva - Reuters") == \
        frozenset({"iran", "talks", "resume", "geneva"})


def test_reprints_removed_keeping_earliest():
    a = art("wire.com", "Minister issues hard no on Russian diesel imports", "2026-10-10")
    b = art("regional.com.au", "Minister issues hard no on Russian diesel imports", "2026-10-11")
    other = art("bbc.com", "Storm hits the coast of Mexico overnight")
    kept, removed = remove_reprints([b, a, other])
    assert removed == 1
    assert a in kept and b not in kept and other in kept


def test_reprints_far_apart_in_time_are_kept():
    a = art("x.com", "Minister issues hard no on Russian diesel imports", "2026-10-01")
    b = art("y.com", "Minister issues hard no on Russian diesel imports", "2026-10-10")
    assert remove_reprints([a, b])[1] == 0


def test_short_titles_are_never_treated_as_duplicates():
    kept, removed = remove_reprints([art("a", "Live updates"), art("b", "Live updates")])
    assert removed == 0


def test_stories_group_different_outlets_and_ignore_single_outlet():
    arts = [
        art("NYT", "Pope Leo undergoes successful surgery to remove lung nodule"),
        art("Fox", "Pope Leo surgery to remove lung nodule was successful"),
        art("BBC", "Hurricane lashes Mexico Pacific coast resorts"),
        art("CBS", "Hurricane lashes Mexico Pacific coast resorts towns"),
        art("CBS", "Transcript: Sen. Murphy on Face the Nation"),
        art("CBS", "Transcript: Sen. Barrasso on Face the Nation"),
    ]
    stories = story_clusters(arts)
    outlets = [set(s["outlets"]) for s in stories]
    assert {"NYT", "Fox"} in outlets
    assert {"BBC", "CBS"} in outlets
    assert not any(s["outlets"] == ["CBS"] for s in stories)  # one outlet is not a story


def test_backfill_respects_time_budget():
    conn = connect(":memory:")
    ticks = iter(range(0, 1000, 100))   # every clock() call jumps 100 seconds
    out = backfill(conn, ["Iran"], days=4, now=NOW, opener=fake_opener([GDELT_ITEM]),
                   pause=0, budget=150, clock=lambda: next(ticks))
    assert any("time budget" in v.get("skipped", "") for v in out.values()
               if isinstance(v, dict))


def test_month_abbreviations_and_generic_words_are_not_names():
    from osint_monitor.analyzer import clean_name

    for word in ("Oct", "Ministry", "News", "According"):
        assert clean_name(word, set()) == ""
    assert clean_name("Tel Aviv", set()) == "Tel Aviv"


def test_country_and_demonym_count_once_per_article():
    articles = [
        {"title": "Israeli strike", "summary": "Israel says the American envoy left"},
        {"title": "Israel talks", "summary": "United States and Israeli officials met"},
    ]
    counts = dict(top_entities(articles, ["Iran"]))
    assert counts["Israel"] == 2 and "Israeli" not in counts
    assert counts["US"] == 2 and "American" not in counts


def test_outlet_name_maps_gdelt_domains_to_feed_names():
    assert outlet_name("jpost.com") == "Jerusalem Post"
    assert outlet_name("www.nytimes.com") == "New York Times"
    assert outlet_name("Jerusalem Post") == "Jerusalem Post"   # feed names pass through
    assert outlet_name("unknown-site.org") == "unknown-site.org"
    assert COUNTRY[outlet_name("jpost.com")] == "Israel"       # so it counts for Israel


def test_load_articles_counts_domain_and_feed_as_one_outlet():
    conn = connect(":memory:")
    save(conn, [
        {"id": "a", "source": "Jerusalem Post", "title": "Hezbollah talks begin", "summary": "",
         "link": "http://x/a", "published": "2026-10-10", "collected": "2026-10-10"},
        {"id": "b", "source": "jpost.com", "title": "Border clash near Metula", "summary": "",
         "link": "http://x/b", "published": "2026-10-10", "collected": "2026-10-10"},
    ])
    result = analyze(conn, ["Hezbollah", "Metula"], days=7, now=NOW)
    assert result["by_source"] == {"Jerusalem Post": 2}
