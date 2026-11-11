"""Turn analysis results into a Markdown report and a coverage chart."""

from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import matplotlib

matplotlib.use("Agg")  # draw to a file, no window needed
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from .analyzer import condense_sources
from .assessment import assessment_lines
from .dedupe import tidy_title
from .models import AnalysisResult, Assessment, Comparison

# Colors. One color for all data: the chart never needs to tell sources
# apart by color, because each source gets its own labeled row instead.
BAR, PARTIAL, OTHER = "#2a78d6", "#cde2fb", "#b9b8b0"
# Per-day bars stack three kinds of article. Only the first is the trend series.
HOME, GDELT = "#8a8980", "#d9d8d1"
# Country comparison: three colors that stay apart for most color-blind viewers,
# always paired with a legend and value labels, never color alone.
COUNTRY_COLORS = {"Israel": "#2a78d6", "US": "#eb6834", "Iran": "#009e73"}
INK, MUTED, GRID, SURFACE = "#1f1f1e", "#6b6a64", "#e6e5e0", "#fcfcfb"


# A report with 100+ outlets is unreadable, so only the largest are shown by name.
TOP_SOURCES_TABLE = 15
TOP_SOURCES_CHART = 10



def plural(n: int) -> str:
    return f"{n} article" if n == 1 else f"{n} articles"


def md_cell(text: str) -> str:
    """Text made safe for a Markdown table cell or link label.

    Headlines are untrusted input. A "|" in one would end the cell early and
    shift every column after it, and "[" or "]" would break a link label.
    """
    text = " ".join(str(text).split())   # a newline would end the table row
    for char in ("\\", "|", "[", "]"):
        text = text.replace(char, "\\" + char)
    return text


def md_link(text: str, url: str) -> str:
    """A Markdown link, or plain text when the URL is not a web address."""
    label = md_cell(text)
    if not url.startswith(("http://", "https://")):
        return label
    return f"[{label}]({quote(url, safe=':/?&=#%+@,;~!$*')})"


def trend_series(result: AnalysisResult) -> dict[str, int]:
    """Per-day counts used for peak and trend: the fixed feeds when they
    have data, otherwise every article."""
    panel = result.get("by_day_panel") or {}
    return panel if any(panel.values()) else result["by_day"]


def short_date(day: str) -> str:
    """'2026-10-12' -> '12/10'."""
    return f"{day[8:]}/{day[5:7]}"


def style(ax: Any) -> None:
    """Quiet axes so the data stands out."""
    ax.set_facecolor(SURFACE)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0, labelsize=9)
    ax.set_axisbelow(True)


