"""The daily brief: one self-contained HTML page (and optionally a PDF).

Laid out the way an analytic product is read: bottom line up front, key
judgments with confidence, what changed, then the evidence and the caveats
about the sources. Charts are embedded, so the file can be emailed or
archived as is.

Headlines come from the open web, so nothing from an article is trusted:
the template escapes all text, and links are only rendered for http(s) URLs.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from . import __version__
from .assessment import CONFIDENCE_NOTE
from .dedupe import tidy_title
from .models import AnalysisResult, Assessment, Comparison, SourceHealth
from .report import countries_with_data, trend_series
from .sources import COUNTRY

log = logging.getLogger(__name__)


def safe_url(url: str | None) -> str:
    """The URL if it is a plain web address, else an empty string."""
    return url if url and url.startswith(("http://", "https://")) else ""


def data_uri(path: Path) -> str:
    """A PNG as a data URI, or "" when the chart was not drawn."""
    if not path.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def bluf(result: AnalysisResult, assessment: Assessment) -> list[str]:
    """Bottom line up front: the judgments' claims, the lead new story, and
    the weakest point, in that order."""
    lines = [j["claim"] for j in assessment["judgments"]]
    stories = assessment["new_stories"]
    if stories:
        lead = stories[0]
        lines.append(f"Lead new story, carried by {len(lead['outlets'])} outlets: "
                     f"“{lead['headline']}”.")
    else:
        lines.append("No new story reached two outlets in the last "
                     f"{assessment['hours']} hours.")
    low = [str(i) for i, j in enumerate(assessment["judgments"], 1) if j["confidence"] == "Low"]
    if low:
        noun = "Judgment" if len(low) == 1 else "Judgments"
        verb = "rests" if len(low) == 1 else "rest"
        lines.append(f"{noun} {' and '.join(low)} {verb} on thin evidence (Low confidence).")
    return lines


def source_caveats(result: AnalysisResult,
                   health: Mapping[str, Any] | None = None,
                   backfill: Mapping[str, Any] | None = None) -> list[str]:
    """What a reader should know about the sources before trusting the numbers."""
    caveats = []
    sources: Mapping[str, SourceHealth] = (health or {}).get("sources", {})
    if sources:
        failed = [n for n, s in sources.items() if "error" in s]
        stale = [n for n, s in sources.items() if s.get("stale")]
        saturated = [n for n, s in sources.items() if s.get("saturated")]
        checked = str((health or {}).get("checked", "time unknown"))
        checked = checked.replace("T", " ").replace("+00:00", " UTC")
        line = (f"{len(sources) - len(failed)} of {len(sources)} feeds answered at the "
                f"last collection ({checked}).")
        if failed:
            line += f" Failed: {', '.join(failed)}."
        if stale:
            line += f" No item newer than a week: {', '.join(stale)}."
        caveats.append(line)
        if saturated:
            caveats.append(
                f"Every item was new in: {', '.join(saturated)}. These feeds turned over "
                "completely between runs, so some of their articles were probably missed "
                "and their counts are a floor.")

    home = result.get("home_countries", [])
    if home:
        outlets = sorted(n for n, c in COUNTRY.items() if c in home)
        share = round(100 * sum(result.get("by_day_home", {}).values()) / result["total"])
        caveats.append(
            f"{' and '.join(home)} press ({', '.join(outlets)}) is state or state-affiliated "
            f"and supplied {share}% of matching articles. It shows the official line, not "
            "public opinion. It is kept out of the trend judgments and reported separately.")

    gdelt_days = [d for d, n in result.get("by_day_gdelt", {}).items() if n]
    if gdelt_days:
        caveats.append(
            f"GDELT backfill added articles on {len(gdelt_days)} of {result['days']} days. "
            "It is uneven from day to day and carries headlines only, so it is used for "
            "stories and names and never for trends.")
    failed_days = [d for d, v in (backfill or {}).get("days", {}).items()
                   if isinstance(v, dict)]
    if failed_days:
        caveats.append(f"The last GDELT run did not complete for: {', '.join(failed_days)}.")
    if result["partial_days"]:
        caveats.append(f"Collection started {result['collection_start']}; "
                       f"{len(result['partial_days'])} earlier days are incomplete.")
    if result["reprints_removed"]:
        caveats.append(f"{result['reprints_removed']} reprints of the same headline under "
                       "other domains were removed before counting.")
    caveats += [
        "English-language outlets only. Hebrew, Persian and Arabic coverage is not seen.",
        "Tone is measured with two short word lists. They catch explicit military and "
        "negotiation vocabulary and miss irony, implication and hypotheticals.",
        "Coverage is not events. A rise in articles is a reason to look, not a finding "
        "about what happened.",
    ]
    return caveats


def comparison_table(comp: Comparison | None) -> dict[str, Any] | None:
    """Rows for the country table: attention first, then one row per name."""
    if not comp:
        return None
    countries = countries_with_data(comp)
    if len(countries) < 2:
        return None
    data = comp["countries"]
    rows = [("Articles about the topic", [
        f"{data[c]['matching']} of {data[c]['total']} ({data[c]['share']}%)"
        + (" home press" if data[c]["home"] else "") for c in countries])]
    rows += [(f"Mentions {name}", [f"{data[c]['names'].get(name, 0)}%" for c in countries])
             for name in comp["top_names"]]
    return {"countries": countries, "rows": rows}


def build_context(result: AnalysisResult, comparison: Comparison | None,
                  assessment: Assessment, now: datetime, out_dir: Path,
                  health: Mapping[str, Any] | None = None,
                  backfill: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Everything the template needs, as plain values."""
    series = trend_series(result)
    return {
        "topic": ", ".join(result["keywords"]),
        "as_of": now.strftime("%d %b %Y, %H:%M UTC"),
        "days": result["days"],
        "total": result["total"],
        "panel_total": sum(series.values()),
        "outlets": len(result["by_source"]),
        "scope": assessment.get("scope", ""),
        "hours": assessment["hours"],
        "bluf": bluf(result, assessment),
        "judgments": assessment["judgments"],
        "new_stories": assessment["new_stories"],
        "rising": assessment["rising"],
        "falling": assessment["falling"],
        "stories": result["stories"],
        "entities": result["entities"],
        "ner_backend": result.get("ner_backend", "regex"),
        "headlines": [{**a, "title": tidy_title(a["title"])} for a in result["articles"][:8]],
        "comparison": comparison_table(comparison),
        "coverage_chart": data_uri(out_dir / "coverage.png"),
        "comparison_chart": data_uri(out_dir / "comparison.png"),
        "caveats": source_caveats(result, health, backfill),
        "confidence_note": CONFIDENCE_NOTE,
        "version": __version__,
    }


