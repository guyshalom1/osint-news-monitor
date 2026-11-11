# Audit of version 0.x

A review of every module before the 1.0 changes, checked against the live database as it stood on 11 November 2026 (16,527 articles, 30 days of collection). Each finding states what was wrong, the evidence, and what was done. Findings that were not fixed are listed at the end.

## Analytical findings

| # | Finding | Evidence on live data | Status |
|---|---|---|---|
| A1 | **A tone shift was reported inside sampling noise, at High confidence.** The rule called a shift at 5 points with no test. | The report read "Language is shifting toward escalation. Confidence: High" on escalation 36% to 38% and diplomacy 19% to 15% (net +6 points) with 158 and 122 articles. The 95% noise margin for those samples is about 15 points. | Fixed: the move must exceed its margin, and the margin is printed. |
| A2 | **The topic country's own press set the trend.** Iranian state outlets match the keyword "Iran" in almost every story, including sports and tourism. | They supplied 63% of the last 24 hours. Without them the tone moved the other way: escalation words fell from 66% to 61% in foreign press while the headline judgment said escalation was rising. | Fixed: trend judgments use the feeds outside the topic country. Home press tone is reported on its own line. |
| A3 | **GDELT backfill made some days look busier.** Backfill succeeds on some days and is rate-limited on others, and both kinds of day were counted together. | GDELT articles existed for 4 of the 7 days. The reported peak (8 November, 158 articles) was a day the backfill ran. On the fixed feeds the peak was 10 November. | Fixed: articles carry an `origin`, and trend, peak and spike use the fixed feeds. The chart stacks the three kinds. |
| A4 | **Confidence measured the amount of data, not the strength of the finding.** A +25.1% change and a +200% change got the same level, and nothing could lower it. | The outlet count included about 95 GDELT domains with one article each, so the "5+ outlets" condition was always met and every volume judgment was High. | Fixed: outlets are counted on the panel, and confidence drops when a finding fails the leave-one-outlet-out check or cannot be confirmed. |
| A5 | **The word lists measured the topic as much as the tone.** | "war" alone matched 22% of recent articles, because the conflict is called "the Iran war". "envoy", "delegation" and "agreement" matched mostly ambassadors at cultural events and trade agreements in Iranian outlets. "threat" matched but "threats" did not; "strike" but not "airstrike" or "struck". "US rules out a strike" counted as escalation. | Fixed: lists revised after reading matches in context, inflections added, negation and reported failure handled. Scored on labeled articles: escalation precision 0.79, recall 0.60; diplomacy 1.00 and 0.75. |
| A6 | **The framing gap had no significance test and several built-in biases.** Eight names were compared across three country pairs, and the largest gap of 15 points or more was reported. | US outlets had 33 topic articles, where 19% is 6 articles. "Israel" in Israeli press was eligible as a "framing gap". 95.9% of Iranian articles match the topic, so every foreign name is diluted there. Names outside a country's top 50 were shown as 0%. | Fixed: two-proportion test with a Bonferroni bar and a minimum expected count, a country's own name is skipped, pairs of foreign press are preferred, and a gap against home press carries a caveat. |
| A7 | **The spike rule fired on noise.** It was mean + 1.5 standard deviations over seven days, with no floor for small counts. | Simulated on weeks of pure random variation around 30 articles a day, it reported a "spike" in 54% of weeks. Four days of 2 articles and one of 4 was a spike. | Fixed: each day is tested against the other days at 3 standard deviations, with a floor of the counting noise. False alarms fall to 3% of weeks, and a true doubling is still caught 93% of the time. |
| A8 | **One article could count twice for one person.** Name variants were merged after counting. | An article with "Benjamin Netanyahu" in the title and "Netanyahu" in the summary added 2. Shares could exceed 100%. "White House" was merged into "House". | Fixed: variants are merged inside each article, and with spaCy only names typed as people are merged into a surname. |
| A9 | **Name extraction was a capitalized-word regex.** | On 50 labeled articles: precision 0.73. In title-case headlines it returned "Refrigeration Systems" and "Chemical Weapons Divide", and it cannot read "U.S.". | Fixed: spaCy NER (F1 0.90 against 0.76), with the regex kept as a measured fallback. |
| A10 | **Names "mentioned more" had no noise check.** | A name going from 1 to 3 articles out of 20 was reported as a rise from 5% to 15%. | Fixed: the move must pass a two-proportion test. |

## Engineering findings

| # | Finding | Status |
|---|---|---|
| E1 | Feeds were fetched with `feedparser.parse(url)`: no timeout (one stalled server could hang the scheduled run), no retry, the library's default User-Agent, no robots.txt check. | Fixed in `http.py`. |
| E2 | A headline containing `\|` broke Markdown tables in the report and the README. Headlines also went unescaped into link labels. | Fixed: `md_cell`, `md_link`, and site names are stripped from displayed headlines. |
| E3 | The bot committed a binary SQLite file to `main` four times a day and rewrote the README on each run, so any human edit to the README risked a merge conflict. | Fixed: `data` branch with one rolling commit. |
| E4 | The database only grew: 8.4 MB after 30 days, including feed items dated 2019. GitHub rejects files over 100 MB. | Fixed: 180-day retention and an integrity check before publishing. |
| E5 | `print` for all output, and `collect` exited 0 even when every source failed. | Fixed: `logging`, and a non-zero exit when nothing was collected. |
| E6 | No type hints, `pytest` listed as a runtime dependency, no package metadata, no license. | Fixed: `mypy --strict`, a full `pyproject.toml` with optional extras, MIT license, Makefile. |
| E7 | Zero-width characters in feed text made "Iran" and "​Iran" different strings. | Fixed in `clean_text`. |
| E8 | Articles with the same timestamp came back in whatever order SQLite chose, so tied counts could reorder between runs. | Fixed: explicit tie-break. |
| E9 | Feed items dated in the future were accepted into the newest window. | Fixed: capped at one hour ahead. |

## Known and not fixed

- **Story grouping still splits one event.** "Trump says renewed attacks on Iran highly unlikely if talks show progress" and "Trump says return to Iran war highly unlikely if talks advance" are two stories. Headline word overlap cannot see paraphrase. Sentence embeddings would, at the cost of a heavier dependency.
- **Outlets are treated as independent.** Two sites rewriting one wire story count as two outlets.
- **The noise tests assume independent articles.** News is bursty, so the true margins are wider than the ones printed.
- **Tone counts hypotheticals.** "US ready to strike if needed" is escalation language to the word list.
- **Short feeds drop items between runs.** This is now detected and flagged, not repaired.
- **The same article can be stored twice** when a feed URL carries a tracking parameter and GDELT returns the clean URL. Reprint removal catches it at analysis time.
- **The labeled sample is small**: 50 articles, one topic, one week, one annotator, and the cleanup rules were adjusted after looking at it. There is no held-out set.
- **The country comparison is not like-for-like**: Israeli feeds are general news, US feeds are world sections.
