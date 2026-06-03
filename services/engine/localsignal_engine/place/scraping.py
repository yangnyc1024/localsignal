import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any, Optional

from .schema import ensure_place_knowledge_schema
from .documents import DOCUMENT_MIN_CHARS, upsert_place_document, _clean_text


def _review_time(review: dict) -> Optional[datetime]:
    value = review.get("time")
    return datetime.fromtimestamp(value, tz=timezone.utc) if value else None


def _maps_url(google_place_id: Optional[str]) -> Optional[str]:
    return f"https://www.google.com/maps/place/?q=place_id:{google_place_id}" if google_place_id else None


def _string_list(value: Any) -> list:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)][:12]


def _clean_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        return [_clean_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_clean_json_value(item) for item in value]
    if isinstance(value, dict):
        return {_clean_text(key): _clean_json_value(item) for key, item in value.items()}
    return value


def _dedupe_display_values(values: Any) -> list:
    if not isinstance(values, list):
        return []
    cleaned: list = []
    seen: set = set()
    for value in values:
        text = _clean_text(value or "")
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        import json
        return json.loads(response.read().decode("utf-8"))


def _google_place_details(place: dict, api_key: str) -> dict:
    if place.get("google_place_id"):
        params = urllib.parse.urlencode(
            {
                "place_id": place["google_place_id"],
                "fields": "name,place_id,formatted_address,types,rating,user_ratings_total,price_level,opening_hours,editorial_summary,reviews,website,url",
                "reviews_sort": "newest",
                "reviews_no_translations": "true",
                "key": api_key,
            }
        )
        url = f"https://maps.googleapis.com/maps/api/place/details/json?{params}"
    else:
        params = urllib.parse.urlencode({"query": f"{place['name']} {place.get('address') or ''} {place['city']}", "key": api_key})
        try:
            payload = _fetch_json(f"https://maps.googleapis.com/maps/api/place/textsearch/json?{params}")
        except OSError:
            return {}
        candidate = next(iter(payload.get("results") or []), {})
        if not candidate.get("place_id"):
            return candidate or {}
        return _google_place_details({**place, "google_place_id": candidate["place_id"]}, api_key)
    try:
        payload = _fetch_json(url)
    except OSError:
        return {}
    return payload.get("result") or {}


def _google_profile_content(result: dict) -> str:
    parts = [
        result.get("name"),
        result.get("formatted_address"),
        "Categories: " + ", ".join(result.get("types") or []) if result.get("types") else "",
        f"Rating: {result.get('rating')} from {result.get('user_ratings_total')} reviews"
        if result.get("rating") and result.get("user_ratings_total")
        else "",
        "Hours: " + "; ".join((result.get("opening_hours") or {}).get("weekday_text") or []),
        ((result.get("editorial_summary") or {}).get("overview") or ""),
        f"Website: {result.get('website')}" if result.get("website") else "",
    ]
    return _clean_text(" | ".join(part for part in parts if part))


# Third-party ordering / menu platforms that cannot be scraped for useful content.
_THIRD_PARTY_MENU_DOMAINS = {
    "toasttab.com", "square.site", "squareup.com", "grubhub.com",
    "doordash.com", "ubereats.com", "chownow.com", "olo.com",
    "bentobox.com", "owner.com", "popmenu.com", "order.online",
    "allset.com", "slice.com", "opentable.com", "resy.com",
    "restaurantji.com", "menupages.com",
}


def _is_third_party_menu_url(url: str) -> bool:
    """Return True if the URL belongs to a known third-party ordering/menu platform."""
    try:
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in _THIRD_PARTY_MENU_DOMAINS)


def _website_candidate_urls(url: str) -> list:
    root = url.rstrip("/")
    candidates = [root]
    parsed = urllib.parse.urlparse(root)
    for path in ["/about", "/about-us", "/menu", "/menus", "/order", "/order-online"]:
        candidates.append(urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")))
    return candidates


def _website_content_type(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower().strip("/")
    if not path or path in {"about", "about-us", "our-story", "story"}:
        return "official_description"
    if "menu" in path or "order" in path:
        return "menu"
    return "website"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._in_title = False
        self.title = ""
        self.parts: list = []

    @property
    def text(self) -> str:
        return " ".join(self.parts)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        cleaned = _clean_text(data)
        if not cleaned:
            return
        if self._in_title:
            self.title = cleaned[:240]
        elif len(cleaned) > 2:
            self.parts.append(cleaned)


def _fetch_webpage(url: str) -> Optional[tuple]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "LocalSignalBot/0.1"})
        with urllib.request.urlopen(request, timeout=12) as response:
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                return None
            html = response.read(1_000_000).decode("utf-8", errors="ignore")
    except OSError:
        return None
    parser = _TextExtractor()
    parser.feed(html)
    text = _clean_text(parser.text)
    if len(text) < DOCUMENT_MIN_CHARS:
        return None
    return parser.title, text[:8000]


def _places(conn, place_ids: Optional[list]) -> list:
    if place_ids:
        return conn.execute(
            """
            SELECT id::text, name, category, address, city, neighborhood, google_place_id, map_url
            FROM places
            WHERE id = ANY(%s)
            ORDER BY name
            """,
            (place_ids,),
        ).fetchall()
    return conn.execute(
        """
        SELECT id::text, name, category, address, city, neighborhood, google_place_id, map_url
        FROM places
        ORDER BY name
        LIMIT 200
        """
    ).fetchall()


