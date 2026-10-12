"""Turn analysis results into a Markdown report and a coverage chart."""

from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to a file, no window needed
import matplotlib.pyplot as plt


def plural(n):
    return f"{n} article" if n == 1 else f"{n} articles"


def make_chart(result, path):
    """Bar chart of articles per day, with spike days highlighted."""
    days = list(result["by_day"])
    counts = list(result["by_day"].values())
    colors = ["#c0392b" if d in result["spikes"] else "#2c6e9e" for d in days]

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar([d[5:] for d in days], counts, color=colors)
    ax.set_title(f"Coverage of: {', '.join(result['keywords'])}")
    ax.set_ylabel("Articles")
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def make_report(result, out_dir):
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
    peak_day = max(result["by_day"], key=result["by_day"].get)
    lines.append(
        f"- Peak coverage on {peak_day}: {plural(result['by_day'][peak_day])}."
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

    lines += ["## Latest headlines", ""]
    for a in result["articles"][:10]:
        lines.append(f"- {a['published'][:10]} | {a['source']} | [{a['title']}]({a['link']})")
    lines.append("")

    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
