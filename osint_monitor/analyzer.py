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

# Capitalized words that start sentences or are too generic to be useful.
STOPWORDS = {
    "The", "A", "An", "In", "On", "At", "For", "And", "But", "Or", "Of", "To",
    "With", "By", "From", "As", "After", "Before", "Over", "Under", "Amid",
    "He", "She", "It", "They", "We", "His", "Her", "Their", "This", "That",
    "These", "Those", "What", "Who", "Why", "How", "When", "Where", "Is",
    "Are", "Was", "Were", "Will", "Would", "Could", "Should", "Says", "Said",
    "New", "Live", "Watch", "Update", "Monday", "Tuesday", "Wednesday",
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


def top_entities(articles, keywords, limit=10):
    """Most frequent names/places mentioned alongside the keywords.

    A simple heuristic: runs of capitalized words. Not as accurate as a full
    NLP model, but fast, transparent and good enough to surface patterns.
    """
    skip = {k.lower() for k in keywords}
    counter = Counter()
    for a in articles:
        found = set()  # count each name once per article
        for name in NAME_PATTERN.findall(f"{a['title']}. {a['summary']}"):
            words = [w for w in name.split() if w not in STOPWORDS]
            name = " ".join(words)
            if len(name) > 2 and name.lower() not in skip:
                found.add(name)
        counter.update(found)
    return counter.most_common(limit)


def analyze(conn, keywords, days=7, now=None):
    """Run the full analysis and return the results as one dict."""
    articles = [a for a in load_articles(conn, days, now) if matches(a, keywords)]
    by_day = daily_counts(articles)

    sources_per_day = defaultdict(set)
    for a in articles:
        sources_per_day[a["published"][:10]].add(a["source"])

    return {
        "keywords": keywords,
        "days": days,
        "total": len(articles),
        "by_day": by_day,
        "by_source": source_counts(articles),
        "spikes": find_spikes(by_day),
        "entities": top_entities(articles, keywords),
        "sources_per_day": {d: sorted(s) for d, s in sorted(sources_per_day.items())},
        "articles": articles,
    }
