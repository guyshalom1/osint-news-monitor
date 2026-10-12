# OSINT News Monitor

A Python tool that tracks how a topic is covered across open news sources. It collects articles from public RSS feeds, stores them locally, and produces an analyst-style report: coverage volume over time, unusual spikes, which outlets lead the coverage, and which names and places appear alongside the topic.

Built as a personal project to automate a task I do manually as a delegate intern at Israel's Permanent Mission to the UN: following how an issue develops across sources before a meeting.

## Live report

A scheduled GitHub Actions workflow collects new articles every 6 hours and rebuilds the report on real data. Latest report: [reports/latest/report.md](reports/latest/report.md)

![Coverage per day](reports/latest/coverage.png)

### Israeli vs US media

The same topic, compared between 6 Israeli and 5 US outlets: how much attention each country's media gives it, and which names and places each puts alongside it. Shares are used instead of raw counts, since the two countries' feeds differ in size.

![Israeli vs US media](reports/latest/comparison.png)

## What it does

1. **Collect** articles from 15 English-language RSS feeds, each tagged by country, into a SQLite database. Duplicates are skipped, so it can run repeatedly and build a history.
   - Israel: Haaretz, Jerusalem Post, Israel Hayom, Israel National News, JNS, Globes
   - US: New York Times, NPR, Fox News, CBS News, ABC News
   - International: BBC, Al Jazeera, The Guardian, UN News
   - Every run records source health in `data/source_status.json`, including feeds that respond but have stopped updating.
2. **Filter** articles by keywords (whole-word, case-insensitive).
3. **Analyze**
   - articles per day and per source
   - spike detection: days above the period's mean + 1.5 standard deviations
   - co-occurring names and places (capitalized-phrase extraction, with possessives, keywords and plurals normalized)
   - country comparison: share of attention and names mentioned, Israel vs US
4. **Report** a Markdown file with key findings, tables, latest headlines and a coverage chart.

## Usage

```bash
pip install -r requirements.txt

# collect new articles (run daily or a few times a day to build history)
python -m osint_monitor collect

# report on a topic for the last 7 days
python -m osint_monitor report --keywords Iran Iranian Tehran --days 7
```

The report is written to `output/report.md` with `output/coverage.png`.

## Project structure

```
osint_monitor/
  sources.py    list of RSS feeds
  collector.py  fetch, clean, deduplicate and store articles
  analyzer.py   keyword filter, daily counts, spikes, entities
  report.py     Markdown report and chart
  __main__.py   command-line interface
tests/          tests on a local sample feed (no internet needed)
```

Run the tests with `pytest`.

## Limitations

- RSS feeds only carry recent items, so trends become meaningful after the collector has run for several days.
- Entity extraction is a simple heuristic, not a trained NLP model. It can pick up generic capitalized words.
- Israeli feeds are general news while US feeds are world sections, so attention shares are indicative, not like-for-like. Times of Israel and i24NEWS block automated access from cloud servers.
- Coverage volume is not importance: one outlet publishing many short updates can inflate a day's count.

## Possible next steps

- Named-entity recognition with spaCy
- Hebrew and Arabic sources
- Scheduled collection and email alerts on spikes
