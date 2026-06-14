"""Resolve restaurants' official Instagram handles via Apify Google Search.

The restaurant-brief web_search tool cannot surface instagram.com links (the
search backend filters them), so handle resolution runs as a dedicated step:
google "<name> <city> instagram", take the first instagram.com/<user> organic
result, and keep it only if the username plausibly matches the place name.
"""
import json
import logging
import os
import re
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .schema import ensure_place_knowledge_schema

logger = logging.getLogger(__name__)

GOOGLE_SEARCH_ACTOR = "apify~google-search-scraper"

# Instagram usernames: letters/digits/period/underscore. Require >=2 chars so
# truncated junk like 'N/A' -> 'N' is rejected (real restaurant handles are longer).
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{2,30}$")
_HANDLE_BLOCKLIST = {
    "", "n/a", "na", "none", "null", "unknown", "instagram", "explore",
    "p", "reel", "reels", "accounts", "about", "tv", "stories", "directory",
}
_INSTAGRAM_URL_RE = re.compile(r"instagram\.com/([A-Za-z0-9._]+)", re.IGNORECASE)


def sanitize_instagram_handle(value) -> str:
    """Normalize a handle/URL to a bare username, or '' if invalid/blocklisted."""
    handle = str(value or "").strip()
    if not handle:
        return ""
    match = _INSTAGRAM_URL_RE.search(handle)
    if match:
        handle = match.group(1)
    handle = handle.lstrip("@").strip().strip("/").split("?")[0].split("/")[0]
    if handle.lower() in _HANDLE_BLOCKLIST or not _HANDLE_RE.match(handle):
        return ""
    return handle


def _name_tokens(name: str) -> set:
    stop = {"the", "and", "cafe", "café", "restaurant", "bakery", "bar", "grill", "kitchen", "house", "co", "nj"}
    return {t for t in re.split(r"[^a-z0-9]+", name.lower()) if len(t) >= 3 and t not in stop}


def _handle_matches_place(handle: str, place_name: str) -> bool:
    """Loose check that a handle plausibly belongs to the place.

    Compares the alphanumeric run of the handle against the place's name
    tokens; a single shared token (>=3 chars) is enough, since handles often
    compress or abbreviate the name (e.g. 'umacha_official' for 'Ümacha').
    """
    handle_blob = re.sub(r"[^a-z0-9]", "", handle.lower())
    tokens = _name_tokens(place_name)
    if not tokens:
        return True
    return any(tok in handle_blob for tok in tokens)


def _candidate_handles(organic_results: list) -> list:
    handles: list = []
    for result in organic_results or []:
        blob = " ".join(str(result.get(k) or "") for k in ("url", "displayedUrl", "description", "title"))
        for raw in _INSTAGRAM_URL_RE.findall(blob):
            cleaned = sanitize_instagram_handle(raw)
            if cleaned and cleaned not in handles:
                handles.append(cleaned)
    return handles


def _run_google_search(token: str, queries: list[str], max_charge: float) -> list[dict]:
    actor_input = {
        "queries": "\n".join(queries),
        "resultsPerPage": 10,
        "maxPagesPerQuery": 1,
        "countryCode": "us",
    }
    query = urlencode({"maxTotalChargeUsd": str(max_charge)})
    request = Request(
        f"https://api.apify.com/v2/acts/{GOOGLE_SEARCH_ACTOR}/run-sync-get-dataset-items?{query}",
        data=json.dumps(actor_input).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=240) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


def _places_needing_handles(conn, place_ids: Optional[list]) -> list[dict]:
    if place_ids:
        rows = conn.execute(
            """
            SELECT p.id::text AS id, p.name, p.city
            FROM places p
            LEFT JOIN place_profiles pp ON pp.place_id = p.id
            WHERE p.id = ANY(%s) AND COALESCE(pp.instagram_handle, '') = ''
            """,
            (place_ids,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT p.id::text AS id, p.name, p.city
            FROM places p
            LEFT JOIN place_profiles pp ON pp.place_id = p.id
            WHERE COALESCE(pp.instagram_handle, '') = ''
            """
        ).fetchall()
    return [dict(r) for r in rows]


def set_instagram_handle(conn, place_id: str, handle: str) -> None:
    """Persist a resolved handle, creating a minimal profile row if needed."""
    ensure_place_knowledge_schema(conn)
    conn.execute(
        """
        INSERT INTO place_profiles (place_id, instagram_handle, updated_at)
        VALUES (%s, %s, now())
        ON CONFLICT (place_id)
        DO UPDATE SET instagram_handle = EXCLUDED.instagram_handle, updated_at = now()
        """,
        (place_id, handle),
    )


def resolve_instagram_handles(conn, place_ids: Optional[list] = None, batch_size: int = 10) -> dict:
    """Resolve and store Instagram handles for places that don't have one yet.

    Returns metrics. Skips silently (enabled=False) when APIFY_TOKEN is missing
    or the feature is disabled. Each Apify search run is charge-capped.
    """
    if os.getenv("PLACE_INSTAGRAM_HANDLE_RESOLVE_ENABLED", "true").lower() != "true":
        return {"enabled": False, "reason": "disabled"}
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        return {"enabled": False, "reason": "missing_apify_token"}

    ensure_place_knowledge_schema(conn)
    places = _places_needing_handles(conn, place_ids)
    if not places:
        return {"enabled": True, "candidates": 0, "resolved": 0}

    max_charge = float(os.getenv("PLACE_INSTAGRAM_HANDLE_MAX_CHARGE_USD", "1.0"))
    limit = int(os.getenv("PLACE_INSTAGRAM_HANDLE_MAX_PLACES", "40"))
    places = places[:limit]

    resolved = 0
    skipped = 0
    for start in range(0, len(places), batch_size):
        batch = places[start:start + batch_size]
        queries = [f"{p['name']} {p.get('city') or ''} instagram".strip() for p in batch]
        try:
            results = _run_google_search(token, queries, max_charge)
        except Exception as exc:
            logger.warning("Instagram handle search failed for batch: %s", exc)
            continue
        # Map each result back to its place by query term order/text.
        by_term = {str((r.get("searchQuery") or {}).get("term") or ""): r for r in results}
        for place, query in zip(batch, queries):
            result = by_term.get(query) or _best_effort_match(query, results)
            handle = _pick_handle(result, place["name"]) if result else ""
            if handle:
                set_instagram_handle(conn, place["id"], handle)
                resolved += 1
                logger.info("Resolved Instagram handle for %s -> @%s", place["name"], handle)
            else:
                skipped += 1
        conn.commit()

    return {"enabled": True, "candidates": len(places), "resolved": resolved, "skipped": skipped}


def _best_effort_match(query: str, results: list[dict]) -> Optional[dict]:
    for result in results:
        if str((result.get("searchQuery") or {}).get("term") or "") == query:
            return result
    return None


def _pick_handle(result: dict, place_name: str) -> str:
    for handle in _candidate_handles(result.get("organicResults") or []):
        if _handle_matches_place(handle, place_name):
            return handle
    return ""
