"""Written assessment: key judgments and what changed in the last 24 hours.

The rest of the tool measures coverage. This module draws conclusions from
it, the way an analyst's summary does: a few judgments, each with a
confidence level and the numbers behind it, plus what is new since yesterday.

Everything here is rule-based and traceable to a count. There is no language
model, so the same data always produces the same assessment.

The important limit: this assesses what the MEDIA is saying, not what is
actually happening. A rise in coverage is a signal worth checking, not proof.
"""

from datetime import timedelta

from .analyzer import matches, top_entities
from .dedupe import STORY_THRESHOLD, similarity, story_clusters, title_words

# Words used for the tone judgment. A story that mentions "strike" or
# "missile" is escalation language; "talks" or "ceasefire" is diplomacy.
# The lists are short on purpose, so the logic is easy to explain and check.
ESCALATION_TERMS = [
    "strike", "strikes", "attack", "attacks", "retaliation", "missile",
    "missiles", "drone", "drones", "war", "troops", "warship", "threat",
    "threatens", "threatened",
]
DIPLOMACY_TERMS = [
    "talks", "negotiations", "negotiate", "diplomacy", "diplomatic",
    "ceasefire", "envoy", "delegation", "delegations", "mediation",
    "mediators", "deal", "agreement",
]

VOLUME_CHANGE = 0.25   # a 25% move in daily volume counts as rising or falling
TONE_SHIFT = 5         # percentage points of difference to call a tone shift
MIN_PRIOR = 5          # fewer articles than this in the earlier window: no trend


def split_windows(articles, now, hours=24):
    """Split articles into the last `hours` and the `hours` before that."""
    recent_from = (now - timedelta(hours=hours)).isoformat()
    prior_from = (now - timedelta(hours=2 * hours)).isoformat()
    recent = [a for a in articles if a["published"] >= recent_from]
    prior = [a for a in articles if prior_from <= a["published"] < recent_from]
    return recent, prior


def confidence(n_articles, n_outlets):
    """How much to trust a judgment, from sample size and source variety.

    High:   at least 60 articles from at least 5 outlets.
    Medium: at least 20 articles from at least 3 outlets.
    Low:    anything smaller. One outlet repeating itself is not a trend.
    """
    if n_articles >= 60 and n_outlets >= 5:
        return "High"
    if n_articles >= 20 and n_outlets >= 3:
        return "Medium"
    return "Low"


def term_share(articles, terms):
    """Percent of articles that use at least one of the terms."""
    if not articles:
        return 0
    hits = sum(1 for a in articles if matches(a, terms))
    return round(100 * hits / len(articles))


def percent_change(now_value, before_value):
    return round(100 * (now_value - before_value) / before_value)


def volume_judgment(recent, prior, incomplete):
    """Is coverage rising, falling or steady compared with the day before?"""
    r, p = len(recent), len(prior)
    outlets = len({a["source"] for a in recent + prior})
    if incomplete or p < MIN_PRIOR:
        reason = ("the earlier period is before collection started"
                  if incomplete else f"only {p} articles in the earlier 24 hours")
        return {
            "claim": "No trend can be called yet.",
            "confidence": "Low",
            "basis": f"{r} articles in the last 24 hours; {reason}.",
        }
    change = (r - p) / p
    if change >= VOLUME_CHANGE:
        word = "Coverage is rising."
    elif change <= -VOLUME_CHANGE:
        word = "Coverage is falling."
    else:
        word = "Coverage is steady."
    return {
        "claim": word,
        "confidence": confidence(r + p, outlets),
        "basis": (f"{r} articles in the last 24 hours vs {p} in the 24 hours "
                  f"before ({percent_change(r, p):+d}%), from {outlets} outlets."),
    }


def tone_judgment(recent, prior):
    """Is the language moving toward escalation or toward diplomacy?"""
    if len(recent) < 10 or len(prior) < 10:
        return {
            "claim": "Too few articles to compare tone.",
            "confidence": "Low",
            "basis": f"{len(recent)} recent and {len(prior)} earlier articles; "
                     "at least 10 in each period are needed.",
        }
    esc_now, esc_before = (term_share(recent, ESCALATION_TERMS),
                           term_share(prior, ESCALATION_TERMS))
    dip_now, dip_before = (term_share(recent, DIPLOMACY_TERMS),
                           term_share(prior, DIPLOMACY_TERMS))
    # Compare the two moves: escalation words up and diplomacy words down is
    # a clear shift, while both rising together is just a busy news day.
    drift = (esc_now - esc_before) - (dip_now - dip_before)
    if drift >= TONE_SHIFT:
        claim = "Language is shifting toward escalation."
    elif drift <= -TONE_SHIFT:
        claim = "Language is shifting toward diplomacy."
    else:
        claim = "The balance between escalation and diplomacy language is unchanged."
    outlets = len({a["source"] for a in recent + prior})
    return {
        "claim": claim,
        "confidence": confidence(len(recent) + len(prior), outlets),
        "basis": (f"Escalation words in {esc_now}% of articles (earlier {esc_before}%), "
                  f"diplomacy words in {dip_now}% (earlier {dip_before}%)."),
    }


