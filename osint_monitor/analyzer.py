"""Analyze stored articles for a set of keywords.

Answers three questions an analyst would ask:
1. Volume: how much coverage is the topic getting, per day and per source?
2. Spikes: on which days did coverage jump well above normal?
3. Context: which names and places appear most often alongside the topic?

Counting over time needs a fixed set of sources. The database holds two
kinds of articles: items from the fixed RSS feeds, collected on every run,
and GDELT backfill, which succeeds on some days and is rate-limited on
others. Mixing them makes a day look busy because the backfill worked, so
trend, peak and spike detection use the RSS panel only. GDELT articles still
count for breadth: stories, sources and names.
"""

from __future__ import annotations

import math
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from . import entities
from .dedupe import remove_reprints, story_clusters
from .entities import top_entities
from .gdelt import query_key
from .models import AnalysisResult, Article, Comparison, CountryData
from .sources import COUNTRY, outlet_name


def load_articles(conn: sqlite3.Connection, days: int,
                  now: datetime | None = None) -> list[Article]:
    """Return articles published in the last `days` days, newest first."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT source, title, summary, link, published, origin FROM articles "
        "WHERE published >= ? AND published <= ? ORDER BY published DESC, rowid",
        (since, (now + timedelta(hours=1)).isoformat()),   # drop items dated in the future
    ).fetchall()
    return [{
        "source": outlet_name(source),   # "jpost.com" -> "Jerusalem Post"
        "title": title, "summary": summary or "", "link": link or "",
        "published": published, "origin": origin or "rss",
    } for source, title, summary, link, published, origin in rows]


def keyword_pattern(keywords: Iterable[str]) -> re.Pattern[str]:
    """One regex matching any keyword as a whole word, case-insensitive."""
    return re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b", re.IGNORECASE)


def matches(article: Mapping[str, Any], keywords: Iterable[str] | re.Pattern[str]) -> bool:
    """True if any keyword appears as a whole word in the title or summary."""
    pattern = keywords if isinstance(keywords, re.Pattern) else keyword_pattern(keywords)
    return bool(pattern.search(f"{article['title']} {article.get('summary') or ''}"))


def home_countries(keywords: Iterable[str]) -> list[str]:
    """Countries named in the keywords. Their press covers the topic as home news."""
    wanted = {k.lower() for k in keywords}
    return sorted(c for c in set(COUNTRY.values()) if c.lower() in wanted)


def is_panel(article: Mapping[str, Any], home: Iterable[str] = ()) -> bool:
    """True for the articles used to judge change over time: collected from a
    fixed RSS feed, and not from the topic country's own press.

    The topic country's outlets mention it in almost every story, sports and
    tourism included, so their count measures how much they publish, not how
    much attention the topic gets.
    """
    return (article.get("origin", "rss") == "rss"
            and COUNTRY.get(article["source"]) not in set(home))


def daily_counts(articles: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Number of articles per day, e.g. {'2026-10-10': 4, ...}."""
    return dict(sorted(Counter(a["published"][:10] for a in articles).items()))


