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

from .dedupe import remove_reprints, story_clusters
from .gdelt import query_key
from .sources import COUNTRY, OUTLET_NAMES

# Capitalized words that start sentences or are too generic to be useful.
STOPWORDS = {
    "The", "A", "An", "In", "On", "At", "For", "And", "But", "Or", "Of", "To",
    "With", "By", "From", "As", "After", "Before", "Over", "Under", "Amid",
    "He", "She", "It", "They", "We", "His", "Her", "Their", "This", "That",
    "These", "Those", "What", "Who", "Why", "How", "When", "Where", "Is",
    "Are", "Was", "Were", "Will", "Would", "Could", "Should", "Says", "Said",
    "New", "Live", "Watch", "Update", "Continue", "Read", "More", "Monday", "Tuesday", "Wednesday",
    "Report", "Reports", "Analysis", "Opinion", "Exclusive",
    "Thursday", "Friday", "Saturday", "Sunday", "January", "February",
    "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
    "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct",
    "Nov", "Dec", "Today", "Day", "Two", "Three", "Get", "According",
    "Ministry", "Department", "News", "Breaking", "Video", "Photos", "Police",
}

# Job titles. They are not part of a person's name, so "Prime Minister Benjamin
# Netanyahu" and "Netanyahu" must count as the same name.
TITLES = {
    "Prime", "Minister", "President", "Vice", "Foreign", "Defense", "Defence",
    "Secretary", "Senator", "Sen", "Rep", "Representative", "General", "Gen",
    "Supreme", "Leader", "Ayatollah", "King", "Prince", "Crown", "Mr", "Mrs",
    "Dr", "Chairman", "Ambassador", "Speaker", "Premier", "Chancellor",
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
        if word in STOPWORDS or word in TITLES or lower in skip:
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
    merge_full_names(counter)
    return counter.most_common(limit)


def merge_full_names(counter):
    """Merge a longer name into its last word when that word is also counted.

    "Benjamin Netanyahu" -> "Netanyahu", "Donald Trump" -> "Trump". Only the
    last word is used, so "Saudi Arabia" stays as is unless "Arabia" alone is
    also a counted name. Changes the counter in place.
    """
    for name in sorted(counter, key=lambda n: -len(n.split())):
        words = name.split()
        if len(words) >= 2 and words[-1] in counter and name in counter:
            counter[words[-1]] += counter.pop(name)


def analyze(conn, keywords, days=7, now=None):
    """Run the full analysis and return the results as one dict."""
    now = now or datetime.now(timezone.utc)
    matched = [a for a in load_articles(conn, days, now) if matches(a, keywords)]
    # Wire copy republished under other domains would inflate every count.
    articles, reprints_removed = remove_reprints(matched)
    by_day = fill_days(daily_counts(articles), days, now)

    # For each day, how many articles each source published: {day: {source: n}}
    by_day_source = defaultdict(Counter)
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
        "keywords": keywords,
        "collection_start": start,
        "partial_days": partial,
        "days": days,
        "total": len(articles),
        "reprints_removed": reprints_removed,
        "stories": story_clusters(articles)[:8],
        "by_day": by_day,
        "by_source": source_counts(articles),
        "spikes": find_spikes({d: n for d, n in by_day.items() if d not in partial}),
        "entities": top_entities(articles, keywords),
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


def mirror_share(pool, targets):
    """% of a country's articles that mention each target country, and either."""
    if not pool:
        return {}
    texts = [f"{a['title']}. {a['summary']}" for a in pool]
    out = {t: round(100 * sum(bool(MIRROR_TERMS[t].search(x)) for x in texts) / len(texts))
           for t in targets}
    either = sum(any(MIRROR_TERMS[t].search(x) for t in targets) for x in texts)
    out["either"] = round(100 * either / len(texts))
    return out


def compare_countries(conn, keywords, days=7, now=None,
                      countries=("Israel", "US", "Iran")):
    """Compare how media in different countries cover the same topic.

    Counts differ a lot between countries (more feeds, longer feeds), so the
    comparison uses shares instead of raw numbers:
    - attention: % of a country's articles that are about the topic
    - framing:   % of a country's topic articles that mention each name

    A country named in the keywords (Iran, when tracking Iran) is the "home"
    press for the topic. It covers the topic as domestic news, so its share of
    attention is not comparable with the others. Its framing still is, and its
    "mirror" shows the opposite view: how often it mentions the other countries.
    """
    all_articles = load_articles(conn, days, now)
    result = {"keywords": keywords, "countries": {}}
    keyword_set = {k.lower() for k in keywords}

    for country in countries:
        pool = [a for a in all_articles if COUNTRY.get(a["source"]) == country]
        topic = [a for a in pool if matches(a, keywords)]
        names = top_entities(topic, keywords, limit=50)
        home = country.lower() in keyword_set
        targets = [c for c in countries if c != country and c in MIRROR_TERMS]
        result["countries"][country] = {
            "home": home,
            "mirror": mirror_share(pool, targets) if home else {},
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