def divergence_judgment(comparison):
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

    # The name whose share differs most between countries is the clearest
    # sign that they tell the story differently.
    best = None
    for name in comparison["top_names"]:
        values = {c: d["names"].get(name, 0) for c, d in data.items()}
        hi, lo = max(values, key=values.get), min(values, key=values.get)
        gap = values[hi] - values[lo]
        if best is None or gap > best[0]:
            best = (gap, name, hi, values[hi], lo, values[lo])

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

    if best and best[0] >= 15:
        _, name, hi, hi_v, lo, lo_v = best
        claim = f"Countries frame the topic differently; the clearest gap is \"{name}\"."
        basis.append(f"\"{name}\" appears in {hi_v}% of {hi} topic articles "
                     f"and {lo_v}% of {lo}.")
    else:
        claim = "No large framing gap between countries."

    smallest = min(d["matching"] for d in data.values())
    fewest_outlets = min(len(d["sources"]) for d in data.values())
    return {
        "claim": claim,
        "confidence": confidence(smallest, fewest_outlets),
        "basis": " ".join(basis),
    }


def new_stories(recent, prior, limit=3):
    """Stories reported by 2+ outlets in the last 24 hours that were not
    in the news before: no earlier headline resembles them."""
    earlier = [title_words(a["title"]) for a in prior]
    fresh = []
    for story in story_clusters(recent):
        words = title_words(story["headline"])
        if not any(similarity(words, w) >= STORY_THRESHOLD for w in earlier):
            fresh.append(story)
    return fresh[:limit]


def entity_shifts(recent, prior, keywords, min_count=3, limit=3):
    """Names that gained or lost the most share of coverage since the day before.

    Returns (rising, falling), each a list of (name, earlier %, now %).
    Shares, not counts, so a busier day does not make every name look bigger.
    """
    if not recent or not prior:
        return [], []
    now_counts = dict(top_entities(recent, keywords, limit=100))
    before_counts = dict(top_entities(prior, keywords, limit=100))
    rows = []
    for name in set(now_counts) | set(before_counts):
        now_n, before_n = now_counts.get(name, 0), before_counts.get(name, 0)
        if max(now_n, before_n) < min_count:
            continue
        now_pct = round(100 * now_n / len(recent))
        before_pct = round(100 * before_n / len(prior))
        rows.append((name, before_pct, now_pct))
    rising = sorted((r for r in rows if r[2] - r[1] >= 5), key=lambda r: r[1] - r[2])
    falling = sorted((r for r in rows if r[1] - r[2] >= 5), key=lambda r: r[2] - r[1])
    return rising[:limit], falling[:limit]


def build_assessment(result, comparison, now, hours=24):
    """Compare the last `hours` with the `hours` before, and draw judgments."""
    recent, prior = split_windows(result["articles"], now, hours)

    # Days before collection began are incomplete (see analyzer.analyze), so
    # a comparison that reaches into them would blame missing data on the news.
    prior_days = {(now - timedelta(hours=2 * hours)).date().isoformat(),
                  (now - timedelta(hours=hours)).date().isoformat()}
    incomplete = bool(prior_days & set(result["partial_days"]))

    judgments = [volume_judgment(recent, prior, incomplete),
                 tone_judgment(recent, prior)]
    divergence = divergence_judgment(comparison)
    if divergence:
        judgments.append(divergence)

    rising, falling = entity_shifts(recent, prior, result["keywords"])
    return {
        "hours": hours,
        "recent": len(recent),
        "prior": len(prior),
        "judgments": judgments,
        "new_stories": new_stories(recent, prior),
        "rising": rising,
        "falling": falling,
    }


def assessment_lines(assessment):
    """Markdown for the top of the report: judgments, then what changed."""
    hours = assessment["hours"]
    lines = [
        "## Assessment",
        "",
        f"The last {hours} hours compared with the {hours} hours before. "
        "Rule-based, from coverage counts only. It describes what the media "
        "report, not what is happening on the ground.",
        "",
    ]
    for i, j in enumerate(assessment["judgments"], 1):
        lines.append(f"{i}. **{j['claim']}** Confidence: {j['confidence']}. {j['basis']}")
    lines += [
        "",
        "Confidence: High means 60+ articles from 5+ outlets, Medium means 20+ "
        "from 3+ outlets, Low means less than that.",
        "",
        f"## What changed in the last {hours} hours",
        "",
    ]
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
