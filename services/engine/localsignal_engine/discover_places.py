import json
import os
import time
import urllib.parse
import urllib.request

from localsignal_engine.db import upsert_places_from_discovery


TARGETS = [
    ("Fort Lee", "Main Street"),
    ("Fort Lee", "Hudson Lights"),
    ("Edgewater", "River Road"),
    ("Palisades Park", "Broad Avenue"),
]

QUERIES = [
    ("restaurant", "restaurants"),
    ("cafe", "cafes coffee"),
    ("bakery", "bakery dessert"),
    ("dessert", "dessert"),
    ("korean restaurant", "Korean food"),
    ("late night restaurant", "late night food"),
    ("new restaurant", "new restaurant opening"),
]


def main() -> None:
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is required to discover places.")

    discovered = _discover(api_key)
    written = upsert_places_from_discovery(discovered)
    print(f"Discovered {len(discovered)} candidate place(s); upserted {written} place row(s).")
    for place in discovered[:40]:
        print(f"{place['city']} | {place['category']} | {place['name']} | {place.get('address') or ''}")


def _discover(api_key: str) -> list[dict]:
    by_google_id: dict[str, dict] = {}
    for city, neighborhood in TARGETS:
        for category, query in QUERIES:
            for result in _search(api_key, f"{query} in {city} NJ"):
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
            time.sleep(0.2)
    return sorted(by_google_id.values(), key=lambda place: (place["city"], place["category"], place["name"]))


def _search(api_key: str, query: str) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "fields": "name,formatted_address,place_id,geometry,types,business_status",
            "key": api_key,
        }
    )
    url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?{params}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") not in {"OK", "ZERO_RESULTS"}:
        print(f"Google Places discovery query failed for {query}: {payload.get('status')} {payload.get('error_message', '')}")
        return []
    return [result for result in payload.get("results", []) if result.get("business_status") != "CLOSED_PERMANENTLY"]


def _looks_local(result: dict, city: str) -> bool:
    address = (result.get("formatted_address") or "").lower()
    return city.lower() in address and " nj" in address


def _category_for(query_category: str, types: list[str]) -> str:
    type_set = set(types)
    if "bakery" in type_set:
        return "bakery"
    if "cafe" in type_set or query_category == "cafe":
        return "cafe"
    if query_category in {"bakery", "dessert"}:
        return query_category
    if "restaurant" in type_set:
        return "restaurant"
    return query_category


if __name__ == "__main__":
    main()
