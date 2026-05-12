import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.models import Mention, Place


class YelpFusionAdapter(IngestionAdapter):
    source = "yelp_fusion"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @classmethod
    def from_env(cls) -> "YelpFusionAdapter | None":
        api_key = os.getenv("YELP_API_KEY", "").strip()
        return cls(api_key) if api_key else None

    def fetch_mentions(self, places: list[Place]) -> list[Mention]:
        mentions: list[Mention] = []
        for place in places:
            query = urllib.parse.urlencode({"term": place.name, "location": f"{place.city}, NJ", "limit": 3})
            url = f"https://api.yelp.com/v3/businesses/search?{query}"
            try:
                payload = self._fetch(url)
            except OSError as exc:
                print(f"Yelp fetch failed for {place.name}: {exc}", flush=True)
                continue

            for business in payload.get("businesses", []):
                body = _business_body(business)
                if not body:
                    continue
                mentions.append(
                    Mention(
                        place_id=place.id,
                        source=self.source,
                        source_url=business.get("url"),
                        body=body,
                        rating=business.get("rating"),
                        author_region=place.city,
                        occurred_at=datetime.now(timezone.utc),
                    )
                )
        return mentions

    def _fetch(self, url: str) -> dict:
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))


def _business_body(business: dict) -> str:
    parts = [
        business.get("name", ""),
        f"rating {business.get('rating')}" if business.get("rating") else "",
        f"review count {business.get('review_count')}" if business.get("review_count") else "",
        ", ".join(business.get("categories", [{}])[0].values()) if business.get("categories") else "",
    ]
    return " | ".join(part for part in parts if part)
