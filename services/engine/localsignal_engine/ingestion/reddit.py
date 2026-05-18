import json
import os
import time
from typing import Optional
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.models import Mention, Place


class RedditAdapter(IngestionAdapter):
    source = "reddit"

    def __init__(self, subreddits: list[str]) -> None:
        self.subreddits = subreddits
        self.max_queries = int(os.getenv("REDDIT_MAX_QUERIES", "20"))
        self.sleep_seconds = float(os.getenv("REDDIT_SLEEP_SECONDS", "2"))

    def fetch_mentions(self, places: list[Place]) -> list[Mention]:
        mentions: list[Mention] = []
        seen_urls: set[str] = set()
        query_count = 0
        rate_limited = False
        for subreddit in self.subreddits:
            if rate_limited:
                break
            for place, query_text in _place_queries(places):
                if query_count >= self.max_queries:
                    print(
                        f"Reddit fetch stopped after {query_count} querie(s); "
                        "set REDDIT_MAX_QUERIES to raise the cap.",
                        flush=True,
                    )
                    _record_reddit_run(status="succeeded", total_queries=query_count, parsed_items=len(mentions))
                    return mentions
                query = urllib.parse.quote(query_text)
                url = (
                    f"https://www.reddit.com/r/{subreddit}/search.json"
                    f"?q={query}&restrict_sr=1&sort=new&t=week&limit=10"
                )
                query_count += 1
                try:
                    payload = _fetch_json(url)
                except urllib.error.HTTPError as exc:
                    if exc.code == 429:
                        print(
                            f"Reddit rate limited r/{subreddit}; stopping Reddit fetch "
                            f"for this run after {query_count} querie(s).",
                            flush=True,
                        )
                        _record_reddit_run(
                            status="failed",
                            total_queries=query_count,
                            parsed_items=len(mentions),
                            error="HTTP 429 Too Many Requests",
                        )
                        rate_limited = True
                        break
                    print(f"Reddit fetch failed for r/{subreddit} {query_text}: HTTP {exc.code}", flush=True)
                    continue
                except OSError as exc:
                    print(f"Reddit fetch failed for r/{subreddit} {query_text}: {exc}", flush=True)
                    continue

                for child in payload.get("data", {}).get("children", []):
                    data = child.get("data", {})
                    title = data.get("title") or ""
                    selftext = data.get("selftext") or ""
                    body = f"{title}\n{selftext}".strip()
                    if not body:
                        continue
                    if not _is_relevant_to_place(body, place):
                        continue
                    permalink = data.get("permalink") or ""
                    source_url = f"https://www.reddit.com{permalink}" if permalink else url
                    if source_url in seen_urls:
                        continue
                    seen_urls.add(source_url)
                    mentions.append(
                        Mention(
                            place_id=place.id,
                            source="reddit",
                            source_url=source_url,
                            body=body,
                            author_region=subreddit,
                            sentiment=None,
                            occurred_at=datetime.fromtimestamp(data.get("created_utc", time.time()), tz=timezone.utc),
                        )
                    )
                time.sleep(self.sleep_seconds)
        _record_reddit_run(status="succeeded", total_queries=query_count, parsed_items=len(mentions))
        return mentions


def _record_reddit_run(status: str, total_queries: int, parsed_items: int, error: Optional[str] = None) -> None:
    try:
        from localsignal_engine.db import record_social_source_run

        record_social_source_run(
            provider="reddit",
            platform="reddit",
            status=status,
            query=",".join(os.getenv("REDDIT_SUBREDDITS", "").split(",")),
            total_records=total_queries,
            normalized_records=parsed_items,
            fresh_records=parsed_items,
            parsed_items=parsed_items,
            resolved_items=parsed_items,
            source_counts={"reddit": parsed_items},
            error=error,
        )
    except Exception as exc:
        print(f"reddit source run logging failed: {exc}", flush=True)


def _place_queries(places: list[Place]) -> list[tuple[Place, str]]:
    queries: list[tuple[Place, str]] = []
    for place in places:
        queries.extend(
            [
                (place, f'"{place.name}"'),
                (place, f'"{place.name}" {place.city}'),
                (place, f'"{place.name}" food'),
                (place, f'"{place.name}" restaurant'),
            ]
        )
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[Place, str]] = []
    for place, query in queries:
        key = (place.id, query.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append((place, query))
    return unique


def _is_relevant_to_place(body: str, place: Place) -> bool:
    lowered = body.lower()
    name_tokens = [token for token in _tokens(place.name) if token not in {"the", "and", "bbq", "cafe", "coffee", "company", "house"}]
    if place.name.lower() in lowered:
        return True
    if name_tokens and sum(1 for token in name_tokens if token in lowered) >= min(2, len(name_tokens)):
        return True
    area_terms = [place.city.lower(), (place.neighborhood or "").lower()]
    food_terms = ["restaurant", "food", "tofu", "coffee", "cafe", "dessert", "bakery", "wait", "line"]
    return any(term and term in lowered for term in area_terms) and any(term in lowered for term in food_terms)


def _tokens(value: str) -> list[str]:
    return [token for token in value.lower().replace("&", " ").split() if token]


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