def make_chart(result: AnalysisResult, path: Path) -> None:
    """Two panels: coverage per day (left) and coverage per source (right).

    Every day in the period is shown. Each bar stacks the fixed feeds (the
    trend series, labeled with its count), the topic country's own press and
    GDELT backfill, so a day that is tall only because the backfill ran is
    visible as such. Days before collection started are drawn pale and
    labeled "partial", so a low count there is not misread as low coverage.
    """
    days = list(result["by_day"])
    series = trend_series(result)
    counts = [series[d] for d in days]
    home = [result.get("by_day_home", {}).get(d, 0) for d in days]
    gdelt = [result["by_day"][d] - series[d] - h for d, h in zip(days, home)]
    partial = set(result["partial_days"])
    top = max(result["by_day"].values()) or 1

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(11, 4.6), gridspec_kw={"width_ratios": [2.2, 1]}
    )
    fig.patch.set_facecolor(SURFACE)

    # Left: articles per day.
    labels = [datetime.fromisoformat(d).strftime("%a\n%d/%m") for d in days]
    colors = [PARTIAL if d in partial else BAR for d in days]
    ax1.bar(labels, counts, width=0.62, color=colors, label="Fixed feeds (trend series)")
    if any(home):
        ax1.bar(labels, home, width=0.62, bottom=counts, color=HOME,
                label=f"{' and '.join(result.get('home_countries', []))} press")
    if any(gdelt):
        ax1.bar(labels, gdelt, width=0.62, bottom=[c + h for c, h in zip(counts, home)],
                color=GDELT, label="GDELT backfill (uneven)")
    if any(home) or any(gdelt):
        ax1.legend(loc="upper left", frameon=False, fontsize=8, ncols=3,
                   handlelength=1, columnspacing=1.2)
    for x, (day, n) in enumerate(zip(days, counts)):
        if day in partial:
            text = f"{n}\npartial"
        elif day in result["spikes"]:
            text = f"{n}\nspike"
        else:
            text = str(n)
        stacked = result["by_day"][day] > n   # the count labels the blue segment only
        if stacked and n >= top * 0.08:
            ax1.text(x, n / 2, str(n), ha="center", va="center", fontsize=9,
                     color="white", fontweight="bold")
            text = text.partition("\n")[2]
        ax1.text(x, result["by_day"][day] + top * 0.03, text, ha="center", va="bottom",
                 fontsize=9, color=MUTED if day in partial else INK,
                 fontweight="bold" if day in result["spikes"] else "normal")
    ax1.set_ylim(0, top * 1.4 + 0.5)
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(axis="y", color=GRID, linewidth=1)
    ax1.set_title("Articles per day", loc="left", fontsize=11, color=INK)
    style(ax1)

    # Right: articles per source, largest on top.
    by_source = condense_sources(result["by_source"], TOP_SOURCES_CHART)
    sources = list(by_source)[::-1]
    values = [by_source[s] for s in sources]
    # The "Other" line adds up many small outlets, so it is drawn in grey, not as one source.
    colors = [OTHER if s.startswith("Other (") else BAR for s in sources]
    ax2.barh(sources, values, height=0.6, color=colors)
    for y, n in enumerate(values):
        ax2.text(n + max(values) * 0.03, y, str(n), va="center", fontsize=9, color=INK)
    ax2.set_xlim(0, max(values) * 1.25)
    ax2.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax2.grid(axis="x", color=GRID, linewidth=1)
    ax2.set_title("Articles per source", loc="left", fontsize=11, color=INK)
    style(ax2)

    note = (f"{plural(result['total'])}, {short_date(days[0])} to {short_date(days[-1])}.")
    if partial:
        note += (f" Collection started {short_date(result['collection_start'])}: "
                 "pale days are incomplete, not low coverage.")
    fig.suptitle(f"News coverage: {', '.join(result['keywords'])}",
                 x=0.012, y=0.985, ha="left", va="top", fontsize=14, color=INK)
    fig.text(0.012, 0.915, note, ha="left", va="top", fontsize=9.5, color=MUTED)

    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def countries_with_data(comp: Comparison) -> list[str]:
    """Countries that have at least one article on the topic."""
    return [c for c, d in comp["countries"].items() if d["matching"]]


