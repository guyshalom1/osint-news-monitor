"""Names and places mentioned in articles.

Two extractors find candidate names in a text:

- spaCy NER (`en_core_web_sm`): a trained model that labels people, places,
  organizations and nationalities. Used when spaCy and its model are installed.
- A regular expression for runs of capitalized words. No dependencies, so it
  is the fallback, and the baseline the model is tested against.

Both feed the same cleanup (titles, possessives, aliases, the topic's own
keywords), so "Prime Minister Benjamin Netanyahu", "Netanyahu's" and
"Netanyahu" count as one name whichever extractor found them.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from .collector import INVISIBLE
from .sources import OUTLET_NAMES

log = logging.getLogger(__name__)

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
    "Strait",
}

# Job titles. They are not part of a person's name, so "Prime Minister Benjamin
# Netanyahu" and "Netanyahu" must count as the same name.
TITLES = {
    "Prime", "Minister", "President", "Vice", "Foreign", "Defense", "Defence",
    "Secretary", "Senator", "Sen", "Rep", "Representative", "General", "Gen",
    "Supreme", "Leader", "Ayatollah", "King", "Prince", "Crown", "Mr", "Mrs",
    "Dr", "Chairman", "Ambassador", "Speaker", "Premier", "Chancellor",
}

# Different forms of the same name, counted as one. The merge happens per
# article, so an article that says both "Israel" and "Israeli" counts once.
ALIASES = {
    "Israeli": "Israel", "Russian": "Russia", "Saudi": "Saudi Arabia",
    "Saudis": "Saudi Arabia", "Lebanese": "Lebanon", "Syrian": "Syria",
    "Iraqi": "Iraq", "Yemeni": "Yemen",
    "Ukrainian": "Ukraine", "Chinese": "China", "British": "UK", "French": "France",
    "Qatari": "Qatar", "Turkish": "Turkey", "Egyptian": "Egypt", "German": "Germany",
    "Israelis": "Israel", "Americans": "US", "American": "US", "America": "US",
    "United States": "US", "U.S": "US", "U.S.": "US", "USA": "US",
    "United Kingdom": "UK", "Britain": "UK", "U.K.": "UK", "U.K": "UK",
    "United Nations": "UN", "U.N.": "UN", "U.N": "UN",
    "Islamic Republic": "Iran", "Iranians": "Iran",
    "Islamic Revolutionary Guard Corps": "IRGC", "Revolutionary Guards": "IRGC",
    "Revolutionary Guard": "IRGC", "Strait of Hormuz": "Hormuz",
}

# One or more capitalized words in a row, e.g. "Security Council", "Gaza".
NAME_PATTERN = re.compile(r"\b[A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+)*\b")

# News agencies open many articles with a dateline: "TEHRAN, Oct. 29 (MNA) -",
# "Tehran, IRNA -" or "LONDON -". It says where and who filed the story, not
# what it is about, so it is removed before names are counted. Without this,
# the agency tag "MNA" tops the name list and looks like a real subject.
AGENCIES = "MNA|IRNA|ISNA|TNA|AP|AFP|Reuters|WAFA"
DATE_PART = r"(?:[A-Z][a-z]{2,8}\.?\s*\d{1,2}\s*)"
DATELINE = re.compile(
    # "City, [date] AGENCY"
    rf"^\s*(?:[A-Za-z .]{{2,30}},\s*{DATE_PART}?\(?(?:{AGENCIES})\)?\s*"
    # "CITY [, date] [(AGENCY)]"
    rf"|[A-Z]{{3,}}(?: [A-Z]{{3,}})?(?:,\s*{DATE_PART})?\s*(?:\([A-Za-z]{{2,8}}\)\s*)?)"
    r"(?:[–—-]|--)\s*"
)

# spaCy labels worth counting: people, countries and cities, organizations,
# nationalities and groups, other locations, facilities, named events.
SPACY_LABELS = {"PERSON", "GPE", "ORG", "NORP", "LOC", "FAC", "EVENT"}
SPACY_MODEL = "en_core_web_sm"

# A candidate name and its type. The regex cannot tell types apart, so its
# label is "".
Candidate = tuple[str, str]
Extractor = Callable[[Sequence[str]], list[list[Candidate]]]


def strip_dateline(text: str) -> str:
    """Remove a leading agency dateline, e.g. "TEHRAN, Oct. 29 (MNA) - Iran said..."."""
    return DATELINE.sub("", text, count=1)


# --- the two extractors: texts in, candidate names per text out -------------

def regex_names(texts: Sequence[str]) -> list[list[Candidate]]:
    """Runs of capitalized words. Fast and transparent, but blind to context."""
    return [[(name, "") for name in NAME_PATTERN.findall(text)] for text in texts]


_nlp: Any = None
_spacy_cache: dict[str, list[Candidate]] = {}


def spacy_available() -> bool:
    """True when spaCy and its English model can be loaded."""
    global _nlp
    if _nlp is not None:
        return True
    try:
        import spacy
        _nlp = spacy.load(SPACY_MODEL, disable=["lemmatizer"])
    except (ImportError, OSError) as err:   # not installed, or model not downloaded
        log.debug("spaCy unavailable: %s", err)
        return False
    return True


def spacy_names(texts: Sequence[str]) -> list[list[Candidate]]:
    """Entities found by the spaCy model. Results are cached per text, since
    the report looks at the same articles several times."""
    if not spacy_available():
        raise RuntimeError(
            f"spaCy or its model is missing. Install with: pip install "
            f"'osint-news-monitor[nlp]' && python -m spacy download {SPACY_MODEL}")
    new = [t for t in dict.fromkeys(texts) if t not in _spacy_cache]
    for text, doc in zip(new, _nlp.pipe(new, batch_size=64)):
        _spacy_cache[text] = [(e.text, e.label_) for e in doc.ents if e.label_ in SPACY_LABELS]
    return [_spacy_cache[t] for t in texts]


EXTRACTORS: dict[str, Extractor] = {"regex": regex_names, "spacy": spacy_names}
_backend = "regex"


def use_backend(name: str) -> str:
    """Choose the extractor: "spacy", "regex", or "auto" (spaCy if installed).

    Returns the backend actually in use, so the report can say which it was.
    """
    global _backend
    if name == "auto":
        name = "spacy" if spacy_available() else "regex"
    if name == "spacy" and not spacy_available():
        raise RuntimeError(f"spaCy backend requested but spaCy or {SPACY_MODEL} is not installed")
    if name not in EXTRACTORS:
        raise ValueError(f"unknown entity backend: {name}")
    _backend = name
    return name


def backend() -> str:
    return _backend


# --- shared cleanup -----------------------------------------------------------

EDGE_WORDS = {"the", "of", "and", "in", "a", "province"}


def clean_name(name: str, skip: set[str]) -> str:
    """Normalize one candidate name, or return "" to drop it.

    "Riyadh's" -> "Riyadh", "Iran's Houthi" -> "Houthi" (keyword removed),
    "Iran-backed Houthis" -> "Houthis", "the Strait of Hormuz" -> "Strait of Hormuz".
    """
    words = []
    for word in name.split():
        word = re.sub(r"['’]s$", "", word).strip("\"'‘’“”,;:()")
        lower = word.lower()
        if word in STOPWORDS or word.rstrip(".") in TITLES or lower in skip:
            continue
        if any(lower.startswith(k + "-") for k in skip):  # "Iran-backed"
            continue
        words.append(word)
    while words and words[0].lower() in EDGE_WORDS:
        words.pop(0)
    while words and words[-1].lower() in EDGE_WORDS:
        words.pop()
    return " ".join(words)


def article_text(article: Mapping[str, Any]) -> str:
    text = f"{article['title']}. {strip_dateline(article.get('summary') or '')}"
    return INVISIBLE.sub("", text)   # rows stored before the collector removed them


def names_per_article(articles: Sequence[Mapping[str, Any]], keywords: Iterable[str],
                      backend_name: str | None = None) -> list[dict[str, str]]:
    """The cleaned names in each article, as {name: type}. A dict, so each
    name counts once per article however often it is repeated."""
    skip = {k.lower() for k in keywords}
    skip |= {name.lower() for name in OUTLET_NAMES}
    extract = EXTRACTORS[backend_name or _backend]
    result = []
    for candidates in extract([article_text(a) for a in articles]):
        found: dict[str, str] = {}
        for raw, label in candidates:
            name = clean_name(raw, skip)
            name = ALIASES.get(name, name)
            if len(name) >= 2 and name.lower() not in skip:
                found.setdefault(name, label)
        result.append(found)
    return result


def canonical_names(labels: Mapping[str, set[str]]) -> dict[str, str]:
    """Map each variant to the form it is counted under.

    `labels` holds every name seen with the types it was given. Plurals go to
    the singular when both appear ("Houthis" -> "Houthi"). A person's full
    name goes to the surname when the surname is also used alone ("Benjamin
    Netanyahu" -> "Netanyahu"). With spaCy only names typed PERSON are merged
    this way, so "White House" never lands on "House"; the regex has no types
    and merges any longer name whose last word also stands alone.
    """
    mapping = {}
    for name, types in labels.items():
        target = name
        if target.endswith("s") and target[:-1] in labels:
            target = target[:-1]
        words = target.split()
        if len(words) >= 2 and words[-1] in labels and types <= {"PERSON", ""}:
            target = words[-1]
        if target != name:
            mapping[name] = target
    return mapping


def top_entities(articles: Sequence[Mapping[str, Any]], keywords: Iterable[str],
                 limit: int | None = 10) -> list[tuple[str, int]]:
    """Most frequent names and places mentioned alongside the keywords.

    Returns (name, number of articles), most frequent first. Variants are
    merged inside each article before counting, so an article that says both
    "Benjamin Netanyahu" and "Netanyahu" counts once. `limit=None` returns
    every name.
    """
    per_article = names_per_article(articles, keywords)
    labels: dict[str, set[str]] = {}
    for found in per_article:
        for name, label in found.items():
            labels.setdefault(name, set()).add(label)
    mapping = canonical_names(labels)
    counter: Counter[str] = Counter()
    for found in per_article:
        counter.update({mapping.get(name, name) for name in found})
    return counter.most_common(limit)
