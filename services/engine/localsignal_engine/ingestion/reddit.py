import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.models import Mention, Place


class RedditAdapter(IngestionAdapter):
    source = "reddit"

    def __init__(self, subreddits: list[str]) -> None:
        self.subreddits = subreddits

    def fetch_mentions(self, places: list[Place]) -> list[Mention]:
        mentions: list[Mention] = []
        for subreddit in self.subreddits:
            for place in places:
                query = urllib.parse.quote(place.name)
                url = (
                    f"https://www.reddit.com/r/{subreddit}/search.json"
                    f"?q={query}&restrict_sr=1&sort=new&t=week&limit=10"
                )
                try:
                    payload = _fetch_json(url)
                except OSError as exc:
                    print(f"Reddit fetch failed for r/{subreddit} {place.name}: {exc}", flush=True)
                    continue

                for child in payload.get("data", {}).get("children", []):
                    data = child.get("data", {})
                    title = data.get("title") or ""
                    selftext = data.get("selftext") or ""
                    body = f"{title}\n{selftext}".strip()
                    if not body:
                        continue
                    permalink = data.get("permalink") or ""
                    mentions.append(
                        Mention(
                            place_id=place.id,
                            source="reddit",
                            source_url=f"https://www.reddit.com{permalink}" if permalink else url,
                            body=body,
                            author_region=subreddit,
                            sentiment=None,
                            occurred_at=datetime.fromtimestamp(data.get("created_utc", time.time()), tz=timezone.utc),
                        )
                    )
                time.sleep(1)
        return mentions


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LocalSignalBot/0.1 by localsignal-mvp",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))
