import json
import os
import time
import urllib.parse
import urllib.request

from localsignal_engine.db import upsert_places_from_discovery


# ---------------------------------------------------------------------------
# Search targets — city + neighbourhood label used for neighbourhood field
# ---------------------------------------------------------------------------

TARGETS = [
    ("Fort Lee", "Main Street"),
    ("Fort Lee", "Hudson Lights"),
    ("Fort Lee", "Anderson Avenue"),
    ("Fort Lee", "Bergen Boulevard"),
    ("Edgewater", "River Road"),
    ("Palisades Park", "Broad Avenue"),
    ("Palisades Park", "Fort Lee Road"),
]

# ---------------------------------------------------------------------------
# Query definitions — (internal_category, search_query_suffix)
# Internal category is used by _category_for() to assign a fine-grained label.
# ---------------------------------------------------------------------------

QUERIES = [
    ("restaurant",              "restaurants"),
    ("cafe",                    "cafes coffee"),
    ("bakery",                  "bakery pastry bread"),
    ("dessert",                 "dessert ice cream"),
    ("korean restaurant",       "Korean restaurant"),
    ("korean bbq",              "Korean BBQ samgyupsal"),
    ("japanese restaurant",     "Japanese ramen sushi izakaya"),
    ("chinese restaurant",      "Chinese restaurant dim sum"),
    ("seafood restaurant",      "seafood crab boil"),
    ("pizza",                   "pizza"),
    ("mediterranean restaurant","Mediterranean Turkish doner"),
    ("latin restaurant",        "Latin Caribbean Mexican"),
    ("brunch",                  "brunch breakfast"),
    ("bubble tea",              "bubble tea boba"),
    ("late night restaurant",   "late night bar food"),
]


def main() -> None:
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is required to discover places.")

    discovered = _discover(api_key)
    written = upsert_places_from_discovery(discovered)
    print(f"Discovered {len(discovered)} candidate place(s); upserted {written} place row(s).")
    for place in discovered[:60]:
        print(f"{place['city']} | {place['category']:<24} | {place['name']} | {place.get('address') or ''}")


def _discover(api_key: str) -> list[dict]:
    by_google_id: dict[str, dict] = {}
    total_queries = len(TARGETS) * len(QUERIES)
    done = 0
    for city, neighborhood in TARGETS:
        for category, query_suffix in QUERIES:
            done += 1
            query = f"{query_suffix} in {city} NJ"
            print(f"[{done}/{total_queries}] {query}")
            for result in _search(api_key, query):
                google_place_id = result.get("place_id")
                if not google_place_id or google_place_id in by_google_id:
                    continue
                if not _looks_local(result, city):
                    continue
                by_google_id[google_place_id] = {
                    "name": result.get("name"),
                    "category": _category_for(category, result.get("types") or []),
                    "address": result.get("formatted_address"),
                    "city": city,
                    "neighborhood": neighborhood,
                    "latitude": (result.get("geometry") or {}).get("location", {}).get("lat"),
                    "longitude": (result.get("geometry") or {}).get("location", {}).get("lng"),
                    "google_place_id": google_place_id,
                    "map_url": f"https://www.google.com/maps/place/?q=place_id:{google_place_id}",
                }
            time.sleep(0.3)
    return sorted(by_google_id.values(), key=lambda p: (p["city"], p["category"], p["name"]))


def _search(api_key: str, query: str) -> list[dict]:
    """Fetch up to 3 pages (60 results) from Google Places Text Search."""
    results: list[dict] = []
    params: dict = {
        "query": query,
        "fields": "name,formatted_address,place_id,geometry,types,business_status",
        "key": api_key,
    }

    for page in range(3):
        url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))

        status = payload.get("status")
        if status == "ZERO_RESULTS":
            break
        if status != "OK":
            print(f"  ⚠ Google Places query failed [{status}]: {payload.get('error_message', '')}")
            break

        page_results = [
            r for r in payload.get("results", [])
            if r.get("business_status") != "CLOSED_PERMANENTLY"
        ]
        results.extend(page_results)

        next_token = payload.get("next_page_token")
        if not next_token:
            break

        # Google requires ~2 s before next_page_token becomes valid
        time.sleep(2.2)
        params = {"pagetoken": next_token, "key": api_key}

    return results


def _looks_local(result: dict, city: str) -> bool:
    address = (result.get("formatted_address") or "").lower()
    return city.lower() in address and " nj" in address


def _category_for(query_category: str, types: list[str]) -> str:
    """
    Assign a fine-grained category.
    Google `types` are used as a secondary signal; query_category wins for
    specific cuisine labels that Google doesn't have native types for.
    """
    type_set = set(types)

    # Precise cuisine labels from the query term take priority
    if query_category == "korean bbq":
        return "korean bbq"
    if query_category == "korean restaurant":
        return "korean restaurant"
    if query_category == "japanese restaurant":
        return "japanese restaurant"
    if query_category == "chinese restaurant":
        return "chinese restaurant"
    if query_category == "seafood restaurant":
        return "seafood restaurant"
    if query_category == "mediterranean restaurant":
        return "mediterranean restaurant"
    if query_category == "latin restaurant":
        return "latin restaurant"
    if query_category == "pizza":
        return "pizza"
    if query_category == "brunch":
        return "brunch"
    if query_category == "bubble tea":
        return "cafe"
    if query_category == "late night restaurant":
        return "late night restaurant"

    # Fall back to Google types for generic queries
    if "bakery" in type_set or query_category == "bakery":
        return "bakery"
    if "cafe" in type_set or query_category == "cafe":
        return "cafe"
    if query_category == "dessert":
        return "dessert"
    if "restaurant" in type_set:
        return "restaurant"
    return query_category


if __name__ == "__main__":
    main()
