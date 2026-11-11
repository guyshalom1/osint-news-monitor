"""Written assessment: key judgments and what changed in the last 24 hours.

The rest of the tool measures coverage. This module draws conclusions from
it, the way an analyst's summary does: a few judgments, each with a
confidence level and the numbers behind it, plus what is new since yesterday.

Everything here is rule-based and traceable to a count. There is no language
model, so the same data always produces the same assessment.

Three rules keep the judgments honest:

1. Compare like with like. Change over time is measured on a fixed set of
   sources (see analyzer.is_panel), never on whatever happened to be collected.
2. Call a change only when it is larger than its sampling noise. With 150
   articles a day, a 5-point move in a percentage is well inside chance.
3. Check that one outlet is not the whole story. Each finding is recomputed
   without the largest outlet; if it does not survive, confidence drops.

The important limit: this assesses what the MEDIA is saying, not what is
actually happening. A rise in coverage is a signal worth checking, not proof.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from statistics import NormalDist
from typing import Any

from .analyzer import home_countries, is_panel
from .dedupe import STORY_THRESHOLD, similarity, story_clusters, title_words
from .entities import top_entities
from .models import (
    AnalysisResult,
    Article,
    Assessment,
    Baseline,
    Comparison,
    Confidence,
    CountryData,
    EntityShift,
    Judgment,
    Story,
)
from .sources import COUNTRY

# Words used for the tone judgment: military action or threat on one side,
# negotiation on the other. The lists are short on purpose, so the logic is
# easy to explain and check, and every word was read in context on real
# articles before it went in. Left out deliberately:
# - "war": once a conflict is called "the Iran war", the word is in every
#   fifth article whatever happens, so it measures the topic, not the tone.
# - "envoy", "delegation", "agreement": in practice mostly ambassadors at
#   cultural events and trade agreements, not negotiation over the conflict.
ESCALATION_TERMS = [
    "strike", "strikes", "airstrike", "airstrikes", "struck", "attack",
    "attacks", "attacked", "retaliation", "retaliate", "retaliates", "missile",
    "missiles", "drone", "drones", "bombing", "bombed", "troops", "warship",
    "warships", "blockade", "threat", "threats", "threatens", "threatened",
]
DIPLOMACY_TERMS = [
    "talks", "negotiations", "negotiate", "negotiating", "diplomacy",
    "diplomatic", "ceasefire", "truce", "mediation", "mediator", "mediators",
    "deal",
]
# A term does not count when it is negated ("rules out a strike", "no talks")
# or, for diplomacy, when the sentence reports its failure ("talks collapse").
NEGATORS = frozenset({
    "no", "not", "never", "without", "unlikely", "rule", "rules", "ruled",
    "reject", "rejects", "rejected", "deny", "denies", "denied", "halt",
    "halts", "halted", "avert", "averts", "averted", "avoid", "avoids",
})
FAILURE_WORDS = frozenset({
    "collapse", "collapses", "collapsed", "fail", "fails", "failed", "stall",
    "stalls", "stalled", "suspended", "cancelled", "canceled", "off",
})
NEGATION_WINDOW = 4    # words before the term that are checked for a negator
FAILURE_WINDOW = 3     # words after a diplomacy term checked for a failure word
WORD = re.compile(r"[a-z][a-z'-]*")

VOLUME_CHANGE = 0.25   # a 25% move in daily volume counts as rising or falling
TONE_SHIFT = 5         # percentage points of difference to call a tone shift
FRAMING_GAP = 15       # percentage points between two countries to call a framing gap
MIN_EXPECTED = 5       # expected mentions per country for a framing gap to be tested
MIN_PRIOR = 5          # fewer articles than this in the earlier window: no trend
MIN_BASELINE_DAYS = 3  # complete days needed to call a "usual level"
Z_95 = NormalDist().inv_cdf(0.975)   # 1.96: two-sided 95%


def split_windows(articles: Sequence[Article], now: datetime,
                  hours: int = 24) -> tuple[list[Article], list[Article]]:
    """Split articles into the last `hours` and the `hours` before that."""
    recent_from = (now - timedelta(hours=hours)).isoformat()
    prior_from = (now - timedelta(hours=2 * hours)).isoformat()
    recent = [a for a in articles if a["published"] >= recent_from]
    prior = [a for a in articles if prior_from <= a["published"] < recent_from]
    return recent, prior


def confidence(n_articles: int, n_outlets: int) -> Confidence:
    """The evidence base behind a judgment: sample size and source variety.

    High:   at least 60 articles from at least 5 outlets.
    Medium: at least 20 articles from at least 3 outlets.
    Low:    anything smaller. One outlet repeating itself is not a trend.
    """
    if n_articles >= 60 and n_outlets >= 5:
        return "High"
    if n_articles >= 20 and n_outlets >= 3:
        return "Medium"
    return "Low"


def downgrade(level: Confidence) -> Confidence:
    """One level down, for a finding that failed a robustness check."""
    return "Medium" if level == "High" else "Low"


def outlets_in(*groups: Iterable[Mapping[str, Any]]) -> int:
    return len({a["source"] for group in groups for a in group})


def without_largest_outlet(
        recent: Sequence[Article], prior: Sequence[Article],
) -> tuple[str, list[Article], list[Article]]:
    """Both windows with the single busiest outlet removed, and its name."""
    counts = Counter(a["source"] for a in [*recent, *prior])
    top = counts.most_common(1)[0][0]
    return (top, [a for a in recent if a["source"] != top],
            [a for a in prior if a["source"] != top])


# --- tone: word lists with negation ---------------------------------------------

def uses_terms(article: Mapping[str, Any], terms: Iterable[str],
               failure_words: frozenset[str] = frozenset()) -> bool:
    """True if the article uses one of the terms as a whole word, not negated.

    "US rules out a strike" does not count as escalation language, and with
    `failure_words`, "talks collapse" does not count as diplomacy.
    """
    wanted = {t.lower() for t in terms}
    words = WORD.findall(f"{article['title']} {article.get('summary') or ''}".lower())
    for i, word in enumerate(words):
        if word not in wanted:
            continue
        if NEGATORS.intersection(words[max(0, i - NEGATION_WINDOW):i]):
            continue
        if failure_words.intersection(words[i + 1:i + 1 + FAILURE_WINDOW]):
            continue
        return True
    return False


def term_hits(articles: Iterable[Mapping[str, Any]], terms: Iterable[str],
              failure_words: frozenset[str] = frozenset()) -> int:
    terms = list(terms)
    return sum(uses_terms(a, terms, failure_words) for a in articles)


def term_share(articles: Sequence[Mapping[str, Any]], terms: Iterable[str],
               failure_words: frozenset[str] = frozenset()) -> int:
    """Percent of articles that use at least one of the terms."""
    if not articles:
        return 0
    return round(100 * term_hits(articles, terms, failure_words) / len(articles))


def tone_score(article: Mapping[str, Any]) -> int:
    """+1 for escalation language, -1 for diplomacy language, 0 for both or neither."""
    return (uses_terms(article, ESCALATION_TERMS)
            - uses_terms(article, DIPLOMACY_TERMS, FAILURE_WORDS))


def tone_drift(recent: Sequence[Article], prior: Sequence[Article]) -> dict[str, float]:
    """How far the balance of language moved, in percentage points, and the
    margin below which the move is sampling noise.

    Each article scores +1, 0 or -1 (see tone_score). The drift is the change
    in the average score, which equals the move in the escalation share minus
    the move in the diplomacy share. The margin is 1.96 standard errors of
    the difference between two means.
    """
    out: dict[str, float] = {}
    means, variance = [], 0.0
    for window, articles in (("now", recent), ("before", prior)):
        n = len(articles)
        scores = [tone_score(a) for a in articles]
        mean = sum(scores) / n
        means.append(mean)
        variance += sum((s - mean) ** 2 for s in scores) / n / n
        out[f"esc_{window}"] = 100 * term_hits(articles, ESCALATION_TERMS) / n
        out[f"dip_{window}"] = 100 * term_hits(articles, DIPLOMACY_TERMS, FAILURE_WORDS) / n
    out["drift"] = 100 * (means[0] - means[1])
    out["margin"] = 100 * Z_95 * math.sqrt(variance)
    return out


def tone_direction(drift: float, margin: float = 0.0) -> str:
    if abs(drift) < TONE_SHIFT or abs(drift) <= margin:
        return "unchanged"
    return "escalation" if drift > 0 else "diplomacy"


def tone_judgment(recent: Sequence[Article], prior: Sequence[Article],
                  home_recent: Sequence[Article] = (),
                  home_prior: Sequence[Article] = ()) -> Judgment:
    """Is the language moving toward escalation or toward diplomacy?"""
    if len(recent) < 10 or len(prior) < 10:
        return {
            "claim": "Too few articles to compare tone.",
            "confidence": "Low",
            "basis": f"{len(recent)} recent and {len(prior)} earlier articles; "
                     "at least 10 in each period are needed.",
        }
    t = tone_drift(recent, prior)
    # Compare the two moves: escalation words up and diplomacy words down is
    # a clear shift, while both rising together is just a busy news day.
    shift = tone_direction(t["drift"], t["margin"])
    claim = {
        "escalation": "Language is shifting toward escalation.",
        "diplomacy": "Language is shifting toward diplomacy.",
        "unchanged": "The balance between escalation and diplomacy language is unchanged.",
    }[shift]
    margin = max(t["margin"], TONE_SHIFT)
    basis = (f"Escalation words in {t['esc_now']:.0f}% of articles (earlier "
             f"{t['esc_before']:.0f}%), diplomacy words in {t['dip_now']:.0f}% "
             f"(earlier {t['dip_before']:.0f}%). Net move: {t['drift']:+.0f} points, "
             f"{'outside' if shift != 'unchanged' else 'inside'} the noise margin of "
             f"{margin:.0f} points for {len(recent)} and {len(prior)} articles.")
    if len(home_recent) >= 10 and len(home_prior) >= 10:
        h = tone_drift(home_recent, home_prior)
        basis += (f" Home press, measured separately: escalation words in "
                  f"{h['esc_now']:.0f}% (earlier {h['esc_before']:.0f}%), diplomacy "
                  f"words in {h['dip_now']:.0f}% (earlier {h['dip_before']:.0f}%).")
    level = confidence(len(recent) + len(prior), outlets_in(recent, prior))
    caveats = []
    if shift == "unchanged" and abs(t["drift"]) >= TONE_SHIFT:
        level = downgrade(level)
        caveats.append("The sample is too small to confirm or rule out a move of this "
                       "size, so confidence is reduced.")
    if shift != "unchanged":
        top, r, p = without_largest_outlet(recent, prior)
        if not r or not p or tone_direction(tone_drift(r, p)["drift"]) != shift:
            level = downgrade(level)
            caveats.append(f"The shift does not hold without {top}, the busiest outlet.")
    judgment: Judgment = {"claim": claim, "confidence": level, "basis": basis}
    if caveats:
        judgment["caveats"] = caveats
    return judgment


# --- volume ---------------------------------------------------------------------

def percent_change(now_value: float, before_value: float) -> int:
    return round(100 * (now_value - before_value) / before_value)


def direction(change: float) -> str:
    """'rising', 'falling' or 'steady' for a relative change."""
    if change >= VOLUME_CHANGE:
        return "rising"
    if change <= -VOLUME_CHANGE:
        return "falling"
    return "steady"


def count_change_is_noise(now_count: int, before_count: int) -> bool:
    """True when two counts differ by less than chance alone would explain.

    Article counts behave like Poisson counts, whose variance equals their
    mean, so the difference of two has a standard error of sqrt(a + b).
    20 against 30 articles is a 50% rise and still inside that noise.
    """
    return abs(now_count - before_count) < Z_95 * math.sqrt(now_count + before_count)


def volume_baseline(result: AnalysisResult, now: datetime, hours: int = 24) -> Baseline | None:
    """The usual daily volume: the average of the complete days before today.

    Left out: the days the last 24 hours touch, the first day of the period
    (it starts mid-day, so its count is cut short) and days before collection
    started. Returns {"mean", "days"}, or None with fewer than three such days.
    """
    by_day = result.get("by_day_panel") or result.get("by_day", {})
    skip = {now.date().isoformat(), (now - timedelta(hours=hours)).date().isoformat()}
    if by_day:
        skip.add(min(by_day))
    skip |= set(result["partial_days"])
    counts = [n for day, n in by_day.items() if day not in skip]
    if len(counts) < MIN_BASELINE_DAYS:
        return None
    return {"mean": sum(counts) / len(counts), "days": len(counts)}


def volume_claim(vs_prior: str, vs_usual: str | None) -> str:
    """One sentence from two comparisons: with the day before, and with the usual level.

    When both point the same way the claim is plain ("Coverage is falling.").
    When they differ, the claim says so: a drop from an unusually busy day
    is not the same as coverage drying up.
    """
    if vs_usual is None or vs_prior == vs_usual:
        return {"rising": "Coverage is rising.", "falling": "Coverage is falling.",
                "steady": "Coverage is steady."}[vs_prior]
    day = {"rising": "rose", "falling": "fell", "steady": "was steady"}[vs_prior]
    level = {"rising": "above", "falling": "below", "steady": "near"}[vs_usual]
    return f"Coverage {day} against the day before and is {level} its usual level."


def volume_judgment(recent: Sequence[Article], prior: Sequence[Article], incomplete: bool,
                    baseline: Baseline | None = None) -> Judgment:
    """Is coverage rising, falling or steady? Against the day before, and
    when there is enough history, against the usual daily level too."""
    r, p = len(recent), len(prior)
    outlets = outlets_in(recent, prior)
    if incomplete or p < MIN_PRIOR:
        reason = ("the earlier period is before collection started"
                  if incomplete else f"only {p} articles in the earlier 24 hours")
        return {
            "claim": "No trend can be called yet.",
            "confidence": "Low",
            "basis": f"{r} articles in the last 24 hours; {reason}.",
        }
    vs_prior = direction((r - p) / p)
    basis = (f"{r} articles in the last 24 hours vs {p} in the 24 hours "
             f"before ({percent_change(r, p):+d}%), from {outlets} outlets.")
    unconfirmed = vs_prior != "steady" and count_change_is_noise(r, p)
    if unconfirmed:
        vs_prior = "steady"
    vs_usual = None
    if baseline and baseline["mean"] > 0:
        vs_usual = direction((r - baseline["mean"]) / baseline["mean"])
        basis += (f" The usual level is {round(baseline['mean'])} a day "
                  f"(average of {baseline['days']} complete days), "
                  f"so the last 24 hours are {percent_change(r, baseline['mean']):+d}% against it.")
    judgment: Judgment = {
        "claim": volume_claim(vs_prior, vs_usual),
        "confidence": confidence(r + p, outlets),
        "basis": basis,
    }
    if unconfirmed:
        judgment["confidence"] = downgrade(judgment["confidence"])
        judgment["caveats"] = ["With counts this small the sample cannot confirm or rule out "
                               "a move of this size, so confidence is reduced."]
    if vs_prior != "steady":
        top, r2, p2 = without_largest_outlet(recent, prior)
        if not p2 or direction((len(r2) - len(p2)) / len(p2)) != vs_prior:
            judgment["confidence"] = downgrade(judgment["confidence"])
            judgment["caveats"] = [f"The change does not hold without {top}, the busiest outlet."]
    return judgment


# --- divergence between countries -------------------------------------------------

def share_gap_z(hits_a: int, n_a: int, hits_b: int, n_b: int) -> float:
    """z-score for the difference between two proportions (pooled)."""
    pooled = (hits_a + hits_b) / (n_a + n_b)
    spread = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    return abs(hits_a / n_a - hits_b / n_b) / spread if spread else 0.0


def name_count(data: CountryData, name: str) -> int:
    """Articles of a country that mention the name."""
    if "name_counts" in data:
        return data["name_counts"].get(name, 0)
    return round(data["names"].get(name, 0) * data["matching"] / 100)


def framing_gaps(comparison: Comparison,
                 data: Mapping[str, CountryData]) -> list[dict[str, Any]]:
    """Names that two countries mention at clearly different rates.

    Every name is tested against every pair of countries, so many tests run
    at once and one of them will look significant by chance. The bar is
    raised accordingly (Bonferroni: 5% divided by the number of tests).
    A country's own name is skipped: Israeli outlets mentioning Israel more
    than US outlets do is geography, not framing.
    """
    countries = list(data)
    pairs = [(a, b) for i, a in enumerate(countries) for b in countries[i + 1:]]
    tests = [(name, a, b) for name in comparison["top_names"] for a, b in pairs
             if name not in (a, b)]
    if not tests:
        return []
    bar = NormalDist().inv_cdf(1 - 0.05 / (2 * len(tests)))
    gaps: list[dict[str, Any]] = []
    for name, a, b in tests:
        hits_a, hits_b = name_count(data[a], name), name_count(data[b], name)
        n_a, n_b = data[a]["matching"], data[b]["matching"]
        share_a, share_b = round(100 * hits_a / n_a), round(100 * hits_b / n_b)
        # The z-test needs about 5 expected mentions on each side to be valid.
        expected = (hits_a + hits_b) / (n_a + n_b) * min(n_a, n_b)
        if (abs(share_a - share_b) < FRAMING_GAP or expected < MIN_EXPECTED
                or share_gap_z(hits_a, n_a, hits_b, n_b) < bar):
            continue
        hi, lo = (a, b) if share_a >= share_b else (b, a)
        gaps.append({
            "name": name, "gap": abs(share_a - share_b),
            "hi": hi, "hi_share": max(share_a, share_b),
            "lo": lo, "lo_share": min(share_a, share_b),
            "home": [c for c in (a, b) if data[c]["home"]],
        })
    # Pairs of foreign press first: they are the like-for-like comparison.
    gaps.sort(key=lambda g: (bool(g["home"]), -g["gap"]))
    return gaps


def divergence_judgment(comparison: Comparison | None) -> Judgment | None:
    """How differently do the countries' media cover the topic?

    Two separate questions: who gives the topic more attention, and who tells
    it differently. The second is the more useful one for an analyst.
    """
    if not comparison:
        return None
    data = {c: d for c, d in comparison["countries"].items() if d["matching"]}
    if len(data) < 2:
        return {
            "claim": "Countries cannot be compared yet.",
            "confidence": "Low",
            "basis": "Fewer than two countries have articles on the topic.",
        }

    # Attention is only compared between countries that are not "home" press.
    shares = {c: d["share"] for c, d in data.items() if not d["home"]}
    basis = []
    if len(shares) >= 2:
        basis.append("; ".join(
            f"{c} outlets give the topic {s}% of their articles"
            for c, s in sorted(shares.items(), key=lambda x: -x[1])) + ".")
    if any(d["home"] for d in data.values()):
        basis.append("Home press is left out of the attention comparison, "
                     "since it covers the topic as domestic news.")

    caveats = []
    gaps = framing_gaps(comparison, data)
    if gaps:
        g = gaps[0]
        claim = f"Countries frame the topic differently; the clearest gap is \"{g['name']}\"."
        basis.append(f"\"{g['name']}\" appears in {g['hi_share']}% of {g['hi']} topic "
                     f"articles and {g['lo_share']}% of {g['lo']}.")
        if g["home"]:
            caveats.append(
                f"{g['home'][0]} is home press: its topic articles include domestic "
                "news, which lowers the share of every foreign name. Read the gap "
                "as indicative.")
    else:
        claim = "No large framing gap between countries."
        basis.append(f"No name differs by {FRAMING_GAP} points or more between two "
                     "countries beyond what sample size explains.")

    smallest = min(d["matching"] for d in data.values())
    fewest_outlets = min(len(d["sources"]) for d in data.values())
    judgment: Judgment = {
        "claim": claim,
        "confidence": confidence(smallest, fewest_outlets),
        "basis": " ".join(basis),
    }
    if caveats:
        judgment["caveats"] = caveats
    return judgment


# --- what changed -----------------------------------------------------------------

def new_stories(recent: Sequence[Article], prior: Sequence[Article],
                limit: int = 3) -> list[Story]:
    """Stories reported by 2+ outlets in the last 24 hours that were not
    in the news before: no earlier headline resembles them."""
    earlier = [title_words(a["title"]) for a in prior]
    fresh = []
    for story in story_clusters(recent):
        words = title_words(story["headline"])
        if not any(similarity(words, w) >= STORY_THRESHOLD for w in earlier):
            fresh.append(story)
    return fresh[:limit]


def entity_shifts(recent: Sequence[Article], prior: Sequence[Article],
                  keywords: Sequence[str], min_count: int = 3,
                  limit: int = 3) -> tuple[list[EntityShift], list[EntityShift]]:
    """Names that gained or lost the most share of coverage since the day before.

    Returns (rising, falling), each a list of (name, earlier %, now %).
    Shares, not counts, so a busier day does not make every name look bigger.
    A move must be at least 5 points and larger than its sampling noise.
    """
    if not recent or not prior:
        return [], []
    now_counts = dict(top_entities(recent, keywords, limit=None))
    before_counts = dict(top_entities(prior, keywords, limit=None))
    rows = []
    for name in set(now_counts) | set(before_counts):
        now_n, before_n = now_counts.get(name, 0), before_counts.get(name, 0)
        if max(now_n, before_n) < min_count:
            continue
        if share_gap_z(now_n, len(recent), before_n, len(prior)) < Z_95:
            continue
        now_pct = round(100 * now_n / len(recent))
        before_pct = round(100 * before_n / len(prior))
        rows.append((name, before_pct, now_pct))
    rising = sorted((r for r in rows if r[2] - r[1] >= 5), key=lambda r: (r[1] - r[2], r[0]))
    falling = sorted((r for r in rows if r[1] - r[2] >= 5), key=lambda r: (r[2] - r[1], r[0]))
    return rising[:limit], falling[:limit]


# --- the full assessment ------------------------------------------------------------

def panel_scope(home: Sequence[str]) -> str:
    """Plain description of the sources the trend judgments are measured on."""
    feeds = sum(1 for country in COUNTRY.values() if country not in home)
    if home:
        return f"the {feeds} fixed RSS feeds outside {' and '.join(home)}"
    return f"the {feeds} fixed RSS feeds"


def build_assessment(result: AnalysisResult, comparison: Comparison | None,
                     now: datetime, hours: int = 24) -> Assessment:
    """Compare the last `hours` with the `hours` before, and draw judgments.

    Volume, tone and name shifts are measured on the panel: the fixed feeds,
    without the topic country's own press. New stories use every article,
    because "did several outlets pick this up" is not a rate.
    """
    home = home_countries(result["keywords"])
    articles = result["articles"]
    panel = [a for a in articles if is_panel(a, home)]
    home_press = [a for a in articles
                  if a.get("origin", "rss") == "rss" and COUNTRY.get(a["source"]) in home]
    recent, prior = split_windows(panel, now, hours)
    home_recent, home_prior = split_windows(home_press, now, hours)
    all_recent, all_prior = split_windows(articles, now, hours)

    # Days before collection began are incomplete (see analyzer.analyze), so
    # a comparison that reaches into them would blame missing data on the news.
    prior_days = {(now - timedelta(hours=2 * hours)).date().isoformat(),
                  (now - timedelta(hours=hours)).date().isoformat()}
    incomplete = bool(prior_days & set(result["partial_days"]))

    baseline = volume_baseline(result, now, hours)
    judgments = [volume_judgment(recent, prior, incomplete, baseline),
                 tone_judgment(recent, prior, home_recent, home_prior)]
    divergence = divergence_judgment(comparison)
    if divergence:
        judgments.append(divergence)

    rising, falling = entity_shifts(recent, prior, result["keywords"])
    return {
        "hours": hours,
        "recent": len(recent),
        "prior": len(prior),
        "scope": panel_scope(home),
        "judgments": judgments,
        "new_stories": new_stories(all_recent, all_prior),
        "rising": rising,
        "falling": falling,
    }


CONFIDENCE_NOTE = (
    "Confidence starts from the evidence base (High: 60+ articles from 5+ outlets; "
    "Medium: 20+ from 3+; otherwise Low). It drops one level when a finding does "
    "not hold without the busiest outlet, or when a move was measured that the "
    "sample is too small to confirm. A change is only called when it is larger "
    "than its sampling noise.")


def assessment_lines(assessment: Assessment) -> list[str]:
    """Markdown for the top of the report: judgments, then what changed."""
    hours = assessment["hours"]
    scope = assessment.get("scope")
    lines = [
        "## Assessment",
        "",
        f"The last {hours} hours compared with the {hours} hours before"
        + (f", measured on {scope}" if scope else "") + ". "
        "Rule-based, from coverage counts only. It describes what the media "
        "report, not what is happening on the ground.",
        "",
    ]
    for i, j in enumerate(assessment["judgments"], 1):
        line = f"{i}. **{j['claim']}** Confidence: {j['confidence']}. {j['basis']}"
        if j.get("caveats"):
            line += " " + " ".join(j["caveats"])
        lines.append(line)
    lines += ["", CONFIDENCE_NOTE, "", f"## What changed in the last {hours} hours", ""]
    stories = assessment["new_stories"]
    if stories:
        for s in stories:
            lines.append(f"- New story, {len(s['outlets'])} outlets: {s['headline']}")
    else:
        lines.append("- No new story reached 2 or more outlets.")
    if assessment["rising"]:
        names = ", ".join(f"{n} ({b}% to {a}%)" for n, b, a in assessment["rising"])
        lines.append(f"- Mentioned more: {names}.")
    if assessment["falling"]:
        names = ", ".join(f"{n} ({b}% to {a}%)" for n, b, a in assessment["falling"])
        lines.append(f"- Mentioned less: {names}.")
    if not (assessment["rising"] or assessment["falling"]):
        lines.append("- No name moved by 5 percentage points or more.")
    lines.append("")
    return lines
