"""Shapes of the data passed between modules.

Plain dicts keep the pipeline easy to inspect and to dump as JSON. The
TypedDicts below document which keys each stage produces, and let mypy catch
a misspelled key before a scheduled run does.
"""

from __future__ import annotations

from typing import Literal, TypedDict

Confidence = Literal["High", "Medium", "Low"]
Origin = Literal["rss", "gdelt"]


class Article(TypedDict, total=False):
    """One stored article. `id` and `collected` exist only on the way into the database."""

    id: str
    source: str
    title: str
    summary: str
    link: str
    published: str   # ISO timestamp, UTC
    collected: str
    origin: Origin   # "rss": one of the fixed feeds; "gdelt": backfilled


class Story(TypedDict):
    """A group of articles from different outlets about the same event."""

    headline: str
    first: str          # date first seen
    outlets: list[str]
    articles: int


class Judgment(TypedDict, total=False):
    claim: str
    confidence: Confidence
    basis: str
    caveats: list[str]


class Baseline(TypedDict):
    mean: float
    days: int


class AnalysisResult(TypedDict, total=False):
    keywords: list[str]
    days: int
    total: int
    reprints_removed: int
    collection_start: str
    partial_days: list[str]
    home_countries: list[str]
    by_day: dict[str, int]          # every matching article
    by_day_panel: dict[str, int]    # fixed feeds outside the topic country: the trend series
    by_day_home: dict[str, int]     # fixed feeds of the topic country
    by_day_gdelt: dict[str, int]    # backfilled articles (uneven from day to day)
    by_source: dict[str, int]
    by_day_source: dict[str, dict[str, int]]
    sources_per_day: dict[str, list[str]]
    spikes: list[str]
    stories: list[Story]
    entities: list[tuple[str, int]]
    ner_backend: str
    articles: list[Article]


class CountryData(TypedDict, total=False):
    home: bool
    mirror: dict[str, int]
    total: int
    matching: int
    share: float
    sources: list[str]
    names: dict[str, int]         # % of the country's topic articles mentioning the name
    name_counts: dict[str, int]   # the same as article counts, for significance tests
    headlines: list[Article]


class Comparison(TypedDict):
    keywords: list[str]
    countries: dict[str, CountryData]
    top_names: list[str]


EntityShift = tuple[str, int, int]   # name, earlier %, now %


class Assessment(TypedDict, total=False):
    hours: int
    recent: int
    prior: int
    scope: str
    judgments: list[Judgment]
    new_stories: list[Story]
    rising: list[EntityShift]
    falling: list[EntityShift]


class SourceHealth(TypedDict, total=False):
    fetched: int
    new: int
    newest: str | None
    stale: bool
    saturated: bool
    error: str
