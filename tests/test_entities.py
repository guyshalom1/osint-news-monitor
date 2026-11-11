"""Tests for name extraction: the shared cleanup, the spaCy model against
the regex fallback on labeled articles, and the tone word lists.
"""

from pathlib import Path

import pytest

from osint_monitor import entities, evaluate
from osint_monitor.entities import canonical_names, clean_name, top_entities

SAMPLE = evaluate.load_sample(Path(__file__).parent / "fixtures" / "labeled_sample.json")
needs_spacy = pytest.mark.skipif(not entities.spacy_available(),
                                 reason="spaCy or en_core_web_sm is not installed")


# --- cleanup shared by both extractors -------------------------------------------

def test_clean_name_trims_articles_and_curly_possessives():
    assert clean_name("the Strait of Hormuz", set()) == "Hormuz"   # "Strait" is generic
    assert clean_name("the White House", set()) == "White House"
    assert clean_name("Iran’s Qeshm Island", {"iran"}) == "Qeshm Island"
    assert clean_name("Semnan province", set()) == "Semnan"


def test_name_in_two_forms_counts_once_per_article():
    articles = [{"title": "Benjamin Netanyahu spoke", "summary": "Netanyahu said talks failed"}]
    assert dict(top_entities(articles, ["talks"]))["Netanyahu"] == 1


def test_only_people_are_merged_into_a_surname_when_types_are_known():
    labels = {"Donald Trump": {"PERSON"}, "Trump": {"PERSON"},
              "White House": {"ORG"}, "House": {"ORG"}}
    assert canonical_names(labels) == {"Donald Trump": "Trump"}


def test_auto_backend_falls_back_to_regex_without_spacy(monkeypatch):
    monkeypatch.setattr(entities, "spacy_available", lambda: False)
    assert entities.use_backend("auto") == "regex"
    with pytest.raises(RuntimeError, match="not installed"):
        entities.use_backend("spacy")


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError):
        entities.use_backend("guess")


# --- regex against spaCy on 50 labeled articles -------------------------------------

def test_regex_baseline_on_labeled_sample():
    score = evaluate.score_entities(SAMPLE, "regex")
    assert score.f1 >= 0.70, score


@needs_spacy
def test_spacy_beats_regex_on_labeled_sample():
    regex = evaluate.score_entities(SAMPLE, "regex")
    spacy = evaluate.score_entities(SAMPLE, "spacy")
    assert spacy.f1 >= 0.85, spacy
    assert spacy.precision > regex.precision + 0.10   # the model's main gain
    assert spacy.recall > regex.recall
    assert spacy.wrong < regex.wrong / 2              # under half the false names


@needs_spacy
def test_spacy_reads_context_the_regex_cannot():
    article = [{"title": "France Blames Iran for Cyberattack on Refrigeration Systems",
                "summary": "The U.S. and the U.K. were briefed."}]
    regex = set(entities.names_per_article(article, ["Iran"], "regex")[0])
    spacy = set(entities.names_per_article(article, ["Iran"], "spacy")[0])
    assert "Refrigeration Systems" in regex            # title case fools the regex
    assert "Refrigeration Systems" not in spacy
    assert {"US", "UK"} <= spacy and not {"US", "UK"} & regex   # "U.S." needs a tokenizer


@needs_spacy
def test_spacy_backend_runs_through_the_same_counting():
    entities.use_backend("spacy")
    articles = [{"title": "Prime Minister Benjamin Netanyahu met Marco Rubio in Washington",
                 "summary": "Netanyahu and Rubio discussed Lebanon."}]
    names = dict(top_entities(articles, ["Iran"]))
    assert names["Netanyahu"] == 1 and names["Rubio"] == 1 and names["Washington"] == 1


# --- tone word lists against the same labels ------------------------------------------

def test_tone_lists_on_labeled_sample():
    """Floors a little under the measured scores (escalation 0.79 / 0.60,
    diplomacy 1.00 / 0.75), so a careless edit to the lists fails the build."""
    escalation = evaluate.score_tone(SAMPLE, "escalation")
    diplomacy = evaluate.score_tone(SAMPLE, "diplomacy")
    assert escalation.precision >= 0.75 and escalation.recall >= 0.55, escalation
    assert diplomacy.precision >= 0.85 and diplomacy.recall >= 0.70, diplomacy


def test_evaluation_report_lists_every_heuristic():
    table = evaluate.report(SAMPLE)
    assert "Names: regex" in table and "Tone: diplomacy list" in table
