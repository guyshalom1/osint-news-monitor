# OSINT News Monitor

[![Tests](https://github.com/guyshalom1/osint-news-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/guyshalom1/osint-news-monitor/actions/workflows/tests.yml)
[![Collect and report](https://github.com/guyshalom1/osint-news-monitor/actions/workflows/monitor.yml/badge.svg)](https://github.com/guyshalom1/osint-news-monitor/actions/workflows/monitor.yml)

A Python tool that tracks how a topic is covered across open news sources. It collects articles from public RSS feeds, stores them locally, and produces an analyst-style report: coverage volume over time, unusual spikes, which outlets lead the coverage, and which names and places appear alongside the topic.

Built as a personal project to automate a task I do manually as a delegate intern at Israel's Permanent Mission to the UN: following how an issue develops across sources before a meeting.

## Latest assessment

<!-- assessment:start -->
_Updated 2026-10-31 05:43 UTC._

## Assessment

The last 24 hours compared with the 24 hours before. Rule-based, from coverage counts only. It describes what the media report, not what is happening on the ground.

1. **Coverage rose against the day before and is near its usual level.** Confidence: High. 86 articles in the last 24 hours vs 55 in the 24 hours before (+56%), from 11 outlets. The usual level is 104 a day (average of 4 complete days), so the last 24 hours are -18% against it.
2. **Language is shifting toward diplomacy.** Confidence: High. Escalation words in 31% of articles (earlier 49%), diplomacy words in 16% (earlier 22%).
3. **Countries frame the topic differently; the clearest gap is "Netanyahu".** Confidence: Medium. Israel outlets give the topic 10.0% of their articles; US outlets give the topic 4.8% of their articles. Home press is left out of the attention comparison, since it covers the topic as domestic news. "Netanyahu" appears in 39% of Israel topic articles and 2% of Iran.

Confidence: High means 60+ articles from 5+ outlets, Medium means 20+ from 3+ outlets, Low means less than that.

## What changed in the last 24 hours

- New story, 2 outlets: Iran foreign minister offers condolences to Spain over deadly train crash
- New story, 2 outlets: Qatari delegation arrives in Tehran for talks
- New story, 2 outlets: IRGC Navy: Two violating oil tankers stopped in south of Strait of Hormuz
- Mentioned more: Netanyahu (0% to 6%), Araghchi (0% to 5%).
- Mentioned less: Vance (16% to 2%), Republic (11% to 0%), US (31% to 20%).

## Key findings

- Peak coverage on 2026-10-26: 132 articles.
- Most widely covered story: "Iran President to attend GECF summit in Moscow", reported by 3 outlets.
- No unusual spikes; coverage was steady.
- Mehr News carried the most coverage (19% of articles).

## Stories covered by the most outlets

| Story | Outlets | First seen |
|---|---|---|
| Iran President to attend GECF summit in Moscow | 3 | 2026-10-24 |
| Iran Pezeshkian blames US for interim deal failure, urges new try | 3 | 2026-10-24 |
| Abbas Araghchi says resumption of war would not change Iran policies | 3 | 2026-10-25 |
| Iran says won’t allow US warships to get close as Trump ponders new attacks | 2 | 2026-10-24 |
| Report: US tells Gulf allies to prepare for Iran strikes after midterms | 2 | 2026-10-28 |
| Is Iran planning attacks on Americans; why is the US on alert? | 2 | 2026-10-24 |
| Iran remains open to talks with US under Pakistan-brokered deal, envoy says | 2 | 2026-10-24 |
| Obama’s Ohio, Michigan speeches: Key takeaways on Trump, Iran war, midterms | 2 | 2026-10-25 |

Stories are groups of articles with similar headlines. Different outlets reporting the same event count once here.
<!-- assessment:end -->

## Live report

A scheduled GitHub Actions workflow collects new articles every 6 hours and rebuilds the report on real data. Latest report: [reports/latest/report.md](reports/latest/report.md)

![Coverage per day](reports/latest/coverage.png)

### Israeli vs US vs Iranian media

The same topic, compared between 7 Israeli, 5 US and 3 Iranian state or state-affiliated outlets: how much attention each country's media gives it, and which names and places each puts alongside it. Shares are used instead of raw counts, since the feeds differ in size. Iranian outlets cover Iran as home news, so they are left out of the attention comparison and only compared on framing.

![Israeli vs US vs Iranian media](reports/latest/comparison.png)

## What it does

1. **Collect** articles from 19 English-language RSS feeds, each tagged by country, into a SQLite database. Duplicates are skipped, so it can run repeatedly and build a history.
   - Israel: Haaretz, Jerusalem Post, Israel Hayom, Israel National News, JNS, Ynetnews, Globes
   - US: New York Times, NPR, Fox News, CBS News, ABC News
   - Iran (state-affiliated, so they show the official line): IRNA, Mehr News, Tehran Times
   - International: BBC, Al Jazeera, The Guardian, UN News
   - Every run records source health in `data/source_status.json`, including feeds that respond but have stopped updating.
2. **Backfill** past days for a topic from [GDELT](https://www.gdeltproject.org/), which indexes thousands of outlets and can be queried by day. A new database gets a usable history immediately instead of after a week of collection. Backfilled days are recorded per keyword set and treated as complete in the report.
3. **Filter** articles by keywords (whole-word, case-insensitive).
4. **Analyze**
   - articles per day and per source
   - spike detection: days above the period's mean + 1.5 standard deviations
   - co-occurring names and places (capitalized-phrase extraction, with possessives, keywords and plurals normalized)
   - reprint removal: copies of the same headline under other domains (mostly wire copy on regional sites) are dropped before counting, keeping the earliest
   - stories: articles with similar headlines from different outlets are grouped, so the report shows which events the most outlets picked up
   - country comparison: share of attention and names mentioned, Israel vs US vs Iran
5. **Assess**: a short written assessment at the top of the report, comparing the last 24 hours with the 24 hours before. It gives three judgments, each with a confidence level and the numbers behind it: is coverage rising or falling (against the day before and against its usual daily level), is the language shifting toward escalation or diplomacy (two short word lists), and do countries frame the topic differently. It then lists what changed: new stories, and names mentioned more or less. It is rule-based, with no language model, so the same data always gives the same text. Confidence is High with 60+ articles from 5+ outlets, Medium with 20+ from 3+, otherwise Low.
6. **Report** a Markdown file with the assessment, key findings, tables, latest headlines and a coverage chart.

## Usage

```bash
pip install -r requirements.txt

# collect new articles (run daily or a few times a day to build history)
python -m osint_monitor collect

# fill the last 7 days for a topic from GDELT (optional, needs internet)
python -m osint_monitor backfill --keywords Iran Iranian Tehran --days 7

# report on a topic for the last 7 days
python -m osint_monitor report --keywords Iran Iranian Tehran --days 7

# optional: also refresh the assessment block at the top of this README
python -m osint_monitor report --keywords Iran --days 7 --out reports/latest --readme README.md
```

The report is written to `output/report.md` (or `--out`) with its charts. The scheduled workflow runs the same commands every 6 hours and commits the data and the report back to the repository.

## Design decisions

- **Rule-based, not a language model.** The assessment is built from counts and short word lists, so the same data always gives the same text and every sentence can be traced to a number. That makes it auditable, which matters more than fluency for an analytic product.
- **Confidence is stated, not implied.** Each judgment carries High, Medium or Low, set by how many articles and how many different outlets stand behind it. One outlet repeating itself does not raise confidence.
- **Volume is judged against two baselines.** The last 24 hours are compared with the 24 hours before and with the usual daily level (the average of the complete days before today, at least 3). A 40% drop after an unusually busy day is reported as "fell against the day before and is near its usual level", not as coverage drying up.
- **Shares instead of raw counts.** Feeds differ in size, so countries are compared by the share of their output that covers the topic.
- **Home press is excluded from attention comparisons.** Iranian state outlets cover Iran as domestic news, so they are compared on framing only.
- **Incomplete days are labeled, not hidden.** Days before collection started are drawn as partial and left out of peak and spike detection.
- **Agency datelines are stripped before names are counted.** Openings like "TEHRAN, Oct. 29 (MNA) -" say who filed the story, not what it is about. Left in, the agency tag "MNA" was the second most common "name" and showed up in the country comparison.
- **Reprints are removed before counting**, so wire copy republished by many sites does not look like independent coverage.
- **Failures are visible.** Each run records source health, a failed scheduled run opens a GitHub issue, and tests run on every push without network access.

## Project structure

```
osint_monitor/
  sources.py    list of RSS feeds
  collector.py  fetch, clean, deduplicate and store articles
  gdelt.py      historical backfill from the GDELT DOC API
  dedupe.py     reprint removal and story grouping by headline similarity
  analyzer.py   keyword filter, daily counts, spikes, entities, country comparison
  assessment.py key judgments with confidence, and what changed in 24 hours
  report.py     Markdown report and chart
  __main__.py   command-line interface
tests/          tests on a local sample feed (no internet needed)
data/           SQLite database and source health, updated by the workflow
reports/latest/ the latest report and charts, updated by the workflow
.github/        scheduled collection (every 6 hours) and CI (lint and tests)
```

Run the tests with `pytest` and the linter with `ruff check .`.

## Limitations
- RSS feeds only carry recent items, so trends become meaningful after the collector has run for several days.
- Entity extraction is a simple heuristic, not a trained NLP model. It can pick up generic capitalized words.
- The assessment describes what media report, not what happens on the ground. Tone uses short word lists, so it misses sarcasm and context.
- Iranian outlets are state-affiliated. Press TV (no dates), Tasnim and Fars (no connection from cloud servers) and Iran International (empty feed) could not be used.
- Israeli feeds are general news while US feeds are world sections, so attention shares are indicative, not like-for-like. Times of Israel and i24NEWS block automated access from cloud servers.
- Coverage volume is not importance: one outlet publishing many short updates can inflate a day's count.
- GDELT results carry titles only, and it matches keywords in the full article text, so backfilled articles whose title lacks the keyword are filtered out of the report. It is capped at 250 articles per day per query; a capped day is not marked complete.
- The same outlet can appear under an RSS name and a GDELT domain in the source table. Duplicate links are skipped, but the labels differ.
- Reprint removal and story grouping compare headline words only (Jaccard similarity), so paraphrased headlines that share few words are treated as different stories. Grouping is deliberately conservative: one event can show up as two or three stories rather than risk merging unrelated ones.

## Possible next steps

- Named-entity recognition with spaCy
- Hebrew and Arabic sources
- Alerts on spikes (failed runs already open a GitHub issue)