def source_counts(articles: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Number of articles per source, largest first."""
    return dict(Counter(a["source"] for a in articles).most_common())


def condense_sources(by_source: Mapping[str, int], top: int) -> dict[str, int]:
    """Keep the `top` largest sources and add up the rest as one line.

    Real runs have 100+ outlets, most of them one article each (a long tail
    from GDELT). The long tail makes a table unreadable and a chart worse.
    Returns {source: n} with "Other (N outlets)" last, or the input unchanged
    when it already fits.
    """
    if len(by_source) <= top:
        return dict(by_source)
    items = list(by_source.items())
    rest = items[top:]
    condensed = dict(items[:top])
    condensed[f"Other ({len(rest)} outlets)"] = sum(n for _, n in rest)
    return condensed


def fill_days(counts: Mapping[str, int], days: int, now: datetime) -> dict[str, int]:
    """Add the days with no articles, so the timeline has no gaps.

    Without this, a quiet day simply disappears from the chart and the
    coverage looks continuous when it was not.
    """
    end = now.date()
    all_days = [(end - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    return {day: counts.get(day, 0) for day in all_days}


def find_spikes(counts: Mapping[str, int], threshold: float = 3.0,
                min_articles: int = 3) -> list[str]:
    """Days where coverage is well above the other days of the period.

    Each day is compared with the mean and spread of the *other* days, so a
    spike does not raise its own bar. The spread has a floor of sqrt(mean),
    the noise expected from counting alone, so 4 articles after a run of 2s
    is not a spike.

    The bar is 3 standard deviations. On simulated weeks of pure random
    variation at 30 articles a day this flags something in about 3% of
    weeks and still catches a doubling 93% of the time. A bar of 1.5 over
    the whole week, the earlier rule, flagged over half of such weeks.
    """
    if len(counts) < 3:
        return []
    spikes = []
    for day, n in counts.items():
        others = [v for d, v in counts.items() if d != day]
        mean = statistics.mean(others)
        spread = max(statistics.pstdev(others), math.sqrt(mean))
        if n >= min_articles and n > mean + threshold * spread:
            spikes.append(day)
    return spikes


def analyze(conn: sqlite3.Connection, keywords: Sequence[str], days: int = 7,
            now: datetime | None = None) -> AnalysisResult:
    """Run the full analysis and return the results as one dict."""
    now = now or datetime.now(timezone.utc)
    pattern = keyword_pattern(keywords)
    matched = [a for a in load_articles(conn, days, now) if matches(a, pattern)]
    # Wire copy republished under other domains would inflate every count.
    articles, reprints_removed = remove_reprints(matched)
    home = home_countries(keywords)

    def series(keep: Any) -> dict[str, int]:
        return fill_days(daily_counts(a for a in articles if keep(a)), days, now)

    by_day = series(lambda a: True)
    by_day_panel = series(lambda a: is_panel(a, home))
    by_day_gdelt = series(lambda a: a.get("origin") == "gdelt")
    by_day_home = {d: by_day[d] - by_day_panel[d] - by_day_gdelt[d] for d in by_day}

    # For each day, how many articles each source published: {day: {source: n}}
    by_day_source: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for a in articles:
        by_day_source[a["published"][:10]][a["source"]] += 1

    # Days before collection began are incomplete: RSS feeds only keep recent
    # items, so a low count there may mean "not collected", not "not covered".
    first = conn.execute("SELECT MIN(collected) FROM articles").fetchone()[0]
    start = first[:10] if first else now.date().isoformat()
    # Days backfilled from GDELT for these keywords count as complete.
    covered = {row[0] for row in conn.execute(
        "SELECT day FROM backfills WHERE query = ?", (query_key(keywords),))}
    partial = [d for d in by_day if d < start and d not in covered]

    return {
        "keywords": list(keywords),
        "collection_start": start,
        "partial_days": partial,
        "home_countries": home,
        "days": days,
        "total": len(articles),
        "reprints_removed": reprints_removed,
        "stories": story_clusters(articles)[:8],
        "by_day": by_day,
        "by_day_panel": by_day_panel,
        "by_day_home": by_day_home,
        "by_day_gdelt": by_day_gdelt,
        "by_source": source_counts(articles),
        "spikes": find_spikes({d: n for d, n in by_day_panel.items() if d not in partial}),
        "entities": top_entities(articles, keywords),
        "ner_backend": entities.backend(),
        "by_day_source": {d: dict(c) for d, c in by_day_source.items()},
        "sources_per_day": {d: sorted(c) for d, c in sorted(by_day_source.items())},
        "articles": articles,
    }


# How each country is referred to, for the mirror view of home press. Case
# matters ("US" the country, not "us" the pronoun).
MIRROR_TERMS = {
    "US": re.compile(r"\b(?:US|U\.S\.|United States|America|American|Americans)\b"),
    "Israel": re.compile(r"\b(?:Israel|Israeli|Israelis)\b"),
}


def mirror_share(pool: Sequence[Mapping[str, Any]], targets: Sequence[str]) -> dict[str, int]:
    """% of a country's articles that mention each target country, and either."""
    if not pool:
        return {}
    texts = [f"{a['title']}. {a['summary']}" for a in pool]
    out = {t: round(100 * sum(bool(MIRROR_TERMS[t].search(x)) for x in texts) / len(texts))
           for t in targets}
    either = sum(any(MIRROR_TERMS[t].search(x) for t in targets) for x in texts)
    out["either"] = round(100 * either / len(texts))
    return out


def compare_countries(conn: sqlite3.Connection, keywords: Sequence[str], days: int = 7,
                      now: datetime | None = None,
                      countries: Sequence[str] = ("Israel", "US", "Iran")) -> Comparison:
    """Compare how media in different countries cover the same topic.

    Counts differ a lot between countries (more feeds, longer feeds), so the
    comparison uses shares instead of raw numbers:
    - attention: % of a country's articles that are about the topic
    - framing:   % of a country's topic articles that mention each name

    A country named in the keywords (Iran, when tracking Iran) is the "home"
    press for the topic. It covers the topic as domestic news, so its share of
    attention is not comparable with the others, and its "mirror" shows the
    opposite view: how often it mentions the other countries.

    Only articles from the fixed feeds are used. GDELT articles carry no
    summary, so they would mention fewer names for a technical reason.
    """
    pattern = keyword_pattern(keywords)
    feed_articles = [a for a in load_articles(conn, days, now) if a.get("origin") == "rss"]
    home_set = set(home_countries(keywords))
    data: dict[str, CountryData] = {}

    for country in countries:
        pool = [a for a in feed_articles if COUNTRY.get(a["source"]) == country]
        topic = [a for a in pool if matches(a, pattern)]
        counts = dict(top_entities(topic, keywords, limit=None))
        home = country in home_set
        targets = [c for c in countries if c != country and c in MIRROR_TERMS]
        data[country] = {
            "home": home,
            "mirror": mirror_share(pool, targets) if home else {},
            "total": len(pool),
            "matching": len(topic),
            "share": round(100 * len(topic) / len(pool), 1) if pool else 0.0,
            "sources": sorted({a["source"] for a in pool}),
            "name_counts": counts,
            # % of this country's topic articles that mention each name
            "names": {n: round(100 * c / len(topic)) for n, c in counts.items()},
            "headlines": topic[:5],
        }

    # Names to compare: the most mentioned overall, by combined share.
    combined: Counter[str] = Counter()
    for country_data in data.values():
        combined.update(country_data["names"])
    return {"keywords": list(keywords), "countries": data,
            "top_names": [n for n, _ in combined.most_common(8)]}
