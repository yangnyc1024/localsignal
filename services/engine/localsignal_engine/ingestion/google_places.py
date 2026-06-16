import logging
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from typing import Optional

from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.models import Mention, Place

logger = logging.getLogger(__name__)


class GooglePlacesAdapter(IngestionAdapter):
    source = "google_places"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @classmethod
    def from_env(cls) -> "GooglePlacesAdapter | None":
        api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
        return cls(api_key) if api_key else None

    def fetch_mentions(self, places: list[Place]) -> list[Mention]:
        mentions: list[Mention] = []
        for place in places:
            result = self._place_result(place)
            if not result:
                continue

            google_place_id = result.get("place_id", "")
            body = _place_body(result)
            if body:
                mentions.append(
                    Mention(
                        place_id=place.id,
                        source=self.source,
                        source_url=_maps_url(google_place_id),
                        body=body,
                        rating=result.get("rating"),
                        author_region=place.city,
                        occurred_at=datetime.now(timezone.utc),
                    )
                )

            if google_place_id:
                mentions.extend(self._fetch_review_mentions(place, google_place_id))
        return mentions

    def _place_result(self, place: Place) -> dict:
        if place.google_place_id:
            return {
                "name": place.name,
                "place_id": place.google_place_id,
                "formatted_address": "",
                "rating": None,
                "user_ratings_total": None,
            }
        return self._find_place(place) or {}

    def _find_place(self, place: Place) -> Optional[dict]:
        params = urllib.parse.urlencode(
            {
                "query": f"{place.name} {place.city} NJ",
                "fields": "name,rating,user_ratings_total,formatted_address,place_id",
                "key": self.api_key,
            }
        )
        url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?{params}"
        try:
            payload = self._fetch(url)
        except OSError as exc:
            logger.warning(f"Google Places search failed for {place.name}: {exc}")
            return None
        return next(iter(payload.get("results", [])), None)

    def _fetch_review_mentions(self, place: Place, google_place_id: str) -> list[Mention]:
        params = urllib.parse.urlencode(
            {
                "place_id": google_place_id,
                "fields": "name,place_id,url,reviews",
                "reviews_sort": "newest",
                "reviews_no_translations": "true",
                "key": self.api_key,
            }
        )
        url = f"https://maps.googleapis.com/maps/api/place/details/json?{params}"
        try:
            payload = self._fetch(url)
        except OSError as exc:
            logger.warning(f"Google Places details failed for {place.name}: {exc}")
            return []

        result = payload.get("result", {})
        reviews = result.get("reviews", [])
        mentions: list[Mention] = []
        for review in reviews:
            text = _review_text(review)
            if not text:
                continue
            review_time = review.get("time")
            mentions.append(
                    Mention(
                        place_id=place.id,
                        source="google_reviews",
                        source_url=_review_url(result.get("url") or _maps_url(google_place_id), review),
                        body=text,
                        rating=review.get("rating"),
                        author_region=place.city,
                    occurred_at=datetime.fromtimestamp(review_time, tz=timezone.utc)
                    if review_time
                    else datetime.now(timezone.utc),
                )
            )
        return mentions

    def _fetch(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))


def _place_body(result: dict) -> str:
    metadata_parts = [
        f"rating {result.get('rating')}" if result.get("rating") else "",
        f"user ratings {result.get('user_ratings_total')}" if result.get("user_ratings_total") else "",
        result.get("formatted_address", ""),
    ]
    metadata_parts = [part for part in metadata_parts if part]
    if not metadata_parts:
        return ""
    return " | ".join([result.get("name", ""), *metadata_parts])


def _review_text(review: dict) -> str:
    text = unescape(review.get("text") or "").strip()
    if not text:
        return ""
    return text


def _maps_url(google_place_id: str) -> Optional[str]:
    return f"https://www.google.com/maps/place/?q=place_id:{google_place_id}" if google_place_id else None


def _review_url(base_url: Optional[str], review: dict) -> Optional[str]:
    if not base_url:
        return None
    author = re.sub(r"[^a-z0-9]+", "-", (review.get("author_name") or "anonymous").lower()).strip("-")
    review_time = review.get("time") or "unknown"
    return f"{base_url}#review-{review_time}-{author}"