def make_comparison_chart(comp: Comparison, path: Path) -> None:
    """Two panels: how much attention each country gives the topic (left),
    and which names each country mentions alongside it (right).

    A home country (Iran, when tracking Iran) covers the topic as domestic news,
    so its bar in the left panel shows the mirror view instead.
    """
    data = comp["countries"]
    countries = countries_with_data(comp)

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(11, 5.2), gridspec_kw={"width_ratios": [1, 1.6]}
    )
    fig.patch.set_facecolor(SURFACE)

    # Left: one bar per country. Foreign press: % of articles about the topic.
    # Home press covers the topic as domestic news, so it shows the mirror
    # instead: % of its articles that mention the other countries.
    def bar_value(c: str) -> float:
        d = data[c]
        return d["mirror"].get("either", 0) if d["home"] and d.get("mirror") else d["share"]

    shares = [bar_value(c) for c in countries]
    top = max(shares, default=1) or 1
    ax1.barh(countries[::-1], shares[::-1], height=0.5,
             color=[COUNTRY_COLORS[c] for c in countries[::-1]])
    for y, c in enumerate(countries[::-1]):
        d = data[c]
        if d["home"] and d.get("mirror"):
            mirror = d["mirror"]
            label = (f"{mirror['either']}% mention US or Israel\n"
                     + ", ".join(f"{t} {mirror[t]}%" for t in mirror if t != "either"))
            ax1.patches[y].set_hatch("//")
            ax1.patches[y].set_edgecolor(SURFACE)
        else:
            label = f"{d['share']}%  ({d['matching']} of {d['total']})"
        ax1.text(bar_value(c) + top * 0.04, y, label,
                 va="center", fontsize=9.5, color=INK)
    ax1.set_xlim(0, top * 2.1)
    ax1.set_title("Attention to the topic\n(Iran: share mentioning US or Israel, hatched)",
                  loc="left", fontsize=11, color=INK)
    ax1.grid(axis="x", color=GRID, linewidth=1)
    ax1.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    style(ax1)

    # Right: % of each country's topic articles that mention each name.
    # With n countries, each name gets n thin bars; the first country is on top.
    names = comp["top_names"][::-1]
    n = len(countries)
    height = 0.8 / n
    for i, c in enumerate(countries):
        values = [data[c]["names"].get(name, 0) for name in names]
        shift = ((n - 1) / 2 - i) * height
        offsets = [y + shift for y in range(len(names))]
        ax2.barh(offsets, values, height=height, color=COUNTRY_COLORS[c],
                 edgecolor=SURFACE, linewidth=1.5, label=c)
        for offset, v in zip(offsets, values):
            ax2.text(v + 1, offset, f"{v}%", va="center", fontsize=8, color=MUTED)
    ax2.set_yticks(range(len(names)), names)
    ax2.set_xlim(0, 100)
    ax2.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax2.grid(axis="x", color=GRID, linewidth=1)
    ax2.set_title("Names mentioned alongside the topic\n(% of that country's topic articles)",
                  loc="left", fontsize=11, color=INK)
    ax2.legend(loc="lower right", frameon=False, fontsize=9)
    style(ax2)

    small = min(data[c]["matching"] for c in countries)
    note = textwrap.fill(
        ". ".join(f"{c} outlets: " + ", ".join(data[c]["sources"]) for c in countries) + ".",
        width=150)
    if any(data[c]["home"] for c in countries):
        note += ("\nHome press covers the topic as domestic news, so its bar shows the "
                 "reverse: how often it mentions the other countries.")
    if small < 30:
        note += (f"\nSmall samples (fewest: {small} articles): "
                 "read differences as indicative, not conclusive.")
    fig.suptitle(f"Media comparison by country: {', '.join(comp['keywords'])}",
                 x=0.012, y=0.985, ha="left", va="top", fontsize=14, color=INK)
    fig.text(0.012, 0.915, note, ha="left", va="top", fontsize=9, color=MUTED)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def comparison_lines(comp: Comparison) -> list[str]:
    """Markdown section comparing the countries."""
    data = {c: comp["countries"][c] for c in countries_with_data(comp)}
    missing = [c for c in comp["countries"] if c not in data]
    lines = ["## Media comparison by country", ""]
    if len(data) < 2:
        lines += ["Not enough matching articles in at least two countries to compare.", ""]
        return lines
    lines += ["![Media comparison by country](comparison.png)", ""]
    lines += ["| | " + " | ".join(data) + " |", "|---|" + "---|" * len(data)]
    lines.append("| Articles about the topic | " + " | ".join(
        f"{d['matching']} of {d['total']} ({d['share']}%)" + (" home press" if d["home"] else "")
        for d in data.values()) + " |")
    if any(d.get("mirror") for d in data.values()):
        for target in ("US", "Israel"):
            cells = [f"{d['mirror'][target]}%" if d.get("mirror") and target in d["mirror"]
                     else "-" for d in data.values()]
            lines.append(f"| Home press: articles mentioning {target} | "
                         + " | ".join(cells) + " |")
    for name in comp["top_names"]:
        lines.append(f"| Mentions {md_cell(name)} | " + " | ".join(
            f"{d['names'].get(name, 0)}%" for d in data.values()) + " |")
    lines.append("")
    for country, d in data.items():
        lines += [f"**Latest {country} headlines**", ""]
        lines += [f"- {a['source']}: {md_link(tidy_title(a['title']), a['link'])}"
                  for a in d["headlines"]]
        lines.append("")
    caveats = [
        "Caveats: Israeli feeds are general news, US feeds are world sections, "
        "so the share of attention is not a like-for-like comparison. Outlets "
        "with longer feeds weigh more within their country.",
    ]
    if any(d["home"] for d in data.values()):
        caveats.append(
            "Home press (here the Iranian outlets) is state or state-affiliated. "
            "It shows the official line, not public opinion, and it covers the "
            "topic as domestic news, so its share of attention is not comparable.")
    if missing:
        caveats.append(f"No matching articles from {', '.join(missing)} in this period.")
    lines += [" ".join(caveats), ""]
    return lines


