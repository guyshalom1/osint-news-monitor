# OSINT News Monitor

A Python tool that tracks how a topic is covered across open news sources. It collects articles from public RSS feeds, stores them locally, and produces an analyst-style report: coverage volume over time, unusual spikes, which outlets lead the coverage, and which names and places appear alongside the topic.

Built as a personal project to automate a task I do manually as a delegate intern at Israel's Permanent Mission to the UN: following how an issue develops across sources before a meeting.

## Live report

A scheduled GitHub Actions workflow collects new articles every 6 hours and rebuilds the report on real data. Latest report: [reports/latest/report.md](reports/latest/report.md)

![Coverage per day](reports/latest/coverage.png)

## What it does

1. **Collect** articles from 6 RSS feeds (Times of Israel, Jerusalem Post, BBC, Al Jazeera, The Guardian, UN News) into a SQLite database. Duplicates are skipped, so it can run repeatedly and build a history.
2. **Filter** articles by keywords (whole-word, case-insensitive).
3. **Analyze**
   - articles per day and per source
   - spike detection: days above the period's mean + 1.5 standard deviations
   - co-occurring names and places (capitalized-phrase extraction)
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
- Coverage volume is not importance: one outlet publishing many short updates can inflate a day's count.

## Possible next steps

- Named-entity recognition with spaCy
- Hebrew and Arabic sources
- Scheduled collection and email alerts on spikes
