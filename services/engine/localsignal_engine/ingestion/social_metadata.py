import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from localsignal_engine.models import Place


@dataclass(frozen=True)
class SocialMetadataItem:
    platform: str
    url: Optional[str]
    author_id: Optional[str]
    place_id: Optional[str]
    text: str
    occurred_at: datetime
    engagement_metrics: dict[str, Any]
    geo_metadata: dict[str, Any]
    raw_json: dict[str, Any]
    place_resolution_confidence: float
    resolution_status: str


def load_social_metadata_items(path: str, source: str, places: list[Place]) -> list[SocialMetadataItem]:
    records = _records_from_path(Path(path))
    return parse_social_metadata_records(records, source, places)


def parse_social_metadata_records(records: list[dict[str, Any]], source: str, places: list[Place]) -> list[SocialMetadataItem]:
    items: list[SocialMetadataItem] = []

    for record in records:
        text = _body(record)
        if not text:
            continue
        place, confidence, status = _resolve_place(record, places)
        platform = _platform(record.get("source") or record.get("platform") or source)
        geo_metadata = _geo_metadata(record)
        if place and place.city and "city" not in geo_metadata:
            geo_metadata["city"] = place.city
        if place and place.neighborhood and "neighborhood" not in geo_metadata:
            geo_metadata["neighborhood"] = place.neighborhood
        items.append(
            SocialMetadataItem(
                platform=platform,
                url=_first(record, ["source_url", "url", "permalink", "post_url", "media_url"]),
                author_id=_first(record, ["author_id", "username", "handle", "creator", "account"]),
                place_id=place.id if place else None,
                text=text,
                occurred_at=_timestamp(record),
                engagement_metrics=_engagement(record),
                geo_metadata=geo_metadata,
                raw_json=record,
                place_resolution_confidence=confidence,
                resolution_status=status,
            )
        )

    return items


