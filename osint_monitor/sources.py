"""News sources the monitor collects from.

Each source is a public RSS feed, tagged with the country of the outlet so
coverage can be compared between countries. Keeping the list in one place
makes it easy to add or remove sources without touching the rest of the code.

All feeds are in English, so the same keywords work for every country.
"""

# name: (country, feed URL)
# Removed after testing from GitHub's servers: Times of Israel and i24NEWS
# (return a web page, not a feed) and Wall Street Journal (no longer updated).
# Ynetnews: the old feed (3089) died; 3082 works but updates slowly.
FEEDS = {
    # Israel
    "Haaretz": ("Israel", "https://www.haaretz.com/srv/haaretz-latest-headlines"),
    "Jerusalem Post": ("Israel", "https://rss.jpost.com/rss/rssfeedsfrontpage.aspx"),
    "Israel Hayom": ("Israel", "https://www.israelhayom.com/feed/"),
    "Israel National News": ("Israel", "https://www.israelnationalnews.com/Rss.aspx"),
    "JNS": ("Israel", "https://www.jns.org/feed/"),
    "Ynetnews": ("Israel", "https://www.ynetnews.com/Integration/StoryRss3082.xml"),
    "Globes": ("Israel", "https://en.globes.co.il/WebService/Rss/RssFeeder.asmx/FeederNode?iID=942"),
    # United States (world sections)
    "New York Times": ("US", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    "NPR": ("US", "https://feeds.npr.org/1004/rss.xml"),
    "Fox News": ("US", "https://moxie.foxnews.com/google-publisher/world.xml"),
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
    "The Guardian", "UN News", "Israel Hayom", "Haaretz", "JNS", "Globes", "Ynet", "Ynetnews",
    "Israel National News", "New York Times", "NPR", "Fox News", "Fox",
    "Wall Street Journal", "WSJ", "CBS News", "CBS", "ABC News", "ABC",
}
