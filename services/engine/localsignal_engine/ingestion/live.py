import os

from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.ingestion.local_json import LocalJsonAdapter
from localsignal_engine.ingestion.reddit import RedditAdapter
from localsignal_engine.ingestion.rss import RssAdapter
from localsignal_engine.models import Mention, Place


def fetch_live_mentions(places: list[Place]) -> list[Mention]:
    adapters = _configured_adapters()
    mentions: list[Mention] = []

    for adapter in adapters:
        fetched = adapter.fetch_mentions(places)
        print(f"{adapter.source} produced {len(fetched)} mentions.", flush=True)
        mentions.extend(fetched)

    return mentions


def _configured_adapters() -> list[IngestionAdapter]:
    adapters: list[IngestionAdapter] = []

    local_json_path = os.getenv("LOCAL_JSON_MENTIONS_PATH", "").strip()
    if local_json_path:
        adapters.append(LocalJsonAdapter(local_json_path))

    rss_urls = _csv("RSS_FEED_URLS")
    if rss_urls:
        adapters.append(RssAdapter(rss_urls))

    subreddits = _csv("REDDIT_SUBREDDITS")
    if subreddits:
        adapters.append(RedditAdapter(subreddits))

    return adapters


def _csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip().strip("/") for item in raw.split(",") if item.strip()]