def _records_from_path(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        records: list[dict[str, Any]] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
        return records
    payload = json.loads(path.read_text())
    return _records(payload)


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        for key in ["items", "records", "data", "posts", "notes", "videos", "media"]:
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
        return [payload]
    return []

def _resolve_place(record: dict[str, Any], places: list[Place]) -> tuple[Optional[Place], float, str]:
    place_id = str(record.get("place_id") or "").strip()
    if place_id:
        place = next((candidate for candidate in places if candidate.id == place_id), None)
        return (place, 1.0, "resolved") if place else (None, 0.0, "unresolved")

    lat = _float(record.get("lat") or record.get("latitude"))
    lng = _float(record.get("lng") or record.get("longitude"))
    if lat is not None and lng is not None:
        nearest = _nearest_place(lat, lng, places)
        if nearest:
            place, distance_km = nearest
            if distance_km <= 0.08:
                return place, 0.95, "resolved"
            if distance_km <= 0.25:
                return place, 0.72, "review"

    explicit_values = [
        record.get("place_name"),
        record.get("venue"),
        record.get("location_name"),
        record.get("business_name"),
        _nested(record, "place", "name"),
        _nested(record, "location", "name"),
    ]
    possible_names = record.get("possible_place_names") or record.get("candidate_place_names") or []
    if isinstance(possible_names, list):
        explicit_values.extend(possible_names)
    explicit_hint = " ".join(str(value).lower() for value in explicit_values if value)
    caption_hint = " ".join(
        str(value).lower()
        for value in [
            record.get("caption"),
            record.get("text"),
            record.get("body"),
            record.get("description"),
            record.get("title"),
            record.get("note_title"),
            record.get("ocr_text"),
        ]
        if value
    )
    combined = f"{explicit_hint} {caption_hint}".strip()

    for place in places:
        names = [place.name.lower()]
        if place.neighborhood:
            names.append(f"{place.name} {place.neighborhood}".lower())
        if explicit_hint and any(name in explicit_hint for name in names):
            return place, 0.95, "resolved"
        if caption_hint and any(name in caption_hint for name in names):
            return place, 0.88, "resolved"

    token_match = _best_token_match(combined, places)
    if token_match:
        place, confidence = token_match
        return place, confidence, "resolved" if confidence >= 0.85 else "review"

    return None, 0.0, "unresolved"


def _best_token_match(text: str, places: list[Place]) -> Optional[tuple[Place, float]]:
    if not text:
        return None
    tokens = set(_tokens(text))
    best: Optional[tuple[Place, float]] = None
    stopwords = {"the", "and", "bbq", "cafe", "coffee", "company", "house", "bar", "grill", "kitchen", "bistro"}
    for place in places:
        name_tokens = [token for token in _tokens(place.name) if token not in stopwords]
        if not name_tokens:
            continue
        overlap = sum(1 for token in name_tokens if token in tokens)
        if overlap < min(2, len(name_tokens)):
            continue
        area_bonus = 0.1 if place.city.lower() in text or (place.neighborhood and place.neighborhood.lower() in text) else 0
        # Hashtag bonus: Instagram posts often have #PlaceName hashtags
        hashtag_text = text.replace("#", " ").replace("_", " ")
        hashtag_bonus = 0.08 if place.name.lower().replace(" ", "") in hashtag_text.replace(" ", "") else 0
        confidence = min(0.92, 0.60 + (overlap / len(name_tokens) * 0.25) + area_bonus + hashtag_bonus)
        if not best or confidence > best[1]:
            best = (place, confidence)
    return best


def _body(record: dict[str, Any]) -> str:
    text = _first(record, ["body", "caption", "text", "description", "title", "note_title"])
    ocr_text = _first(record, ["ocr_text", "image_text", "transcript"])
    if not text and not ocr_text:
        return ""
    parts = [part for part in [text, f"ocr text: {ocr_text}" if ocr_text else None] if part]
    menu_item = _first(record, ["menu_item", "dish", "item"])
    if menu_item:
        parts.append(f"mentioned item: {menu_item}")
    location = _first(record, ["place_name", "venue", "location_name", "business_name"]) or _nested(record, "place", "name") or _nested(record, "location", "name")
    if location:
        parts.append(f"place hint: {location}")
    hashtags = record.get("hashtags") or record.get("tags")
    if isinstance(hashtags, list) and hashtags:
        parts.append("hashtags: " + " ".join(str(tag) for tag in hashtags[:8]))
    possible_names = record.get("possible_place_names") or record.get("candidate_place_names")
    if isinstance(possible_names, list) and possible_names:
        parts.append("possible place names: " + " | ".join(str(name) for name in possible_names[:5]))
    return " | ".join(parts)


def _timestamp(record: dict[str, Any]) -> datetime:
    value = _first(record, ["occurred_at", "timestamp", "created_at", "published_at", "taken_at"])
    if not value:
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    normalized = str(value).strip().replace("Z", "+00:00")
    if normalized.isdigit():
        return datetime.fromtimestamp(int(normalized), tz=timezone.utc)
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _engagement(record: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "likes",
        "like_count",
        "comments",
        "comment_count",
        "views",
        "view_count",
        "plays",
        "play_count",
        "shares",
        "share_count",
        "saves",
        "save_count",
    ]
    return {key: record[key] for key in keys if key in record and record[key] is not None}


def _geo_metadata(record: dict[str, Any]) -> dict[str, Any]:
    keys = ["city", "neighborhood", "region", "lat", "lng", "latitude", "longitude", "location_name", "poi_name"]
    metadata = {key: record[key] for key in keys if key in record and record[key] is not None}
    if "latitude" in metadata and "lat" not in metadata:
        metadata["lat"] = metadata.pop("latitude")
    if "longitude" in metadata and "lng" not in metadata:
        metadata["lng"] = metadata.pop("longitude")
    return metadata


def _nearest_place(lat: float, lng: float, places: list[Place]) -> Optional[tuple[Place, float]]:
    candidates = [
        (place, _distance_km(lat, lng, place.latitude, place.longitude))
        for place in places
        if place.latitude is not None and place.longitude is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[1])


def _distance_km(lat1: float, lng1: float, lat2: Optional[float], lng2: Optional[float]) -> float:
    if lat2 is None or lng2 is None:
        return 999
    radius = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))



def _platform(value: Optional[str]) -> str:
    normalized = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "xhs": "xiaohongshu",
        "小红书": "xiaohongshu",
        "rednote": "xiaohongshu",
        "red_note": "xiaohongshu",
        "tiktok": "tiktok_metadata",
        "douyin": "tiktok_metadata",
        "抖音": "tiktok_metadata",
        "ig": "instagram",
        "instagram_reel": "instagram",
        "instagram_post": "instagram",
    }
    return aliases.get(normalized, normalized or "social_metadata")


def _nested(record: dict[str, Any], parent: str, child: str) -> Optional[str]:
    value = record.get(parent)
    if isinstance(value, dict) and value.get(child) is not None and str(value.get(child)).strip():
        return str(value[child]).strip()
    return None

def _first(record: dict[str, Any], keys: list[str]) -> Optional[str]:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tokens(value: str) -> list[str]:
    return [token for token in value.lower().replace("&", " ").replace("-", " ").split() if token]
