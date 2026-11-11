"""Score the heuristics against hand-labeled articles.

Two parts of the tool make a judgment call on text: name extraction and the
tone word lists. Both are scored here on a labeled sample, so their error
rates are measured instead of assumed. The sample format is described at the
top of tests/fixtures/labeled_sample.json.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from . import entities
from .assessment import DIPLOMACY_TERMS, ESCALATION_TERMS, FAILURE_WORDS, uses_terms

KEYWORDS = ["Iran", "Iranian", "Tehran"]   # the topic the sample was drawn for


class Score(NamedTuple):
    correct: int   # found and right
    wrong: int     # found but not in the labels
    missed: int    # in the labels but not found

    @property
    def precision(self) -> float:
        found = self.correct + self.wrong
        return self.correct / found if found else 0.0

    @property
    def recall(self) -> float:
        wanted = self.correct + self.missed
        return self.correct / wanted if wanted else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0


def load_sample(path: str | Path) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = json.loads(
        Path(path).read_text(encoding="utf-8"))["articles"]
    return articles


def score_entities(sample: Sequence[Mapping[str, Any]], backend: str) -> Score:
    """Compare the names one extractor finds with the labeled names.

    A label can list several accepted forms ("Bessent" or "Scott Bessent");
    finding any of them is one correct answer. Names marked optional count
    neither for nor against.
    """
    correct = wrong = missed = 0
    found_per_article = entities.names_per_article(sample, KEYWORDS, backend)
    for article, found in zip(sample, found_per_article):
        names = set(found)
        wanted = [{g} if isinstance(g, str) else set(g) for g in article["entities"]]
        hits = sum(1 for forms in wanted if forms & names)
        accepted = set(article.get("optional", [])).union(*wanted)
        correct += hits
        missed += len(wanted) - hits
        wrong += len(names - accepted)
    return Score(correct, wrong, missed)


def score_tone(sample: Sequence[Mapping[str, Any]], kind: str) -> Score:
    """Compare one word list ("escalation" or "diplomacy") with the labels."""
    terms, failure = ((ESCALATION_TERMS, frozenset[str]()) if kind == "escalation"
                      else (DIPLOMACY_TERMS, FAILURE_WORDS))
    correct = wrong = missed = 0
    for article in sample:
        flagged = uses_terms(article, terms, failure)
        labeled = article["tone"] in (kind, "both")
        correct += flagged and labeled
        wrong += flagged and not labeled
        missed += labeled and not flagged
    return Score(correct, wrong, missed)


def report(sample: Sequence[Mapping[str, Any]]) -> str:
    """A small table of precision, recall and F1 for every heuristic."""
    rows = [("Names: regex", score_entities(sample, "regex"))]
    if entities.spacy_available():
        rows.append(("Names: spaCy", score_entities(sample, "spacy")))
    rows += [("Tone: escalation list", score_tone(sample, "escalation")),
             ("Tone: diplomacy list", score_tone(sample, "diplomacy"))]
    lines = [f"{len(sample)} labeled articles",
             f"{'':24}{'precision':>10}{'recall':>8}{'F1':>6}"]
    lines += [f"{name:24}{s.precision:>10.2f}{s.recall:>8.2f}{s.f1:>6.2f}" for name, s in rows]
    return "\n".join(lines)
