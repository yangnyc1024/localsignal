import urllib.parse
from datetime import datetime, timedelta, timezone

from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.ingestion.rss import RssAdapter
from localsignal_engine.models import Mention, Place


class GoogleNewsAdapter(IngestionAdapter):
    source = "google_news"

    def fetch_mentions(self, places: list[Place]) -> list[Mention]:
        feeds = [
            f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
            for query in _queries(places)
        ]

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        return [mention for mention in RssAdapter(feeds, source=self.source).fetch_mentions(places) if mention.occurred_at >= cutoff]


def _queries(places: list[Place]) -> list[str]:
    queries: list[str] = []
    for place in places:
        area = place.neighborhood or place.city
        category = place.category.replace("_", " ")
        queries.extend(
            [
                f'"{place.name}" ({place.city} OR "{area}")',
                f'"{place.city}" "{category}" restaurant',
                f'"{place.city}" cafe dessert opening',
                f'"{place.city}" Korean food opening',
                f'"{area}" restaurant opening',
                f'"{place.city}" food "worth the drive"',
                f'"{place.city}" restaurant wait line',
            ]
        )
    seen: set[str] = set()
    return [query for query in queries if not (query.lower() in seen or seen.add(query.lower()))]
