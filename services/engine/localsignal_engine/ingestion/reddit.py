import base64
import logging
import json
import os
import threading
import time
from typing import Optional
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.models import Mention, Place

logger = logging.getLogger(__name__)


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
        if not _oauth_credentials():
            logger.warning(
                "Reddit credentials missing (REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET); "
                "the public JSON endpoint is blocked (HTTP 403) from most hosts. "
                "Register a 'script' app at https://www.reddit.com/prefs/apps to enable ingestion."
            )
        for subreddit in self.subreddits:
            if rate_limited:
                break
            for place, query_text in _place_queries(places):
                if query_count >= self.max_queries:
                    logger.info(
                        "Reddit fetch stopped after %d querie(s); set REDDIT_MAX_QUERIES to raise the cap.",
                        query_count,
                    )
                    _record_reddit_run(status="succeeded", total_queries=query_count, parsed_items=len(mentions))
                    return mentions
                query = urllib.parse.quote(query_text)
                time_window = os.getenv("REDDIT_TIME_WINDOW", "month")
                base = _base_url()
                suffix = "" if base.startswith("https://oauth") else ".json"
                url = (
                    f"{base}/r/{subreddit}/search{suffix}"
                    f"?q={query}&restrict_sr=1&sort=new&t={time_window}&limit=25"
                )
                query_count += 1
                try:
                    payload = _fetch_json(url)
                except urllib.error.HTTPError as exc:
                    if exc.code == 429:
                        logger.warning(
                            "Reddit rate limited r/%s; stopping after %d querie(s).",
                            subreddit, query_count,
                        )
                        _record_reddit_run(
                            status="failed",
                            total_queries=query_count,
                            parsed_items=len(mentions),
                            error="HTTP 429 Too Many Requests",
                        )
                        rate_limited = True
                        break
                    logger.warning(f"Reddit fetch failed for r/{subreddit} {query_text}: HTTP {exc.code}")
                    continue
                except OSError as exc:
                    logger.warning(f"Reddit fetch failed for r/{subreddit} {query_text}: {exc}")
                    continue

                for child in payload.get("data", {}).get("children", []):
                    data = child.get("data", {})
                    title = data.get("title") or ""
                    selftext = data.get("selftext") or ""
                    body = f"{title}\n{selftext}".strip()
                    if not body:
                        continue
                    if not _is_relevant_to_place(body, place, subreddit):
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
        logger.warning(f"reddit source run logging failed: {exc}")


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


def _is_relevant_to_place(body: str, place: Place, subreddit: str = "") -> bool:
    """Return True if the Reddit post body is relevant to the given place.

    Matching strategy (any one is sufficient):
    1. Exact place name appears in the body.
    2. Enough name tokens match (handles partial/abbreviated names).
    3. The subreddit is a local neighbourhood sub (fort lee, edgewater, etc.)
       AND the body contains at least one food-related term — we assume
       neighbourhood-specific subs are inherently local so any food talk is fair game.
    4. A city/neighbourhood area term AND a food term appear together.
    """
    lowered = body.lower()
    stopwords = {"the", "and", "bbq", "cafe", "coffee", "company", "house", "bar", "grill"}
    name_tokens = [t for t in _tokens(place.name) if t not in stopwords]

    # 1. Exact name match
    if place.name.lower() in lowered:
        return True

    # 2. Token overlap (≥2 tokens, or all tokens if name is short)
    if name_tokens and sum(1 for t in name_tokens if t in lowered) >= min(2, len(name_tokens)):
        return True

    food_terms = [
        "restaurant", "food", "eat", "eating", "ate", "tofu", "coffee", "cafe",
        "dessert", "bakery", "boba", "ramen", "sushi", "bbq", "brunch", "lunch",
        "dinner", "breakfast", "menu", "order", "takeout", "delivery", "reservation",
        "wait", "line", "service", "dish", "taste", "review", "recommend",
    ]

    # 3. Local neighbourhood subreddit — any food mention is relevant
    local_subs = {"fortlee", "edgewater", "palisadespark"}
    if subreddit.lower().replace(" ", "") in local_subs:
        return any(term in lowered for term in food_terms)

    # 4. Area term + food term
    area_terms = [t for t in [place.city.lower(), (place.neighborhood or "").lower()] if t]
    return any(term in lowered for term in area_terms) and any(term in lowered for term in food_terms)


def _tokens(value: str) -> list[str]:
    return [token for token in value.lower().replace("&", " ").split() if token]


def _user_agent() -> str:
    return os.getenv("REDDIT_USER_AGENT", "LocalSignalBot/0.1 by localsignal-mvp")


def _oauth_credentials() -> Optional[tuple[str, str]]:
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return client_id, client_secret
    return None


def _base_url() -> str:
    # Reddit blocks the public www.reddit.com JSON endpoints from datacenter IPs
    # (HTTP 403). With OAuth credentials we use oauth.reddit.com, which works.
    return "https://oauth.reddit.com" if _oauth_credentials() else "https://www.reddit.com"


_token_cache: dict = {"token": None, "expires_at": 0.0}
_token_lock = threading.Lock()


def _get_access_token() -> Optional[str]:
    """Return a cached Reddit OAuth bearer token, fetching one if needed.

    Uses the resource-owner password grant when REDDIT_USERNAME/PASSWORD are set
    (script app), otherwise application-only client_credentials. Returns None when
    no credentials are configured so callers fall back to the public endpoint.
    """
    creds = _oauth_credentials()
    if not creds:
        return None
    now = time.time()
    with _token_lock:
        if _token_cache["token"] and now < _token_cache["expires_at"]:
            return _token_cache["token"]
        client_id, client_secret = creds
        username = os.getenv("REDDIT_USERNAME", "").strip()
        password = os.getenv("REDDIT_PASSWORD", "").strip()
        if username and password:
            form = {"grant_type": "password", "username": username, "password": password}
        else:
            form = {"grant_type": "client_credentials"}
        auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        request = urllib.request.Request(
            "https://www.reddit.com/api/v1/access_token",
            data=urllib.parse.urlencode(form).encode(),
            headers={
                "Authorization": f"Basic {auth}",
                "User-Agent": _user_agent(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, OSError) as exc:
            logger.warning("Reddit OAuth token request failed: %s", exc)
            return None
        token = payload.get("access_token")
        if not token:
            logger.warning("Reddit OAuth response had no access_token: %s", payload.get("error"))
            return None
        _token_cache["token"] = token
        _token_cache["expires_at"] = now + float(payload.get("expires_in", 3600)) - 60
        return token


def _fetch_json(url: str) -> dict:
    headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
    token = _get_access_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # A stale/invalid token returns 401; drop it so the next call re-auths.
        if exc.code == 401:
            with _token_lock:
                _token_cache["token"] = None
                _token_cache["expires_at"] = 0.0
        raise
