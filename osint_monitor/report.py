"""Turn analysis results into a Markdown report and a coverage chart."""

import textwrap
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to a file, no window needed
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from .assessment import assessment_lines

# Colors. One color for all data: the chart never needs to tell sources
# apart by color, because each source gets its own labeled row instead.
BAR, PARTIAL = "#2a78d6", "#cde2fb"
# Country comparison: three colors that stay apart for most color-blind viewers,
# always paired with a legend and value labels, never color alone.
COUNTRY_COLORS = {"Israel": "#2a78d6", "US": "#eb6834", "Iran": "#009e73"}
INK, MUTED, GRID, SURFACE = "#1f1f1e", "#6b6a64", "#e6e5e0", "#fcfcfb"


def plural(n):
    return f"{n} article" if n == 1 else f"{n} articles"


def short_date(day):
    """'2026-10-12' -> '12/10'."""
    return f"{day[8:]}/{day[5:7]}"


def style(ax):
    """Quiet axes so the data stands out."""
    ax.set_facecolor(SURFACE)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0, labelsize=9)
    ax.set_axisbelow(True)


def make_chart(result, path):
    """Two panels: coverage per day (left) and coverage per source (right).

    Every day in the period is shown. Days before collection started are
    drawn pale and labeled "partial", so a low count there is not misread
    as low coverage.
    """
    days = list(result["by_day"])
    counts = list(result["by_day"].values())
    partial = set(result["partial_days"])
    top = max(counts) or 1

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(11, 4.6), gridspec_kw={"width_ratios": [2.2, 1]}
    )
    fig.patch.set_facecolor(SURFACE)

    # Left: articles per day.
    labels = [datetime.fromisoformat(d).strftime("%a\n%d/%m") for d in days]
    colors = [PARTIAL if d in partial else BAR for d in days]
    ax1.bar(labels, counts, width=0.62, color=colors)
    for x, (day, n) in enumerate(zip(days, counts)):
        if day in partial:
            text = f"{n}\npartial"
        elif day in result["spikes"]:
            text = f"{n}\nspike"
        else:
            text = str(n)
        ax1.text(x, n + top * 0.03, text, ha="center", va="bottom", fontsize=9,
                 color=MUTED if day in partial else INK,
                 fontweight="bold" if day in result["spikes"] else "normal")
    ax1.set_ylim(0, top * 1.3 + 0.5)
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(axis="y", color=GRID, linewidth=1)
    ax1.set_title("Articles per day", loc="left", fontsize=11, color=INK)
    style(ax1)

    # Right: articles per source, largest on top.
    sources = list(result["by_source"])[::-1]
    values = [result["by_source"][s] for s in sources]
    ax2.barh(sources, values, height=0.6, color=BAR)
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


def countries_with_data(comp):
    """Countries that have at least one article on the topic."""
    return [c for c, d in comp["countries"].items() if d["matching"]]


def make_comparison_chart(comp, path):
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
    def bar_value(c):
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
        for y, v in zip(offsets, values):
            ax2.text(v + 1, y, f"{v}%", va="center", fontsize=8, color=MUTED)
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


def comparison_lines(comp):
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
        lines.append(f"| Mentions {name} | " + " | ".join(
            f"{d['names'].get(name, 0)}%" for d in data.values()) + " |")
    lines.append("")
    for country, d in data.items():
        lines += [f"**Latest {country} headlines**", ""]
        lines += [f"- {a['source']}: [{a['title']}]({a['link']})" for a in d["headlines"]]
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


def key_findings_lines(result):
    """Markdown bullets: peak, top story, spikes, leading source."""
    lines = ["## Key findings", ""]
    complete = {d: n for d, n in result["by_day"].items()
                if d not in result["partial_days"]}
    if complete:
        peak_day = max(complete, key=complete.get)
        lines.append(
            f"- Peak coverage on {peak_day}: {plural(result['by_day'][peak_day])}."
        )
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


def story_lines(result):
    """Markdown table of the stories picked up by the most outlets."""
    lines = []
    if result["stories"]:
        lines += ["## Stories covered by the most outlets", "",
                  "| Story | Outlets | First seen |", "|---|---|---|"]
        lines += [f"| {st['headline']} | {len(st['outlets'])} | {st['first']} |"
                  for st in result["stories"]]
        lines += ["", "Stories are groups of articles with similar headlines. "
                  "Different outlets reporting the same event count once here.", ""]
    return lines


README_START, README_END = "<!-- assessment:start -->", "<!-- assessment:end -->"


def update_readme(readme_path, assessment, generated, result=None):
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


def make_report(result, out_dir, comparison=None, assessment=None):
    """Write report.md and coverage.png into out_dir. Returns the report path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    keywords = ", ".join(result["keywords"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# OSINT Coverage Report: {keywords}",
        "",
        f"Generated {now}. Period: last {result['days']} days. "
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
    lines += [f"| {s} | {n} |" for s, n in result["by_source"].items()]
    lines.append("")

    lines += ["## Names and places mentioned alongside the topic", ""]
    lines += ["| Name | Articles |", "|---|---|"]
    lines += [f"| {name} | {n} |" for name, n in result["entities"]]
    lines.append("")

    if comparison:
        if len(countries_with_data(comparison)) >= 2:
            make_comparison_chart(comparison, out_dir / "comparison.png")
        lines += comparison_lines(comparison)

    lines += ["## Latest headlines", ""]
    for a in result["articles"][:10]:
        lines.append(f"- {a['published'][:10]} | {a['source']} | [{a['title']}]({a['link']})")
    lines.append("")

    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
