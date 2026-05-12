import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.models import Mention, Place


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
                print(f"Google Places fetch failed for {place.name}: {exc}", flush=True)
                continue

            for result in payload.get("results", [])[:3]:
                place_id = result.get("place_id", "")
                body = _place_body(result)
                if not body:
                    continue
                mentions.append(
                    Mention(
                        place_id=place.id,
                        source=self.source,
                        source_url=f"https://maps.google.com/?cid={place_id}" if place_id else None,
                        body=body,
                        rating=result.get("rating"),
                        author_region=place.city,
                        occurred_at=datetime.now(timezone.utc),
                    )
                )
        return mentions

    def _fetch(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))


def _place_body(result: dict) -> str:
    parts = [
        result.get("name", ""),
        f"rating {result.get('rating')}" if result.get("rating") else "",
        f"user ratings {result.get('user_ratings_total')}" if result.get("user_ratings_total") else "",
        result.get("formatted_address", ""),
    ]
    return " | ".join(part for part in parts if part)
