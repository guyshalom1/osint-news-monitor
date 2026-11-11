"""Tests for the rules that keep the judgments honest: a fixed panel of
sources, changes that must beat sampling noise, and a check that one outlet
is not the whole story.
"""

from datetime import datetime, timedelta, timezone

from osint_monitor.analyzer import analyze, compare_countries, find_spikes, is_panel
from osint_monitor.assessment import (
    DIPLOMACY_TERMS,
    ESCALATION_TERMS,
    FAILURE_WORDS,
    build_assessment,
    count_change_is_noise,
    divergence_judgment,
    entity_shifts,
    tone_judgment,
    uses_terms,
    volume_judgment,
)
from osint_monitor.collector import connect, save

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def at(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def make(n, hours_ago, title="Talks continue", sources=("A", "B", "C")):
    return [{"source": sources[i % len(sources)], "title": f"{title} {i}",
             "summary": "", "link": f"http://x/{hours_ago}/{title}/{i}",
             "published": at(hours_ago)} for i in range(n)]


def text(title, summary=""):
    return {"title": title, "summary": summary}


# --- the panel: compare like with like ---------------------------------------------

def test_panel_is_fixed_feeds_outside_the_topic_country():
    assert is_panel({"source": "Haaretz", "origin": "rss"}, ["Iran"])
    assert not is_panel({"source": "Tehran Times", "origin": "rss"}, ["Iran"])   # home press
    assert not is_panel({"source": "example.com", "origin": "gdelt"}, ["Iran"])  # backfill
    assert is_panel({"source": "Tehran Times", "origin": "rss"}, [])   # no home country


def test_backfill_and_home_press_do_not_move_the_trend_series():
    """A day is not busier because GDELT happened to answer that day."""
    conn = connect(":memory:")
    day = "2026-10-25T10:00:00+00:00"
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
    rows = []
    for i, (source, origin) in enumerate(
            [("Haaretz", "rss"), ("NPR", "rss")]
            + [("Tehran Times", "rss")] * 3 + [(f"site{i}.com", "gdelt") for i in range(3)]):
        rows.append({"id": str(i), "source": source, "origin": origin, "summary": "",
                     "title": f"Iran {words[i]} {words[i]}x {words[i]}y {words[i]}z",
                     "link": f"http://x/{i}", "published": day, "collected": day})
    save(conn, rows)
    result = analyze(conn, ["Iran"], days=3, now=NOW)
    assert result["by_day"]["2026-10-25"] == 8
    assert result["by_day_panel"]["2026-10-25"] == 2
    assert result["by_day_home"]["2026-10-25"] == 3
    assert result["by_day_gdelt"]["2026-10-25"] == 3
    assert result["home_countries"] == ["Iran"]


def test_assessment_measures_trends_on_the_panel_only():
    panel = make(30, 3, sources=("Haaretz", "NPR", "BBC Middle East"))
    home = make(200, 3, title="Home story", sources=("Tehran Times",))
    earlier = make(30, 30, sources=("Haaretz", "NPR", "BBC Middle East"))
    result = {"articles": panel + home + earlier, "keywords": ["Iran"], "partial_days": []}
    assessment = build_assessment(result, None, NOW)
    assert (assessment["recent"], assessment["prior"]) == (30, 30)
    assert assessment["judgments"][0]["claim"] == "Coverage is steady."
    assert "outside Iran" in assessment["scope"]


def test_country_comparison_ignores_backfilled_articles():
    conn = connect(":memory:")
    save(conn, [
        {"id": "a", "source": "Jerusalem Post", "title": "Iran talks resume in Vienna",
         "summary": "", "link": "a", "published": at(3), "collected": at(3)},
        {"id": "b", "source": "jpost.com", "title": "Iran says deal is close now",
         "summary": "", "link": "b", "published": at(3), "collected": at(3)},
    ])
    comp = compare_countries(conn, ["Iran"], days=7, now=NOW)
    assert comp["countries"]["Israel"]["matching"] == 1


# --- spikes ----------------------------------------------------------------------------

def test_a_clear_jump_is_a_spike():
    assert find_spikes({"d1": 10, "d2": 12, "d3": 9, "d4": 11, "d5": 40}) == ["d5"]


def test_ordinary_variation_is_not_a_spike():
    # Inside day-to-day noise for about 30 articles a day. The earlier rule
    # (mean + 1.5 sd over the week) flagged d5.
    assert find_spikes({"d1": 28, "d2": 33, "d3": 25, "d4": 31, "d5": 39,
                        "d6": 30, "d7": 27}) == []


def test_small_wobble_on_a_quiet_topic_is_not_a_spike():
    assert find_spikes({"d1": 2, "d2": 2, "d3": 2, "d4": 2, "d5": 4}) == []


# --- volume ----------------------------------------------------------------------------

def test_count_noise_rule():
    assert count_change_is_noise(30, 20)       # +50%, still inside chance
    assert not count_change_is_noise(60, 40)   # the same +50% on twice the articles


def test_volume_change_inside_noise_is_not_called_and_lowers_confidence():
    j = volume_judgment(make(30, 3), make(20, 30), incomplete=False)
    assert j["claim"] == "Coverage is steady."
    assert j["confidence"] == "Low"            # 50 articles would be Medium
    assert "confirm or rule out" in j["caveats"][0]


def test_volume_rise_from_one_outlet_lowers_confidence():
    steady = make(40, 3, sources=("A", "B", "C", "D", "E")) + make(40, 30, title="Earlier",
                                                                  sources=("A", "B", "C", "D", "E"))
    flood = make(60, 3, title="Flood", sources=("Loud",))
    recent = [a for a in steady + flood if a["published"] == at(3)]
    prior = [a for a in steady if a["published"] == at(30)]
    j = volume_judgment(recent, prior, incomplete=False)
    assert j["claim"] == "Coverage is rising."
    assert j["confidence"] == "Medium"         # High on size alone
    assert "Loud" in j["caveats"][0]


# --- tone ---------------------------------------------------------------------------------

def test_negated_terms_do_not_count():
    assert uses_terms(text("US launches strike on port"), ESCALATION_TERMS)
    assert not uses_terms(text("US rules out a strike on port"), ESCALATION_TERMS)
    assert not uses_terms(text("Trump unlikely to order Iran attack"), ESCALATION_TERMS)
    assert not uses_terms(text("Tehran rejects talks with Washington"), DIPLOMACY_TERMS)


def test_failed_diplomacy_does_not_count_as_diplomacy():
    assert uses_terms(text("Nuclear talks resume in Doha"), DIPLOMACY_TERMS, FAILURE_WORDS)
    assert not uses_terms(text("Nuclear talks collapse in Doha"), DIPLOMACY_TERMS, FAILURE_WORDS)
    assert not uses_terms(text("Ceasefire talks called off"), DIPLOMACY_TERMS, FAILURE_WORDS)


def test_terms_match_whole_words_only():
    assert not uses_terms(text("Striker scores twice for Persepolis"), ESCALATION_TERMS)
    assert not uses_terms(text("Dealer fined over car sales"), DIPLOMACY_TERMS)


def test_the_name_of_the_war_is_not_escalation_language():
    assert not uses_terms(text("How the Iran war changed oil markets"), ESCALATION_TERMS)


def test_small_tone_move_is_not_called_a_shift():
    """6 points on about 140 articles a window: the kind of move that used to
    be reported as a High-confidence shift."""
    outlets = ("A", "B", "C", "D", "E")

    def window(hours_ago, escalation, diplomacy, total):
        return (make(escalation, hours_ago, "Missile strike reported", outlets)
                + make(diplomacy, hours_ago, "Ceasefire talks held", outlets)
                + make(total - escalation - diplomacy, hours_ago, "Budget vote held", outlets))
    j = tone_judgment(window(3, 60, 24, 158), window(30, 44, 23, 122))
    assert "unchanged" in j["claim"]
    assert j["confidence"] == "Medium"         # High on size alone
    assert "confirm or rule out" in j["caveats"][0]


def test_tone_shift_carried_by_one_outlet_lowers_confidence():
    quiet = ("A", "B", "C", "D", "E")
    recent = make(40, 3, "Budget vote held", quiet) + make(40, 3, "Missile strike", ("Loud",))
    prior = make(40, 30, "Budget vote held", quiet) + make(40, 30, "Budget vote held", ("Loud",))
    j = tone_judgment(recent, prior)
    assert j["claim"] == "Language is shifting toward escalation."
    assert j["confidence"] == "Medium"
    assert "Loud" in j["caveats"][0]


def test_home_press_tone_is_reported_separately():
    j = tone_judgment(make(12, 3), make(12, 30),
                      home_recent=make(12, 3, "Missile strike"), home_prior=make(12, 30))
    assert "Home press, measured separately: escalation words in 100%" in j["basis"]


# --- divergence ---------------------------------------------------------------------------

def comparison(names_israel, names_us, n_israel=100, n_us=100, top=("Vance",)):
    def country(matching, names, home=False):
        return {"home": home, "total": 500, "matching": matching, "share": 10.0,
                "sources": ["S1", "S2", "S3"], "names": names, "headlines": []}
    return {"keywords": ["Iran"], "top_names": list(top), "countries": {
        "Israel": country(n_israel, names_israel), "US": country(n_us, names_us)}}


def test_framing_gap_on_a_small_sample_is_not_called():
    # 19% against 3% looks large, but it is 6 articles out of 32.
    j = divergence_judgment(comparison({"Vance": 3}, {"Vance": 19}, n_israel=140, n_us=32))
    assert j["claim"] == "No large framing gap between countries."


def test_framing_gap_on_a_solid_sample_is_called():
    j = divergence_judgment(comparison({"Vance": 5}, {"Vance": 30}))
    assert '"Vance"' in j["claim"]


def test_a_country_naming_itself_is_not_a_framing_gap():
    j = divergence_judgment(comparison({"Israel": 60}, {"Israel": 10}, top=("Israel",)))
    assert j["claim"] == "No large framing gap between countries."


def test_gap_against_home_press_carries_a_caveat():
    comp = comparison({"Trump": 40}, {"Trump": 38}, top=("Trump",))
    comp["countries"]["Iran"] = {"home": True, "total": 500, "matching": 400, "share": 80.0,
                                 "sources": ["S1", "S2", "S3"], "names": {"Trump": 8},
                                 "headlines": []}
    j = divergence_judgment(comp)
    assert '"Trump"' in j["claim"]
    assert "home press" in j["caveats"][0]


# --- names that moved ----------------------------------------------------------------------

def test_name_shift_inside_noise_is_not_reported():
    recent = make(3, 3, "Hormuz closure fears") + make(17, 3, "Budget vote held")
    prior = make(1, 30, "Hormuz closure fears") + make(19, 30, "Budget vote held")
    assert entity_shifts(recent, prior, ["Iran"]) == ([], [])   # 5% to 15% on 20 articles
