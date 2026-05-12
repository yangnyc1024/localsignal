import json
from datetime import datetime
from pathlib import Path

from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.models import Mention, Place


class LocalJsonAdapter(IngestionAdapter):
    source = "local_json"

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def fetch_mentions(self, places: list[Place]) -> list[Mention]:
        place_ids = {place.id for place in places}
        records = json.loads(self.path.read_text())
        mentions: list[Mention] = []

        for record in records:
            if record["place_id"] not in place_ids:
                continue
            mentions.append(
                Mention(
                    place_id=record["place_id"],
                    source=record.get("source", self.source),
                    source_url=record.get("source_url"),
                    body=record["body"],
                    author_region=record.get("author_region"),
                    rating=record.get("rating"),
                    sentiment=record.get("sentiment"),
                    occurred_at=datetime.fromisoformat(record["occurred_at"]),
                )
            )

        return mentions
