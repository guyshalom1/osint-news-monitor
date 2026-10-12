"""News sources the monitor collects from.

Each source is a public RSS feed, tagged with the country of the outlet so
coverage can be compared between countries. Keeping the list in one place
makes it easy to add or remove sources without touching the rest of the code.

All feeds are in English, so the same keywords work for every country.
"""

# name: (country, feed URL)
FEEDS = {
    # Israel
    "Times of Israel": ("Israel", "https://www.timesofisrael.com/feed/"),
    "Jerusalem Post": ("Israel", "https://www.jpost.com/rss/rssfeedsheadlines.aspx"),
    "Israel Hayom": ("Israel", "https://www.israelhayom.com/feed/"),
    "Ynetnews": ("Israel", "https://www.ynetnews.com/Integration/StoryRss3089.xml"),
    "Israel National News": ("Israel", "https://www.israelnationalnews.com/Rss.aspx"),
    "i24NEWS": ("Israel", "https://www.i24news.tv/en/rss"),
    # United States (world sections)
    "New York Times": ("US", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    "NPR": ("US", "https://feeds.npr.org/1004/rss.xml"),
    "Fox News": ("US", "https://moxie.foxnews.com/google-publisher/world.xml"),
    "Wall Street Journal": ("US", "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
    "CBS News": ("US", "https://www.cbsnews.com/latest/rss/world"),
    "ABC News": ("US", "https://abcnews.go.com/abcnews/internationalheadlines"),
    # International
    "BBC Middle East": ("International", "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"),
    "Al Jazeera": ("International", "https://www.aljazeera.com/xml/rss/all.xml"),
    "The Guardian World": ("International", "https://www.theguardian.com/world/rss"),
    "UN News": ("International", "https://news.un.org/feed/subscribe/en/news/all/rss.xml"),
}

SOURCES = {name: url for name, (_, url) in FEEDS.items()}
COUNTRY = {name: country for name, (country, _) in FEEDS.items()}

# Outlets' own names. They appear in headlines ("BBC finds...") but are not
# part of the story, so the entity analysis ignores them.
OUTLET_NAMES = {
    "BBC", "Al Jazeera", "Times of Israel", "Jerusalem Post", "Guardian",
    "The Guardian", "UN News", "Israel Hayom", "Ynet", "Ynetnews", "i24NEWS",
    "Israel National News", "New York Times", "NPR", "Fox News", "Fox",
    "Wall Street Journal", "WSJ", "CBS News", "CBS", "ABC News", "ABC",
}
