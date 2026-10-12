"""Analyze stored articles for a set of keywords.

Answers three questions an analyst would ask:
1. Volume: how much coverage is the topic getting, per day and per source?
2. Spikes: on which days did coverage jump well above normal?
3. Context: which names and places appear most often alongside the topic?
"""

import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .sources import COUNTRY, OUTLET_NAMES

# Capitalized words that start sentences or are too generic to be useful.
STOPWORDS = {
    "The", "A", "An", "In", "On", "At", "For", "And", "But", "Or", "Of", "To",
    "With", "By", "From", "As", "After", "Before", "Over", "Under", "Amid",
    "He", "She", "It", "They", "We", "His", "Her", "Their", "This", "That",
    "These", "Those", "What", "Who", "Why", "How", "When", "Where", "Is",
    "Are", "Was", "Were", "Will", "Would", "Could", "Should", "Says", "Said",
    "New", "Live", "Watch", "Update", "Continue", "Read", "More", "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday", "Sunday", "January", "February",
    "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
}

# One or more capitalized words in a row, e.g. "Security Council", "Gaza".
NAME_PATTERN = re.compile(r"\b[A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+)*\b")


def load_articles(conn, days, now=None):
    """Return articles published in the last `days` days, newest first."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT source, title, summary, link, published FROM articles "
        "WHERE published >= ? ORDER BY published DESC",
        (since,),
    ).fetchall()
    keys = ("source", "title", "summary", "link", "published")
    return [dict(zip(keys, row)) for row in rows]


def matches(article, keywords):
    """True if any keyword appears as a whole word in the title or summary."""
    text = f"{article['title']} {article['summary']}"
    return any(
        re.search(rf"\b{re.escape(k)}\b", text, re.IGNORECASE) for k in keywords
    )


def daily_counts(articles):
    """Number of articles per day, e.g. {'2026-10-10': 4, ...}."""
    return dict(sorted(Counter(a["published"][:10] for a in articles).items()))


def source_counts(articles):
    """Number of articles per source, largest first."""
    return dict(Counter(a["source"] for a in articles).most_common())


def fill_days(counts, days, now):
    """Add the days with no articles, so the timeline has no gaps.

    Without this, a quiet day simply disappears from the chart and the
    coverage looks continuous when it was not.
    """
    end = now.date()
    all_days = [(end - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    return {day: counts.get(day, 0) for day in all_days}


def find_spikes(counts, threshold=1.5, min_articles=3):
    """Days where coverage is well above the period's average.

    A day is a spike if its count is above mean + threshold * standard
    deviation, and it has at least `min_articles` (to ignore noise on
    quiet topics).
    """
    values = list(counts.values())
    if len(values) < 3:
        return []
    cutoff = statistics.mean(values) + threshold * statistics.pstdev(values)
    return [day for day, n in counts.items() if n > cutoff and n >= min_articles]


def clean_name(name, skip):
    """Normalize one capitalized phrase, or return "" to drop it.

    "Riyadh's" -> "Riyadh", "Iran's Houthi" -> "Houthi" (keyword removed),
    "Iran-backed Houthis" -> "Houthis".
    """
    words = []
    for word in name.split():
        word = re.sub(r"'s$", "", word)
        lower = word.lower()
        if word in STOPWORDS or lower in skip:
            continue
        if any(lower.startswith(k + "-") for k in skip):  # "Iran-backed"
            continue
        words.append(word)
    return " ".join(words)


def top_entities(articles, keywords, limit=10):
    """Most frequent names/places mentioned alongside the keywords.

    A simple heuristic: runs of capitalized words. Not as accurate as a full
    NLP model, but fast, transparent and good enough to surface patterns.
    """
    skip = {k.lower() for k in keywords}
    skip |= {name.lower() for name in OUTLET_NAMES}
    counter = Counter()
    for a in articles:
        found = set()  # count each name once per article
        for name in NAME_PATTERN.findall(f"{a['title']}. {a['summary']}"):
            name = clean_name(name, skip)
            if len(name) >= 2 and name.lower() not in skip:
                found.add(name)
        counter.update(found)

    # Merge plurals into the singular when both appear: "Houthis" -> "Houthi".
    for name in list(counter):
        if name.endswith("s") and name[:-1] in counter:
            counter[name[:-1]] += counter.pop(name)
    return counter.most_common(limit)


def analyze(conn, keywords, days=7, now=None):
    """Run the full analysis and return the results as one dict."""
    now = now or datetime.now(timezone.utc)
    articles = [a for a in load_articles(conn, days, now) if matches(a, keywords)]
    by_day = fill_days(daily_counts(articles), days, now)

    # For each day, how many articles each source published: {day: {source: n}}
    by_day_source = defaultdict(Counter)
    for a in articles:
        by_day_source[a["published"][:10]][a["source"]] += 1

    # Days before collection began are incomplete: RSS feeds only keep recent
    # items, so a low count there may mean "not collected", not "not covered".
    first = conn.execute("SELECT MIN(collected) FROM articles").fetchone()[0]
    start = first[:10] if first else now.date().isoformat()
    partial = [d for d in by_day if d < start]

    return {
        "keywords": keywords,
        "collection_start": start,
        "partial_days": partial,
        "days": days,
        "total": len(articles),
        "by_day": by_day,
        "by_source": source_counts(articles),
        "spikes": find_spikes({d: n for d, n in by_day.items() if d not in partial}),
        "entities": top_entities(articles, keywords),
        "by_day_source": {d: dict(c) for d, c in by_day_source.items()},
        "sources_per_day": {d: sorted(c) for d, c in sorted(by_day_source.items())},
        "articles": articles,
    }


def compare_countries(conn, keywords, days=7, now=None, countries=("Israel", "US")):
    """Compare how media in different countries cover the same topic.

    Counts differ a lot between countries (more feeds, longer feeds), so the
    comparison uses shares instead of raw numbers:
    - attention: % of a country's articles that are about the topic
    - framing:   % of a country's topic articles that mention each name
    """
    all_articles = load_articles(conn, days, now)
    result = {"keywords": keywords, "countries": {}}

    for country in countries:
        pool = [a for a in all_articles if COUNTRY.get(a["source"]) == country]
        topic = [a for a in pool if matches(a, keywords)]
        names = top_entities(topic, keywords, limit=50)
        result["countries"][country] = {
            "total": len(pool),
            "matching": len(topic),
            "share": round(100 * len(topic) / len(pool), 1) if pool else 0.0,
            "sources": sorted({a["source"] for a in pool}),
            # % of this country's topic articles that mention each name
            "names": {n: round(100 * c / len(topic)) for n, c in names} if topic else {},
            "headlines": topic[:5],
        }

    # Names to compare: the most mentioned overall, by combined share.
    combined = Counter()
    for data in result["countries"].values():
        combined.update(data["names"])
    result["top_names"] = [n for n, _ in combined.most_common(8)]
    return result
