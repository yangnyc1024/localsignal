"""Ingest recent posts from restaurants' own Instagram accounts.

Unlike location/hashtag scraping (which returns stale, sparse "top posts" for
small restaurants), scraping a restaurant's own profile yields its newest posts
— new dishes, specials, events — and binds every post to a known place with no
fuzzy matching. Handles come from place_profiles.instagram_handle, populated by
localsignal_engine.place.handles.resolve_instagram_handles().
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from localsignal_engine.db.connection import get_conn
from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.models import Mention, Place

logger = logging.getLogger(__name__)

ACTOR_ID = "apify~instagram-scraper"


class InstagramProfileAdapter(IngestionAdapter):
    source = "instagram"

    @classmethod
    def from_env(cls) -> Optional["InstagramProfileAdapter"]:
        if os.getenv("INSTAGRAM_PROFILE_ENABLED", "false").lower() != "true":
            return None
        if not os.getenv("APIFY_TOKEN", "").strip():
            return None
        return cls()

    def fetch_mentions(self, places: list[Place]) -> list[Mention]:
        token = os.getenv("APIFY_TOKEN", "").strip()
        if not token:
            return []
        # keyed by lowercased handle for matching against post ownerUsername
        self.handle_to_place = {
            h.lower(): p for h, p in _load_handle_map([p.id for p in places], places).items()
        }
        if not self.handle_to_place:
            logger.info("Instagram profile ingestion enabled but no handles are resolved yet.")
            return []

        max_profiles = int(os.getenv("INSTAGRAM_PROFILE_MAX_PROFILES", "30"))
        results_limit = int(os.getenv("INSTAGRAM_PROFILE_RESULTS_LIMIT", "10"))
        newer_than = os.getenv("INSTAGRAM_PROFILE_ONLY_NEWER_THAN", "60 days").strip()
        max_charge = float(os.getenv("INSTAGRAM_PROFILE_MAX_CHARGE_USD", "1.0"))

        handles = list(self.handle_to_place.keys())[:max_profiles]
        direct_urls = [f"https://www.instagram.com/{h}/" for h in handles]
        actor_input = {
            "directUrls": direct_urls,
            "resultsType": "posts",
            "resultsLimit": results_limit,
            "onlyPostsNewerThan": newer_than,
            "addParentData": True,
        }
        try:
            dataset_id = self._run(token, actor_input, max_charge)
            records = self._dataset_items(token, dataset_id, max_profiles * results_limit) if dataset_id else []
        except Exception as exc:
            logger.warning("Instagram profile scrape failed: %s", exc)
            return []

        mentions = self._parse(records)
        logger.info("Instagram profile scrape produced %d mention(s) from %d handle(s).", len(mentions), len(handles))
        return mentions

    # ── parsing ────────────────────────────────────────────────────────────

    def _parse(self, records: list[dict]) -> list[Mention]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(os.getenv("SOCIAL_MAX_AGE_DAYS", "60")))
        mentions: list[Mention] = []
        seen: set[str] = set()
        for record in records:
            for post in _iter_posts(record):
                owner = str(post.get("ownerUsername") or record.get("username") or "").lower()
                place = self.handle_to_place.get(owner)
                if not place:
                    continue
                body = _caption_text(post)
                if not body:
                    continue
                occurred_at = _post_timestamp(post)
                if occurred_at is None or occurred_at < cutoff:
                    continue
                code = _first(post, ["shortCode", "code", "shortcode"])
                url = f"https://www.instagram.com/p/{code}/" if code else _first(post, ["url", "inputUrl"])
                if url and url in seen:
                    continue
                if url:
                    seen.add(url)
                mentions.append(
                    Mention(
                        place_id=place.id,
                        source="instagram",
                        source_url=url or f"https://www.instagram.com/{owner}/",
                        body=body,
                        author_region=place.city,
                        sentiment=None,
                        occurred_at=occurred_at,
                        engagement_metrics={
                            "likes": post.get("likesCount") or post.get("like_count"),
                            "comments": post.get("commentsCount") or post.get("comment_count"),
                        },
                    )
                )
        return mentions

    # ── apify helpers ────────────────────────────────────────────────────────

    def _run(self, token: str, actor_input: dict[str, Any], max_charge: float) -> Optional[str]:
        query = urlencode({"maxTotalChargeUsd": str(max_charge)})
        request = Request(
            f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs?{query}",
            data=json.dumps(actor_input).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=60) as response:
            run = json.loads(response.read().decode("utf-8"))["data"]
        deadline = time.time() + int(os.getenv("INSTAGRAM_PROFILE_WAIT_SECONDS", "600"))
        while time.time() < deadline:
            current = self._get_run(token, run["id"])
            if current.get("status") in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
                if current.get("status") != "SUCCEEDED":
                    logger.warning("Instagram profile run finished with %s", current.get("status"))
                    return None
                return current.get("defaultDatasetId")
            time.sleep(10)
        logger.warning("Instagram profile run timed out.")
        return None

    def _get_run(self, token: str, run_id: str) -> dict:
        request = Request(
            f"https://api.apify.com/v2/actor-runs/{run_id}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))["data"]

    def _dataset_items(self, token: str, dataset_id: str, limit: int) -> list[dict]:
        query = urlencode({"clean": "true", "format": "json", "limit": str(limit)})
        request = Request(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items?{query}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, list) else []


def _load_handle_map(place_ids: list[str], places: list[Place]) -> dict[str, Place]:
    by_id = {p.id: p for p in places}
    if not place_ids:
        return {}
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT place_id::text, instagram_handle
            FROM place_profiles
            WHERE place_id = ANY(%s) AND COALESCE(instagram_handle, '') <> ''
            """,
            (place_ids,),
        ).fetchall()
    handle_map: dict[str, Place] = {}
    for place_id, handle in rows:
        place = by_id.get(place_id)
        if place:
            handle_map[handle] = place
    return handle_map


def _iter_posts(record: dict) -> list[dict]:
    """Yield post dicts from a scraper record (flat post or profile w/ nested posts)."""
    for key in ("latestPosts", "posts"):
        nested = record.get(key)
        if isinstance(nested, list) and nested and isinstance(nested[0], dict):
            return [p for p in nested if isinstance(p, dict)]
    # Flat post record (has its own caption/timestamp).
    if _caption_text(record) or record.get("shortCode") or record.get("timestamp"):
        return [record]
    return []


def _caption_text(post: dict) -> str:
    caption = post.get("caption")
    if isinstance(caption, dict):
        return str(caption.get("text") or "").strip()
    if caption:
        return str(caption).strip()
    return _first(post, ["text", "description", "title"])


def _post_timestamp(post: dict) -> Optional[datetime]:
    value = post.get("timestamp") or post.get("taken_at")
    caption = post.get("caption")
    if not value and isinstance(caption, dict):
        value = caption.get("created_at")
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.isdigit():
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, OSError):
        return None


def _first(record: dict, keys: list[str]) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""
