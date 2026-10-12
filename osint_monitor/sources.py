"""News sources the monitor collects from.

Each source is a public RSS feed. Keeping the list in one place makes it
easy to add or remove sources without touching the rest of the code.
"""

SOURCES = {
    "Times of Israel": "https://www.timesofisrael.com/feed/",
    "Jerusalem Post": "https://www.jpost.com/rss/rssfeedsheadlines.aspx",
    "BBC Middle East": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "The Guardian World": "https://www.theguardian.com/world/rss",
    "UN News": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
}

# Outlets' own names. They appear in headlines ("BBC finds...") but are not
# part of the story, so the entity analysis ignores them.
OUTLET_NAMES = {
    "BBC", "Al Jazeera", "Times of Israel", "Jerusalem Post",
    "Guardian", "The Guardian", "UN News",
}
