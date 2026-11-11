# Changelog

## 1.0.0 (2026-11-11)

Based on a full audit of the earlier code against live data: [docs/AUDIT.md](docs/AUDIT.md).

### Method

- **Fixed panel for trends.** Volume, tone, peak and spike detection now use the RSS feeds outside the topic country. GDELT backfill and home press are counted separately and shown as separate segments in the chart. Why: backfill is uneven from day to day, and Iranian state outlets supplied over half of all matching articles.
- **Noise tests.** A change in volume, tone, a name's share or a framing gap is only called when it is larger than its 95% sampling margin. The framing comparison uses a Bonferroni-corrected bar.
- **Confidence can drop.** One level down when a finding does not hold without the busiest outlet, or when a measured move cannot be confirmed at the sample size.
- **Tone word lists revised** after reading matches in context. "war", "envoy", "delegation" and "agreement" removed; inflected forms added; negated terms and reported failures of diplomacy no longer count.
- **Spike detection** compares each day with the other days at 3 standard deviations with a counting-noise floor. The earlier rule fired in about half of all weeks of pure random variation.
- **Framing comparison** skips a country's own name, uses feed articles only, and attaches a caveat to any gap against home press.
- **Names are merged per article**, so one article cannot count twice for one person.

### Features

- **Daily brief** in HTML (self-contained, charts embedded) and optional PDF: bottom line, key judgments with confidence, what changed, coverage, framing by country, source caveats.
- **spaCy NER** for names, with the regex kept as a fallback. `--ner auto|spacy|regex`.
- **`osint-monitor evaluate`** scores name extraction and the tone lists against 50 hand-labeled articles.
- **Source health** now flags feeds that turned over completely between runs.
- **`prune`** and **`check`** commands for retention and database integrity.

### Engineering

- `http.py`: project User-Agent, robots.txt (RFC 9309), 20-second timeout, retries with exponential backoff and jitter, `Retry-After` honored.
- Headlines escaped in Markdown tables and links; site names stripped from displayed headlines.
- Type hints throughout, checked with `mypy --strict`. `logging` instead of `print`.
- `pyproject.toml` with metadata, the `osint-monitor` entry point, and optional extras `nlp`, `pdf`, `dev`. `requirements.txt` and `pytest.ini` removed.
- MIT license, Makefile (`make install`, `make check`, `make run`, `make evaluate`).
- CI: lint, type check and tests on Python 3.10 and 3.13, a run without the optional dependencies, and an informational live-feed check on pull requests.
- Database and reports moved to the `data` branch (one commit, replaced on every run). Snapshots kept 14 days as workflow artifacts.
- Tests: 70 to 135, 97% line coverage. Two existing volume tests now use larger samples, because 30 against 20 articles is correctly no longer called a rise.

### Schema

- `articles.origin` column (`rss` or `gdelt`), added and backfilled automatically on first open.
