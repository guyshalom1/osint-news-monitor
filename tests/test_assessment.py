"""Tests for the written assessment and the three-country comparison.

Articles are built by hand with fixed dates, so no internet and no real
clock are involved.
"""

from datetime import datetime, timedelta, timezone

from osint_monitor.analyzer import compare_countries
from osint_monitor.assessment import (
    assessment_lines,
    build_assessment,
    confidence,
    divergence_judgment,
    entity_shifts,
    new_stories,
    split_windows,
    term_share,
    tone_judgment,
    volume_baseline,
    volume_claim,
    volume_judgment,
)
from osint_monitor.collector import connect, save
from osint_monitor.report import make_report

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def at(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def make(n, hours_ago, title="Talks continue", sources=("A", "B", "C")):
    """n articles published `hours_ago`, rotating through the sources."""
    return [{"source": sources[i % len(sources)], "title": f"{title} {i}",
             "summary": "", "link": f"http://x/{hours_ago}/{i}",
             "published": at(hours_ago)} for i in range(n)]


def result_for(articles, partial_days=()):
    return {"articles": articles, "keywords": ["Iran"],
            "partial_days": list(partial_days)}


# --- windows and confidence -------------------------------------------------

def test_split_windows():
    articles = make(2, 3) + make(3, 30) + make(1, 60)
    recent, prior = split_windows(articles, NOW)
    assert (len(recent), len(prior)) == (2, 3)  # the 60-hour-old one is ignored


def test_confidence_levels():
    assert confidence(80, 6) == "High"
    assert confidence(80, 2) == "Low"      # many articles, but one or two outlets repeating
    assert confidence(25, 3) == "Medium"
    assert confidence(10, 5) == "Low"


# --- volume ------------------------------------------------------------------

def test_volume_rising():
    j = volume_judgment(make(30, 3), make(20, 30), incomplete=False)
    assert j["claim"] == "Coverage is rising."
    assert "+50%" in j["basis"]


def test_volume_falling():
    j = volume_judgment(make(10, 3), make(20, 30), incomplete=False)
    assert j["claim"] == "Coverage is falling."


def test_volume_steady_within_threshold():
    j = volume_judgment(make(22, 3), make(20, 30), incomplete=False)
    assert j["claim"] == "Coverage is steady."


def test_volume_no_trend_without_earlier_data():
    j = volume_judgment(make(30, 3), make(2, 30), incomplete=False)
    assert j["claim"] == "No trend can be called yet."
    assert j["confidence"] == "Low"


def test_volume_no_trend_when_earlier_period_is_incomplete():
    j = volume_judgment(make(30, 3), make(30, 30), incomplete=True)
    assert j["confidence"] == "Low"
    assert "before collection started" in j["basis"]


def test_volume_claim_plain_when_both_comparisons_agree():
    assert volume_claim("falling", "falling") == "Coverage is falling."
    assert volume_claim("rising", None) == "Coverage is rising."


def test_volume_claim_says_when_comparisons_differ():
    assert volume_claim("falling", "steady") == (
        "Coverage fell against the day before and is near its usual level.")
    assert volume_claim("rising", "falling") == (
        "Coverage rose against the day before and is below its usual level.")
    assert volume_claim("steady", "rising") == (
        "Coverage was steady against the day before and is above its usual level.")


def test_volume_drop_from_a_busy_day_is_not_called_falling():
    baseline = {"mean": 22, "days": 5}
    j = volume_judgment(make(20, 3), make(40, 30), incomplete=False, baseline=baseline)
    assert j["claim"] == "Coverage fell against the day before and is near its usual level."
    assert "usual level is 22 a day" in j["basis"]


def test_volume_baseline_leaves_out_edge_and_partial_days():
    by_day = {"2026-10-19": 5, "2026-10-20": 100, "2026-10-21": 3, "2026-10-22": 100,
              "2026-10-23": 120, "2026-10-24": 80, "2026-10-25": 90, "2026-10-26": 40}
    # Out: the first day (cut short), the two days the last 24 hours touch
    # (25 and 26 Oct), and the partial day (21 Oct).
    result = {"by_day": by_day, "partial_days": ["2026-10-21"]}
    assert volume_baseline(result, NOW) == {"mean": 100, "days": 4}


def test_volume_baseline_needs_three_days():
    result = {"by_day": {"2026-10-23": 50, "2026-10-24": 60, "2026-10-25": 70,
                         "2026-10-26": 40}, "partial_days": []}
    assert volume_baseline(result, NOW) is None
    assert volume_baseline({"partial_days": []}, NOW) is None


# --- tone --------------------------------------------------------------------

def test_term_share_counts_articles_not_words():
    articles = [{"title": "Missile strike hits base", "summary": ""},
                {"title": "Quiet day", "summary": ""}]
    assert term_share(articles, ["strike", "missile"]) == 50


def test_tone_shifts_toward_diplomacy():
    recent = make(12, 3, title="Ceasefire talks resume")
    prior = make(12, 30, title="Missile strike on base")
    j = tone_judgment(recent, prior)
    assert j["claim"] == "Language is shifting toward diplomacy."


def test_tone_shifts_toward_escalation():
    recent = make(12, 3, title="Missile strike on base")
    prior = make(12, 30, title="Ceasefire talks resume")
    assert tone_judgment(recent, prior)["claim"] == "Language is shifting toward escalation."


def test_tone_unchanged_when_both_move_together():
    # A busy news day raises both kinds of words; that is not a shift.
    recent = make(12, 3, title="Missile strike as talks resume")
    prior = make(12, 30, title="Missile strike as talks resume")
    assert "unchanged" in tone_judgment(recent, prior)["claim"]


def test_tone_needs_enough_articles():
    j = tone_judgment(make(3, 3), make(3, 30))
    assert j["confidence"] == "Low"
    assert "Too few" in j["claim"]


# --- what changed --------------------------------------------------------------

def test_new_story_is_reported_and_old_story_is_not():
    old = "Parliament debates nuclear inspection law"
    fresh = "Tanker seized near Hormuz strait"
    prior = [{"source": "A", "title": old, "summary": "", "published": at(30)}]
    recent = [
        {"source": "A", "title": old, "summary": "", "published": at(3)},
        {"source": "B", "title": old, "summary": "", "published": at(3)},
        {"source": "A", "title": fresh, "summary": "", "published": at(2)},
        {"source": "B", "title": fresh, "summary": "", "published": at(2)},
    ]
    headlines = [s["headline"] for s in new_stories(recent, prior)]
    assert headlines == [fresh]


def test_entity_shifts_find_rising_and_falling_names():
    recent = make(6, 3, title="Hormuz closure fears grow")
    prior = make(6, 30, title="Baghdad talks stall")
    rising, falling = entity_shifts(recent, prior, ["Iran"])
    assert rising[0][0] == "Hormuz" and rising[0][1:] == (0, 100)
    assert falling[0][0] == "Baghdad" and falling[0][1:] == (100, 0)


def test_entity_shifts_empty_when_a_window_is_empty():
    assert entity_shifts(make(5, 3), [], ["Iran"]) == ([], [])


# --- divergence between countries -------------------------------------------------

def comparison(iran_matching=20):
    def country(share, matching, names, home=False):
        return {"home": home, "total": 100, "matching": matching, "share": share,
                "sources": ["S1", "S2", "S3"], "names": names, "headlines": []}
    return {"keywords": ["Iran"], "top_names": ["Houthi", "Trump"], "countries": {
        "Israel": country(13.0, 40, {"Houthi": 0, "Trump": 30}),
        "US": country(7.0, 30, {"Houthi": 28, "Trump": 14}),
        "Iran": country(60.0, iran_matching, {"Houthi": 5, "Trump": 40}, home=True),
    }}


def test_divergence_names_the_largest_framing_gap():
    j = divergence_judgment(comparison())
    assert '"Trump"' in j["claim"] or '"Houthi"' in j["claim"]
    assert "Houthi" in j["basis"] or "Trump" in j["basis"]


def test_divergence_leaves_home_press_out_of_attention():
    j = divergence_judgment(comparison())
    assert "Israel outlets give the topic 13.0%" in j["basis"]
    assert "Iran outlets give" not in j["basis"]
    assert "Home press is left out" in j["basis"]


def test_divergence_needs_two_countries():
    comp = comparison()
    comp["countries"]["Israel"]["matching"] = 0
    comp["countries"]["US"]["matching"] = 0
    assert divergence_judgment(comp)["claim"] == "Countries cannot be compared yet."


# --- the full assessment and the report ---------------------------------------------

def test_build_assessment_marks_early_data_as_incomplete():
    day_before = (NOW - timedelta(hours=30)).date().isoformat()
    a = build_assessment(result_for(make(30, 3) + make(30, 30), [day_before]),
                         None, NOW)
    assert a["judgments"][0]["confidence"] == "Low"


def test_assessment_lines_have_judgments_and_changes():
    a = build_assessment(result_for(make(30, 3) + make(20, 30)), comparison(), NOW)
    text = "\n".join(assessment_lines(a))
    assert "## Assessment" in text
    assert "## What changed in the last 24 hours" in text
    assert "Confidence:" in text


def make_db_with_three_countries():
    conn = connect(":memory:")
    rows = []
    for i, (source, word) in enumerate([
        ("Haaretz", "Iran"), ("Jerusalem Post", "Iran"), ("JNS", "Tehran"),
        ("New York Times", "Iran"), ("NPR", "Iran"),
        ("IRNA", "Iran"), ("Mehr News", "Iran"), ("Tehran Times", "Tehran"),
    ]):
        rows.append({"id": f"id{i}", "source": source,
                     "title": f"{word} talks continue in Vienna {i}",
                     "summary": "", "link": f"http://x/{i}",
                     "published": at(3), "collected": at(3)})
    save(conn, rows)
    return conn


def test_compare_countries_marks_home_press():
    comp = compare_countries(make_db_with_three_countries(), ["Iran", "Tehran"],
                             days=7, now=NOW)
    assert comp["countries"]["Iran"]["home"] is True
    assert comp["countries"]["Israel"]["home"] is False
    assert comp["countries"]["Iran"]["matching"] == 3


def test_report_has_assessment_first_and_three_country_chart(tmp_path):
    from osint_monitor.analyzer import analyze
    conn = make_db_with_three_countries()
    result = analyze(conn, ["Iran", "Tehran"], days=7, now=NOW)
    comp = compare_countries(conn, ["Iran", "Tehran"], days=7, now=NOW)
    assessment = build_assessment(result, comp, NOW)
    text = make_report(result, tmp_path, comp, assessment).read_text()
    assert text.index("## Assessment") < text.index("coverage.png")
    assert (tmp_path / "comparison.png").exists()
    assert "Home press" in text


def test_report_still_works_when_iran_feeds_return_nothing(tmp_path):
    from osint_monitor.analyzer import analyze
    conn = connect(":memory:")
    rows = [{"id": f"id{i}", "source": s, "title": f"Iran talks continue {i}",
             "summary": "", "link": f"http://x/{i}", "published": at(3),
             "collected": at(3)}
            for i, s in enumerate(["Haaretz", "JNS", "New York Times", "NPR"])]
    save(conn, rows)
    result = analyze(conn, ["Iran"], days=7, now=NOW)
    comp = compare_countries(conn, ["Iran"], days=7, now=NOW)
    text = make_report(result, tmp_path, comp, build_assessment(result, comp, NOW)).read_text()
    assert (tmp_path / "comparison.png").exists()
    assert "No matching articles from Iran" in text


# --- the same person under different names ---------------------------------

def test_titles_and_full_names_count_as_one_person():
    from osint_monitor.analyzer import top_entities
    arts = [
        {"title": "Prime Minister Benjamin Netanyahu said talks failed", "summary": ""},
        {"title": "Netanyahu warns Tehran", "summary": ""},
        {"title": "Israeli Prime Minister Netanyahu meets envoy", "summary": ""},
        {"title": "Benjamin Netanyahu to address UN", "summary": ""},
    ]
    names = dict(top_entities(arts, ["Tehran"]))
    assert names.get("Netanyahu") == 4
    assert not any("Minister" in n or "Benjamin" in n for n in names)


def test_two_word_places_are_not_merged_without_cause():
    from osint_monitor.analyzer import top_entities
    arts = [{"title": "Saudi Arabia hosts talks", "summary": ""}]
    assert "Saudi Arabia" in dict(top_entities(arts, ["talks"]))


def test_update_readme_fills_block_and_is_repeatable(tmp_path):
    from osint_monitor.report import update_readme

    readme = tmp_path / "README.md"
    readme.write_text("# T\n\n<!-- assessment:start -->\n<!-- assessment:end -->\n\nrest\n",
                      encoding="utf-8")
    articles = make(30, 5) + make(30, 30)
    result = result_for(articles)
    assessment = build_assessment(result, comparison(), NOW)

    assert update_readme(readme, assessment, "2026-10-26 12:00 UTC")
    first = readme.read_text(encoding="utf-8")
    assert "## Assessment" in first and first.rstrip().endswith("rest")
    assert update_readme(readme, assessment, "2026-10-26 12:00 UTC")
    assert readme.read_text(encoding="utf-8") == first  # no duplicate blocks


def test_update_readme_leaves_file_alone_without_markers(tmp_path):
    from osint_monitor.report import update_readme

    readme = tmp_path / "README.md"
    readme.write_text("# T\n", encoding="utf-8")
    assert not update_readme(readme, {"hours": 24, "judgments": [], "new_stories": [],
                                      "rising": [], "falling": []}, "x")
    assert readme.read_text(encoding="utf-8") == "# T\n"


def test_home_press_mirror_counts_mentions_of_other_countries():
    from osint_monitor.analyzer import mirror_share

    pool = [{"title": "US warns Tehran", "summary": ""},
            {"title": "Israeli strike", "summary": "Washington silent"},
            {"title": "Let us talk", "summary": ""},
            {"title": "Oil prices rise", "summary": "Israel and America react"}]
    m = mirror_share(pool, ["US", "Israel"])
    assert m == {"US": 50, "Israel": 50, "either": 75}  # "us" the pronoun is not the US
