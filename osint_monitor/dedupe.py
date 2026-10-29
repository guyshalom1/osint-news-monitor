"""Remove reprints and group articles about the same story.

Two different things are handled here, because they mean different things:

- Reprints: the same text published under several domains (wire copy picked
  up by regional sites). They inflate counts without adding a new report, so
  they are removed before counting.
- Stories: different outlets reporting the same event in their own words.
  That is real coverage. Articles are grouped into stories so the report can
  show which events were picked up by the most outlets.

Both rely on word overlap between titles (Jaccard similarity), which is
simple, fast and easy to explain. It misses paraphrases that share few words.
"""

import re
from datetime import date

STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "at", "by",
    "with", "from", "as", "is", "are", "was", "were", "be", "been", "it", "its",
    "this", "that", "after", "over", "amid", "says", "said", "say", "new",
    "live", "watch", "update", "more", "us",
}

REPRINT_THRESHOLD = 0.9   # near-identical titles
STORY_THRESHOLD = 0.5     # same event, different wording
MIN_WORDS = 3             # shorter titles ("Live updates") match too easily
WINDOW_DAYS = 2           # only compare articles published close together


def title_words(title):
    """Content words of a title, without a trailing ' - Outlet' tag."""
    title = re.sub(r"\s[-|–]\s[^-|–]{2,40}$", "", title or "")
    words = re.findall(r"[a-z0-9']+", title.lower())
    return frozenset(w for w in words if len(w) > 1 and w not in STOPWORDS)


def similarity(a, b):
    """Jaccard similarity of two word sets: shared words / all words."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _day(article):
    return date.fromisoformat(article["published"][:10])


def _close_in_time(x, y):
    return abs((_day(x) - _day(y)).days) <= WINDOW_DAYS


def remove_reprints(articles, threshold=REPRINT_THRESHOLD):
    """Drop articles whose title is a near-copy of an earlier one.

    The earliest published copy is kept. Returns (kept, removed_count); the
    kept list preserves the input order.
    """
    ordered = sorted(articles, key=lambda a: a["published"])
    kept, words_of = [], {}
    for article in ordered:
        words = title_words(article["title"])
        duplicate = len(words) >= MIN_WORDS and any(
            _close_in_time(article, other)
            and similarity(words, words_of[id(other)]) >= threshold
            for other in kept
        )
        if not duplicate:
            kept.append(article)
            words_of[id(article)] = words
    keep_ids = {id(a) for a in kept}
    result = [a for a in articles if id(a) in keep_ids]
    return result, len(articles) - len(result)


# Section labels that sites put in front of a headline. They are not part of it.
# "Report:" stays, because it tells the reader the claim is not confirmed.
HEADLINE_LABELS = re.compile(
    r"^(?:Exclusive|Opinion|Analysis|Editorial|Live|Watch|Video|Photos)\s*[|:]\s*",
    re.IGNORECASE,
)


def tidy_title(title):
    """Clean a headline for display.

    Some sources (GDELT in particular) return headlines with spaces around
    punctuation, and many sites add a section label in front:
    "U . S . and Israel preparing , sources say" -> "U.S. and Israel preparing, sources say",
    "Exclusive | Iran talks resume" -> "Iran talks resume".
    """
    title = re.sub(r"\s+", " ", title).strip()
    title = HEADLINE_LABELS.sub("", title)
    title = re.sub(r"\s+([,.;:!?%)\]])", r"\1", title)   # "word ," -> "word,"
    title = re.sub(r"([(\[])\s+", r"\1", title)           # "( word" -> "(word"
    title = re.sub(r"(?<=\b[A-Z]\.)\s+(?=[A-Z]\.)", "", title)  # "U. S." -> "U.S."
    return title


def story_clusters(articles, threshold=STORY_THRESHOLD, min_outlets=2):
    """Group articles about the same event, across different outlets.

    Each article joins the first story whose first headline it resembles, or
    starts a new one. Comparing against the first headline only, not every
    member, stops long chains of loosely related titles from merging into one.
    Returns stories covered by at least `min_outlets` outlets, widest first.
    """
    stories = []
    for article in sorted(articles, key=lambda a: a["published"]):
        words = title_words(article["title"])
        if len(words) < MIN_WORDS:
            continue
        for story in stories:
            if (_close_in_time(article, story["seed"])
                    and similarity(words, story["words"]) >= threshold):
                story["articles"].append(article)
                break
        else:
            stories.append({"seed": article, "words": words, "articles": [article]})

    result = []
    for story in stories:
        outlets = sorted({a["source"] for a in story["articles"]})
        if len(outlets) >= min_outlets:
            result.append({
                "headline": tidy_title(story["seed"]["title"]),
                "first": story["seed"]["published"][:10],
                "outlets": outlets,
                "articles": len(story["articles"]),
            })
    result.sort(key=lambda s: (-len(s["outlets"]), -s["articles"], s["first"]))
    return result
