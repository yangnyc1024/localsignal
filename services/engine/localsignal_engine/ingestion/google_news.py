import urllib.parse

from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.ingestion.rss import RssAdapter
from localsignal_engine.models import Mention, Place


class GoogleNewsAdapter(IngestionAdapter):
    source = "google_news"

    def fetch_mentions(self, places: list[Place]) -> list[Mention]:
        feeds = []
        for place in places:
            query = urllib.parse.quote(f'"{place.name}" ({place.city} OR {place.neighborhood or place.city})')
            feeds.append(f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en")

        return RssAdapter(feeds, source=self.source).fetch_mentions(places)
