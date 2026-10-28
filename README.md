# OSINT News Monitor

A Python tool that tracks how a topic is covered across open news sources. It collects articles from public RSS feeds, stores them locally, and produces an analyst-style report: coverage volume over time, unusual spikes, which outlets lead the coverage, and which names and places appear alongside the topic.

Built as a personal project to automate a task I do manually as a delegate intern at Israel's Permanent Mission to the UN: following how an issue develops across sources before a meeting.

## Latest assessment

<!-- assessment:start -->
_Updated 2026-10-28 15:53 UTC. Full report: [reports/latest/report.md](reports/latest/report.md)_

## Assessment

The last 24 hours compared with the 24 hours before. Rule-based, from coverage counts only. It describes what the media report, not what is happening on the ground.

1. **Coverage is steady.** Confidence: High. 100 articles in the last 24 hours vs 125 in the 24 hours before (-20%), from 16 outlets.
2. **The balance between escalation and diplomacy language is unchanged.** Confidence: High. Escalation words in 23% of articles (earlier 17%), diplomacy words in 16% (earlier 12%).
3. **Countries frame the topic differently; the clearest gap is "Netanyahu".** Confidence: Medium. Israel outlets give the topic 11.3% of their articles; US outlets give the topic 7.0% of their articles. Home press is left out of the attention comparison, since it covers the topic as domestic news. "Netanyahu" appears in 44% of Israel topic articles and 2% of Iran.

Confidence: High means 60+ articles from 5+ outlets, Medium means 20+ from 3+ outlets, Low means less than that.

## What changed in the last 24 hours

- New story, 2 outlets: IRGC dispmantles two terror teams in southeast Iran
- New story, 2 outlets: Report: US tells Gulf allies to prepare for Iran strikes after midterms
- Mentioned more: Ministry (0% to 7%), Oct (23% to 30%), Middle East (0% to 7%).
- Mentioned less: Saudi Arabia (10% to 2%), Khamenei (8% to 0%), Turkey (7% to 0%).
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
5. **Assess**: a short written assessment at the top of the report, comparing the last 24 hours with the 24 hours before. It gives three judgments, each with a confidence level and the numbers behind it: is coverage rising or falling, is the language shifting toward escalation or diplomacy (two short word lists), and do countries frame the topic differently. It then lists what changed: new stories, and names mentioned more or less. It is rule-based, with no language model, so the same data always gives the same text. Confidence is High with 60+ articles from 5+ outlets, Medium with 20+ from 3+, otherwise Low.
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
```

The report is written to `output/report.md` with `output/coverage.png`.

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
```

Run the tests with `pytest`.

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
