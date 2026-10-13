"""Turn analysis results into a Markdown report and a coverage chart."""

from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to a file, no window needed
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

# Colors. One color for all data: the chart never needs to tell sources
# apart by color, because each source gets its own labeled row instead.
BAR, PARTIAL = "#2a78d6", "#cde2fb"
# Country comparison: two validated colors, always paired with a legend/labels.
COUNTRY_COLORS = {"Israel": "#2a78d6", "US": "#eb6834"}
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


def make_comparison_chart(comp, path):
    """Two panels: how much attention each country gives the topic (left),
    and which names each country mentions alongside it (right)."""
    countries = list(comp["countries"])
    data = comp["countries"]

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(11, 5.2), gridspec_kw={"width_ratios": [1, 1.6]}
    )
    fig.patch.set_facecolor(SURFACE)

    # Left: % of each country's articles that are about the topic.
    shares = [data[c]["share"] for c in countries]
    ax1.barh(countries[::-1], shares[::-1], height=0.5,
             color=[COUNTRY_COLORS[c] for c in countries[::-1]])
    for y, c in enumerate(countries[::-1]):
        d = data[c]
        ax1.text(d["share"] + max(shares) * 0.04, y,
                 f"{d['share']}%  ({d['matching']} of {d['total']})",
                 va="center", fontsize=9.5, color=INK)
    ax1.set_xlim(0, max(shares) * 1.8 or 1)
    ax1.set_title("Share of all articles about the topic", loc="left",
                  fontsize=11, color=INK)
    ax1.grid(axis="x", color=GRID, linewidth=1)
    ax1.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    style(ax1)

    # Right: % of each country's topic articles that mention each name.
    names = comp["top_names"][::-1]
    height = 0.38
    for i, c in enumerate(countries):
        values = [data[c]["names"].get(n, 0) for n in names]
        offsets = [y + (height / 2 if i == 0 else -height / 2) for y in range(len(names))]
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
    note = "Israeli outlets: " + ", ".join(data["Israel"]["sources"]) + ". US outlets: " \
        + ", ".join(data["US"]["sources"]) + "."
    if small < 30:
        note += f"\nSmall samples (fewest: {small} articles): read differences as indicative, not conclusive."
    fig.suptitle(f"Israeli vs US media: {', '.join(comp['keywords'])}",
                 x=0.012, y=0.985, ha="left", va="top", fontsize=14, color=INK)
    fig.text(0.012, 0.915, note, ha="left", va="top", fontsize=9, color=MUTED)
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def comparison_lines(comp):
    """Markdown section comparing the countries."""
    data = comp["countries"]
    lines = ["## Israeli vs US media", ""]
    if not all(d["matching"] for d in data.values()):
        lines += ["Not enough matching articles in both countries to compare.", ""]
        return lines
    lines += ["![Israeli vs US media](comparison.png)", ""]
    lines += ["| | " + " | ".join(data) + " |", "|---|" + "---|" * len(data)]
    lines.append("| Articles about the topic | " + " | ".join(
        f"{d['matching']} of {d['total']} ({d['share']}%)" for d in data.values()) + " |")
    for name in comp["top_names"]:
        lines.append(f"| Mentions {name} | " + " | ".join(
            f"{d['names'].get(name, 0)}%" for d in data.values()) + " |")
    lines.append("")
    for country, d in data.items():
        lines += [f"**Latest {country} headlines**", ""]
        lines += [f"- {a['source']}: [{a['title']}]({a['link']})" for a in d["headlines"]]
        lines.append("")
    lines += [
        "Caveats: Israeli feeds are general news, US feeds are world sections, "
        "so the share of attention is not a like-for-like comparison. Outlets "
        "with longer feeds weigh more within their country.",
        "",
    ]
    return lines


def make_report(result, out_dir, comparison=None):
    """Write report.md and coverage.png into out_dir. Returns the report path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    keywords = ", ".join(result["keywords"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# OSINT Coverage Report: {keywords}",
        "",
        f"Generated {now}. Period: last {result['days']} days. "
        f"Matching articles: {result['total']}.",
        "",
    ]

    if result["total"] == 0:
        lines.append("No matching articles in this period.")
        path = out_dir / "report.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    make_chart(result, out_dir / "coverage.png")
    lines += ["![Coverage per day](coverage.png)", ""]

    lines += ["## Key findings", ""]
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

    lines += ["## Coverage by source", "", "| Source | Articles |", "|---|---|"]
    lines += [f"| {s} | {n} |" for s, n in result["by_source"].items()]
    lines.append("")

    lines += ["## Names and places mentioned alongside the topic", ""]
    lines += ["| Name | Articles |", "|---|---|"]
    lines += [f"| {name} | {n} |" for name, n in result["entities"]]
    lines.append("")

    if comparison:
        make_comparison_chart(comparison, out_dir / "comparison.png") \
            if all(d["matching"] for d in comparison["countries"].values()) else None
        lines += comparison_lines(comparison)

    lines += ["## Latest headlines", ""]
    for a in result["articles"][:10]:
        lines.append(f"- {a['published'][:10]} | {a['source']} | [{a['title']}]({a['link']})")
    lines.append("")

    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