def key_findings_lines(result: AnalysisResult) -> list[str]:
    """Markdown bullets: peak, top story, spikes, leading source."""
    lines = ["## Key findings", ""]
    series = trend_series(result)
    complete = {d: n for d, n in series.items() if d not in result["partial_days"]}
    if complete:
        peak_day = max(complete, key=lambda d: complete[d])
        fixed = " from the fixed feeds" if series is not result["by_day"] else ""
        lines.append(f"- Peak coverage on {peak_day}: {plural(complete[peak_day])}{fixed}.")
    else:
        lines.append("- Not enough complete days of data yet to identify a peak.")
    if result["partial_days"]:
        lines.append(
            f"- Collection started {result['collection_start']}. Earlier days are "
            "incomplete and are left out of peak and spike detection."
        )
    if result["stories"]:
        top = result["stories"][0]
        lines.append(
            f"- Most widely covered story: \"{top['headline']}\", "
            f"reported by {len(top['outlets'])} outlets."
        )
    if result["spikes"]:
        for day in result["spikes"]:
            srcs = ", ".join(result["sources_per_day"][day])
            lines.append(f"- Spike on {day}, reported by: {srcs}.")
    else:
        lines.append("- No unusual spikes; coverage was steady.")
    top_source, top_n = next(iter(result["by_source"].items()))
    share = round(100 * top_n / result["total"])
    lines.append(f"- {top_source} carried the most coverage ({share}% of articles).")
    lines.append("")
    return lines


def story_lines(result: AnalysisResult) -> list[str]:
    """Markdown table of the stories picked up by the most outlets."""
    lines = []
    if result["stories"]:
        lines += ["## Stories covered by the most outlets", "",
                  "| Story | Outlets | First seen |", "|---|---|---|"]
        lines += [f"| {md_cell(st['headline'])} | {len(st['outlets'])} | {st['first']} |"
                  for st in result["stories"]]
        lines += ["", "Stories are groups of articles with similar headlines. "
                  "Different outlets reporting the same event count once here.", ""]
    return lines


README_START, README_END = "<!-- assessment:start -->", "<!-- assessment:end -->"


def update_readme(readme_path: str | Path, assessment: Assessment, generated: str,
                  result: AnalysisResult | None = None) -> bool:
    """Put the latest assessment between the markers in the README.

    The repo's front page is the README, so the bottom line should be there
    and not only inside reports/latest/report.md. Does nothing if the
    markers are missing, so a hand-edited README never breaks the run.
    """
    path = Path(readme_path)
    text = path.read_text(encoding="utf-8")
    start, end = text.find(README_START), text.find(README_END)
    if start == -1 or end < start:
        return False
    block = ["", f"_Updated {generated}._", ""]
    block += assessment_lines(assessment)
    if result:
        block += key_findings_lines(result) + story_lines(result)
    new = text[:start + len(README_START)] + "\n".join(block) + text[end:]
    path.write_text(new, encoding="utf-8")
    return True


def make_report(result: AnalysisResult, out_dir: str | Path,
                comparison: Comparison | None = None,
                assessment: Assessment | None = None,
                now: datetime | None = None) -> Path:
    """Write report.md and coverage.png into out_dir. Returns the report path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    keywords = ", ".join(result["keywords"])
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# OSINT Coverage Report: {keywords}",
        "",
        f"Generated {stamp}. Period: last {result['days']} days. "
        f"Matching articles: {result['total']}"
        + (f" ({result['reprints_removed']} reprints removed)."
           if result["reprints_removed"] else "."),
        "",
    ]

    if result["total"] == 0:
        lines.append("No matching articles in this period.")
        path = out_dir / "report.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # Bottom line first: the assessment comes before any chart or table.
    if assessment:
        lines += assessment_lines(assessment)

    make_chart(result, out_dir / "coverage.png")
    lines += ["![Coverage per day](coverage.png)", ""]

    lines += key_findings_lines(result)
    lines += story_lines(result)

    lines += ["## Coverage by source", "", "| Source | Articles |", "|---|---|"]
    lines += [f"| {md_cell(s)} | {n} |"
              for s, n in condense_sources(result["by_source"], TOP_SOURCES_TABLE).items()]
    lines.append("")

    lines += ["## Names and places mentioned alongside the topic", ""]
    lines += ["| Name | Articles |", "|---|---|"]
    lines += [f"| {md_cell(name)} | {n} |" for name, n in result["entities"]]
    method = ("spaCy named-entity recognition" if result.get("ner_backend") == "spacy"
              else "a capitalized-phrase heuristic (spaCy not installed)")
    lines += ["", f"Names extracted with {method}.", ""]

    if comparison:
        if len(countries_with_data(comparison)) >= 2:
            make_comparison_chart(comparison, out_dir / "comparison.png")
        lines += comparison_lines(comparison)

    lines += ["## Latest headlines", ""]
    for a in result["articles"][:10]:
        link = md_link(tidy_title(a["title"]), a["link"])
        lines.append(f"- {a['published'][:10]}, {md_cell(a['source'])}: {link}")
    lines.append("")

    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
