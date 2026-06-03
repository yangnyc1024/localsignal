import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from localsignal_engine.db.connection import get_conn

from localsignal_engine.ingestion.apify_social import fetch_apify_social_metadata_items
from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.ingestion.google_news import GoogleNewsAdapter
from localsignal_engine.ingestion.google_places import GooglePlacesAdapter
from localsignal_engine.ingestion.local_json import LocalJsonAdapter
from localsignal_engine.ingestion.reddit import RedditAdapter
from localsignal_engine.ingestion.rss import RssAdapter
from localsignal_engine.ingestion.social_metadata import SocialMetadataItem, load_social_metadata_items
from localsignal_engine.ingestion.yelp import YelpFusionAdapter
from localsignal_engine.models import Mention, Place


def fetch_live_mentions(places: list[Place]) -> tuple[list[Mention], dict[str, int]]:
    adapters = _configured_adapters()
    mentions: list[Mention] = []
    source_counts: dict[str, int] = {}

    for adapter in adapters:
        fetched = adapter.fetch_mentions(places)
        print(f"{adapter.source} produced {len(fetched)} mentions.", flush=True)
        source_counts[adapter.source] = len(fetched)
        mentions.extend(fetched)

    return mentions, source_counts


def fetch_social_metadata_items(places: list[Place]) -> tuple[list[SocialMetadataItem], dict[str, int]]:
    sources = {
        "instagram": os.getenv("INSTAGRAM_JSON_PATH", "").strip(),
        "tiktok_metadata": os.getenv("TIKTOK_JSON_PATH", "").strip(),
        "xiaohongshu": os.getenv("XHS_JSON_PATH", os.getenv("XIAOHONGSHU_JSON_PATH", "")).strip(),
    }
    items: list[SocialMetadataItem] = []
    source_counts: dict[str, int] = {}

    for source, raw_paths in sources.items():
        fetched_for_source: list[SocialMetadataItem] = []
        for path in _paths(raw_paths):
            fetched = load_social_metadata_items(path, source, places)
            print(f"{source} metadata from {path} produced {len(fetched)} raw item(s).", flush=True)
            fetched_for_source.extend(fetched)
        if fetched_for_source:
            source_counts[source] = len(fetched_for_source)
            items.extend(fetched_for_source)

    for extra_items, extra_counts in [
        _fetch_social_inbox_items(places),
        fetch_apify_social_metadata_items(places),
    ]:
        items.extend(extra_items)
        for source, count in extra_counts.items():
            source_counts[source] = source_counts.get(source, 0) + count

    return items, source_counts


def _configured_adapters() -> list[IngestionAdapter]:
    adapters: list[IngestionAdapter] = []

    local_json_path = os.getenv("LOCAL_JSON_MENTIONS_PATH", "").strip()
    if local_json_path:
        adapters.append(LocalJsonAdapter(local_json_path))

    rss_urls = _csv("RSS_FEED_URLS")
    if rss_urls:
        adapters.append(RssAdapter(rss_urls))

    if os.getenv("GOOGLE_NEWS_ENABLED", "true").lower() == "true":
        adapters.append(GoogleNewsAdapter())

    reddit_enabled = os.getenv("REDDIT_ENABLED", "false").lower() == "true"
    subreddits = _csv("REDDIT_SUBREDDITS")
    if reddit_enabled and subreddits:
        if _source_due("reddit", int(os.getenv("REDDIT_INTERVAL_SECONDS", "604800"))):
            adapters.append(RedditAdapter(subreddits))
        else:
            print("Reddit ingestion is enabled but not due yet; set REDDIT_FORCE_RUN=true to override.", flush=True)
    elif subreddits and not reddit_enabled:
        print("Reddit ingestion is configured but disabled; set REDDIT_ENABLED=true to fetch Reddit.", flush=True)

    yelp = YelpFusionAdapter.from_env()
    if yelp:
        adapters.append(yelp)

    google_places = GooglePlacesAdapter.from_env()
    if google_places:
        adapters.append(google_places)

    return adapters


def _source_due(provider: str, interval_seconds: int) -> bool:
    if os.getenv(f"{provider.upper()}_FORCE_RUN", "false").lower() == "true":
        return True
    if interval_seconds <= 0:
        return True
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return True
    try:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT finished_at
                FROM social_source_runs
                WHERE provider = %s
                ORDER BY finished_at DESC
                LIMIT 1
                """,
                (provider,),
            ).fetchone()
    except Exception as exc:
        print(f"{provider} cadence check failed; running source anyway: {exc}", flush=True)
        return True
    if not row or not row[0]:
        return True
    elapsed = (datetime.now(timezone.utc) - row[0]).total_seconds()
    return elapsed >= interval_seconds


def _csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip().strip("/") for item in raw.split(",") if item.strip()]


def _paths(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _fetch_social_inbox_items(places: list[Place]) -> tuple[list[SocialMetadataItem], dict[str, int]]:
    directory = os.getenv("SOCIAL_JSON_DIR", "").strip()
    if not directory:
        return [], {}

    root = Path(directory)
    if not root.exists():
        print(f"social inbox directory does not exist: {directory}", flush=True)
        return [], {}

    items: list[SocialMetadataItem] = []
    source_counts: dict[str, int] = {}
    for path in sorted(root.glob("**/*")):
        if path.suffix.lower() not in {".json", ".jsonl"}:
            continue
        fetched = load_social_metadata_items(str(path), "social_metadata", places)
        print(f"social inbox file {path} produced {len(fetched)} raw item(s).", flush=True)
        items.extend(fetched)
        for item in fetched:
            source_counts[item.platform] = source_counts.get(item.platform, 0) + 1
    return items, source_counts
