"""Tests for what the reader sees: Markdown tables, the HTML brief and the
command line. Headlines are untrusted text, so several tests feed in hostile ones.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from osint_monitor import cli
from osint_monitor.analyzer import analyze, compare_countries
from osint_monitor.assessment import build_assessment
from osint_monitor.brief import bluf, make_brief, safe_url, source_caveats, write_pdf
from osint_monitor.collector import connect, save
from osint_monitor.dedupe import tidy_title
from osint_monitor.report import make_report, md_cell, md_link, story_lines

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
KEYWORDS = ["Iran", "Tehran"]
HOSTILE = 'Iran talks <script>alert(1)</script> | "Politics" & more'


def at(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def fill(conn, hostile_link="javascript:alert(1)"):
    rows = []
    feeds = ["Haaretz", "Jerusalem Post", "JNS", "New York Times", "NPR", "CBS News",
             "IRNA", "Mehr News", "Tehran Times", "BBC Middle East"]
    topics = ["Missile strike reported near Hormuz", "Ceasefire talks resume in Doha",
              "Sanctions vote delayed in Congress", "Tanker seized by naval patrol"]
    for hours_ago in (3, 30, 54, 78, 102):
        for i, feed in enumerate(feeds):
            for j, topic in enumerate(topics):
                rows.append({"id": f"{hours_ago}-{i}-{j}", "source": feed,
                             "title": f"Iran: {topic} {feed.split()[0]} {hours_ago}",
                             "summary": "Trump and Netanyahu commented.",
                             "link": f"https://example.com/{hours_ago}/{i}/{j}",
                             "published": at(hours_ago), "collected": at(hours_ago)})
    rows.append({"id": "hostile", "source": "Haaretz", "title": HOSTILE, "summary": "",
                 "link": hostile_link, "published": at(1), "collected": at(1)})
    save(conn, rows)


def build(tmp_path, **brief_args):
    conn = connect(":memory:")
    fill(conn)
    result = analyze(conn, KEYWORDS, days=7, now=NOW)
    comparison = compare_countries(conn, KEYWORDS, days=7, now=NOW)
    assessment = build_assessment(result, comparison, NOW)
    report = make_report(result, tmp_path, comparison, assessment, now=NOW)
    brief = make_brief(result, comparison, assessment, tmp_path, NOW, **brief_args)
    return result, assessment, report.read_text(), brief.read_text()


# --- Markdown --------------------------------------------------------------------------

def test_pipe_in_a_headline_does_not_break_a_table():
    result = {"stories": [{"headline": "Arab News | Iran sent proposal", "outlets": ["A", "B"],
                           "first": "2026-10-25", "articles": 2}]}
    row = story_lines(result)[4]
    assert row == "| Arab News \\| Iran sent proposal | 2 | 2026-10-25 |"
    assert row.replace("\\|", "").count("|") == 4   # still exactly three cells


def test_md_cell_escapes_what_breaks_tables_and_links():
    assert md_cell("a | b") == "a \\| b"
    assert md_cell("[Live] update\nnow") == "\\[Live\\] update now"


def test_md_link_refuses_non_web_urls_and_encodes_brackets():
    assert md_link("Title", "javascript:alert(1)") == "Title"
    assert md_link("Title", "https://x.org/a(b) c") == "[Title](https://x.org/a%28b%29%20c)"


def test_report_tables_all_have_consistent_columns(tmp_path):
    _, _, report, _ = build(tmp_path)
    tables, rows = [], []
    for line in [*report.splitlines(), ""]:
        if line.startswith("|"):
            rows.append(line.replace("\\|", "").count("|"))
        elif rows:
            tables.append(rows)
            rows = []
    assert len(tables) >= 4
    assert all(len(set(table)) == 1 for table in tables)   # every row has the same cells


def test_site_names_are_stripped_from_displayed_headlines():
    assert tidy_title("Arab News | Iran sent nuclear proposal to the US") == (
        "Iran sent nuclear proposal to the US")
    assert tidy_title("Trump says war unlikely if talks advance | Politics") == (
        "Trump says war unlikely if talks advance")
    assert tidy_title("Trump says war unlikely if talks advance – Middle East Monitor") == (
        "Trump says war unlikely if talks advance")
    assert tidy_title("Iran talks - what we know") == "Iran talks - what we know"


# --- the brief ----------------------------------------------------------------------------

def test_brief_has_the_sections_of_an_analytic_product(tmp_path):
    _, assessment, _, html = build(tmp_path)
    for heading in ("Bottom line", "Key judgments", "What changed in the last 24 hours",
                    "Framing by country", "Source caveats"):
        assert heading in html
    assert html.count("confidence</span>") == len(assessment["judgments"])
    assert html.index("Bottom line") < html.index("Key judgments") < html.index("Source caveats")


def test_brief_is_self_contained(tmp_path):
    _, _, _, html = build(tmp_path)
    assert html.count("data:image/png;base64,") == 2      # both charts are embedded
    assert "<script" not in html and "http://" not in html.split("<main>")[0]


def test_brief_escapes_hostile_headlines_and_drops_hostile_links(tmp_path):
    _, _, _, html = build(tmp_path)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "javascript:" not in html


def test_safe_url():
    assert safe_url("https://example.com/a") == "https://example.com/a"
    assert safe_url("javascript:alert(1)") == "" and safe_url(None) == ""


def test_bluf_leads_with_the_judgments_and_flags_thin_evidence(tmp_path):
    result, assessment, _, _ = build(tmp_path)
    lines = bluf(result, assessment)
    assert lines[0] == assessment["judgments"][0]["claim"]
    weak = dict(assessment, judgments=[{"claim": "X.", "confidence": "Low", "basis": ""}])
    assert bluf(result, weak)[-1] == "Judgment 1 rests on thin evidence (Low confidence)."


def test_source_caveats_report_collection_problems(tmp_path):
    result, _, _, _ = build(tmp_path)
    health = {"checked": "2026-10-26T12:00+00:00", "sources": {
        "Haaretz": {"fetched": 10, "new": 2}, "NPR": {"error": "HTTP 403 Forbidden"},
        "Ynetnews": {"fetched": 30, "new": 0, "stale": True},
        "JNS": {"fetched": 30, "new": 30, "saturated": True}}}
    backfill = {"days": {"2026-10-24": 12, "2026-10-25": {"error": "HTTP 429"}}}
    caveats = " ".join(source_caveats(result, health, backfill))
    assert "3 of 4 feeds answered" in caveats and "Failed: NPR" in caveats
    assert "No item newer than a week: Ynetnews" in caveats
    assert "JNS" in caveats and "floor" in caveats
    assert "did not complete for: 2026-10-25" in caveats
    assert "state or state-affiliated" in caveats     # Iranian outlets are home press here


def test_pdf_is_skipped_cleanly_without_weasyprint(tmp_path, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_weasyprint(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_weasyprint)
    assert write_pdf("<p>x</p>", tmp_path / "brief.pdf") is False
    assert not (tmp_path / "brief.pdf").exists()


def test_pdf_is_written_when_weasyprint_is_installed(tmp_path):
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):   # not installed, or its system libraries are missing
        pytest.skip("WeasyPrint is not usable here")
    assert write_pdf("<p>x</p>", tmp_path / "brief.pdf") is True
    assert (tmp_path / "brief.pdf").read_bytes().startswith(b"%PDF")


# --- command line -------------------------------------------------------------------------

def test_cli_report_writes_report_brief_and_charts(tmp_path):
    db = tmp_path / "data" / "articles.db"
    conn = connect(db)
    now = datetime.now(timezone.utc)
    save(conn, [{"id": str(i), "source": feed, "title": f"Iran talks continue in Doha {i}",
                 "summary": "", "link": f"https://example.com/{i}",
                 "published": (now - timedelta(hours=2)).isoformat(),
                 "collected": now.isoformat()}
                for i, feed in enumerate(["Haaretz", "NPR", "IRNA", "JNS"])])
    conn.close()
    (db.parent / "source_status.json").write_text(json.dumps(
        {"checked": "now", "sources": {"NPR": {"error": "HTTP 500"}}}))
    out = tmp_path / "out"
    code = cli.main(["--db", str(db), "--quiet", "report", "--keywords", "Iran",
                     "--out", str(out), "--ner", "regex"])
    assert code == 0
    assert {p.name for p in out.iterdir()} >= {"report.md", "brief.html", "coverage.png"}
    assert "Failed: NPR" in (out / "brief.html").read_text()


def test_cli_collect_fails_loudly_when_every_source_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SOURCES", {"Broken": str(tmp_path / "missing.xml")})
    db = tmp_path / "articles.db"
    assert cli.main(["--db", str(db), "--quiet", "collect"]) == 1
    status = json.loads((tmp_path / "source_status.json").read_text())
    assert "error" in status["sources"]["Broken"]


def test_cli_check_refuses_an_empty_database(tmp_path):
    db = tmp_path / "a.db"
    assert cli.main(["--db", str(db), "--quiet", "check"]) == 1
    conn = connect(db)
    save(conn, [{"id": "a", "source": "NPR", "title": "t", "summary": "", "link": "l",
                 "published": at(1), "collected": at(1)}])
    conn.close()
    assert cli.main(["--db", str(db), "--quiet", "check"]) == 0


def test_cli_prune_and_evaluate(tmp_path, capsys):
    assert cli.main(["--db", str(tmp_path / "a.db"), "--quiet", "prune", "--keep-days", "30"]) == 0
    assert cli.main(["evaluate"]) == 0
    assert "Names: regex" in capsys.readouterr().out