def render_html(context: Mapping[str, Any]) -> str:
    env = Environment(loader=PackageLoader("osint_monitor"),
                      autoescape=select_autoescape(default=True, default_for_string=True),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["safe_url"] = safe_url
    return env.get_template("brief.html").render(**context)


def write_pdf(html: str, path: Path) -> bool:
    """Write the brief as a PDF. Needs the optional WeasyPrint dependency."""
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as err:   # not installed, or system libraries missing
        log.warning("PDF skipped, WeasyPrint is unavailable: %s", err)
        return False
    HTML(string=html).write_pdf(str(path))
    return True


def make_brief(result: AnalysisResult, comparison: Comparison | None,
               assessment: Assessment, out_dir: str | Path, now: datetime,
               health: Mapping[str, Any] | None = None,
               backfill: Mapping[str, Any] | None = None,
               pdf: bool = False) -> Path:
    """Write brief.html (and brief.pdf) into out_dir. Call after make_report,
    which draws the charts this embeds. Returns the HTML path."""
    out_dir = Path(out_dir)
    html = render_html(build_context(result, comparison, assessment, now, out_dir,
                                     health, backfill))
    path = out_dir / "brief.html"
    path.write_text(html, encoding="utf-8")
    if pdf:
        write_pdf(html, out_dir / "brief.pdf")
    return path