def ingest_google_place_documents(conn, place_ids: Optional[list] = None) -> int:
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        return 0
    ensure_place_knowledge_schema(conn)
    rows = _places(conn, place_ids)
    written = 0
    for place in rows:
        result = _google_place_details(place, api_key)
        if not result:
            continue
        profile_content = _google_profile_content(result)
        if profile_content:
            if upsert_place_document(
                conn,
                place_id=place["id"],
                source="google_places",
                source_url=result.get("url") or _maps_url(result.get("place_id")),
                title=f"Official context for {result.get('name') or place['name']}",
                content=profile_content,
                content_type="official_description",
                metadata={
                    "source_type": "official_context",
                    "claim_type": "self_or_platform_description",
                    "trust_level": "context_only",
                    "types": result.get("types") or [],
                    "website": result.get("website"),
                    "opening_hours": result.get("opening_hours") or {},
                },
            ):
                written += 1
            if upsert_place_document(
                conn,
                place_id=place["id"],
                source="google_places",
                source_url=result.get("url") or _maps_url(result.get("place_id")),
                title=f"Google profile for {result.get('name') or place['name']}",
                content=profile_content,
                content_type="place_profile",
                metadata={
                    "types": result.get("types") or [],
                    "rating": result.get("rating"),
                    "user_ratings_total": result.get("user_ratings_total"),
                    "price_level": result.get("price_level"),
                    "website": result.get("website"),
                    "opening_hours": result.get("opening_hours") or {},
                },
            ):
                written += 1
        for review in result.get("reviews") or []:
            text = _clean_text(review.get("text") or "")
            if len(text) < 30:
                continue
            if upsert_place_document(
                conn,
                place_id=place["id"],
                source="google_reviews",
                source_url=result.get("url") or _maps_url(result.get("place_id")),
                title=f"Google review for {result.get('name') or place['name']}",
                content=text,
                content_type="review",
                occurred_at=_review_time(review),
                metadata={"rating": review.get("rating"), "author_name": review.get("author_name")},
            ):
                written += 1
    return written


def ingest_website_documents(conn, place_ids: Optional[list] = None) -> int:
    ensure_place_knowledge_schema(conn)
    rows = conn.execute(
        """
        SELECT DISTINCT ON (pd.place_id)
          pd.place_id::text AS place_id,
          p.name,
          pd.metadata->>'website' AS website
        FROM place_documents pd
        JOIN places p ON p.id = pd.place_id
        WHERE pd.source = 'google_places'
          AND pd.metadata ? 'website'
          AND pd.metadata->>'website' <> ''
          AND (%s::uuid[] IS NULL OR pd.place_id = ANY(%s::uuid[]))
        ORDER BY pd.place_id, pd.fetched_at DESC
        """,
        (place_ids, place_ids),
    ).fetchall()
    written = 0
    for row in rows:
        for url in _website_candidate_urls(row["website"]):
            # Detect third-party menu platforms — skip scraping, record link instead.
            if _is_third_party_menu_url(url):
                if upsert_place_document(
                    conn,
                    place_id=row["place_id"],
                    source="website",
                    source_url=url,
                    title=f"Menu link for {row['name']}",
                    content=f"Menu is hosted on a third-party platform: {url}",
                    content_type="menu_external_link",
                    metadata={"website_root": row["website"], "third_party": True},
                ):
                    written += 1
                continue

            page = _fetch_webpage(url)
            if not page:
                continue
            title, text = page

            # Also detect if the fetched page redirected to a third-party platform.
            if _is_third_party_menu_url(url):
                if upsert_place_document(
                    conn,
                    place_id=row["place_id"],
                    source="website",
                    source_url=url,
                    title=f"Menu link for {row['name']}",
                    content=f"Menu is hosted on a third-party platform: {url}",
                    content_type="menu_external_link",
                    metadata={"website_root": row["website"], "third_party": True},
                ):
                    written += 1
                continue

            content_type = _website_content_type(url)
            metadata: dict[str, Any] = {"website_root": row["website"]}
            if content_type == "official_description":
                metadata.update(
                    {
                        "source_type": "official",
                        "claim_type": "self_description",
                        "trust_level": "context_only",
                    }
                )
            if upsert_place_document(
                conn,
                place_id=row["place_id"],
                source="website",
                source_url=url,
                title=title or f"{row['name']} website",
                content=text,
                content_type=content_type,
                metadata=metadata,
            ):
                written += 1
    return written


def ingest_apify_google_reviews(conn, place_ids: Optional[list] = None) -> int:
    """Fetch full Google Maps reviews via Apify and store as place_documents.

    This supplements ingest_google_place_documents() which is limited to
    5 reviews by the Places API. Requires APIFY_TOKEN env var.
    """
    from localsignal_engine.ingestion.apify_google_reviews import fetch_google_reviews

    ensure_place_knowledge_schema(conn)
    rows = _places(conn, place_ids)
    if not rows:
        return 0

    from localsignal_engine.models import Place
    places = [
        Place(
            id=row["id"],
            name=row["name"],
            category=row.get("category", "food"),
            city=row.get("city", ""),
            neighborhood=row.get("neighborhood"),
            google_place_id=row.get("google_place_id"),
        )
        for row in rows
        if row.get("google_place_id")
    ]
    if not places:
        return 0

    records = fetch_google_reviews(places)
    written = 0
    for record in records:
        text = _clean_text(record.get("text") or "")
        if len(text) < 30:
            continue
        if upsert_place_document(
            conn,
            place_id=record["place_id"],
            source="google_reviews_apify",
            source_url=record.get("review_url") or "",
            title="Google review (Apify)",
            content=text,
            content_type="review",
            occurred_at=record.get("published_at"),
            metadata={
                "rating": record.get("rating"),
                "author_name": record.get("author_name"),
                "source": "apify_google_maps_reviews",
            },
        ):
            written += 1
    return written
