import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from localsignal_engine.ingestion.social_metadata import SocialMetadataItem, parse_social_metadata_records
from localsignal_engine.models import Place
from localsignal_engine.db import record_social_source_run


def fetch_apify_social_metadata_items(places: list[Place]) -> tuple[list[SocialMetadataItem], dict[str, int]]:
    token = os.getenv("APIFY_TOKEN", "").strip()
    dataset_ids = _csv("APIFY_SOCIAL_DATASET_IDS")
    if not token or not dataset_ids:
        return [], {}

    max_items = int(os.getenv("APIFY_SOCIAL_MAX_ITEMS", "200"))
    all_items: list[SocialMetadataItem] = []
    source_counts: dict[str, int] = {}

    for dataset_id in dataset_ids:
        try:
            records = _fetch_dataset_items(dataset_id, token, max_items)
        except Exception as exc:
            print(f"apify dataset {dataset_id} failed: {exc}", flush=True)
            _record_apify_run(dataset_id=dataset_id, status="failed", error=str(exc))
            continue
        normalized_records = [
            normalized
            for record in records
            if isinstance(record, dict)
            for normalized in _expand_record(record, dataset_id)
        ]
        fresh_records, old_count = _filter_recent_records(normalized_records)
        items = parse_social_metadata_records(fresh_records, "social_metadata", places)
        dataset_source_counts = _source_counts(items)
        resolved_count = sum(1 for item in items if item.resolution_status == "resolved")
        review_count = sum(1 for item in items if item.resolution_status == "review")
        unresolved_count = sum(1 for item in items if item.resolution_status == "unresolved")
        _record_apify_run(
            dataset_id=dataset_id,
            platform=_dominant_platform(dataset_source_counts),
            status="succeeded",
            total_records=len(records),
            normalized_records=len(normalized_records),
            fresh_records=len(fresh_records),
            old_records_dropped=old_count,
            parsed_items=len(items),
            resolved_items=resolved_count,
            review_items=review_count,
            unresolved_items=unresolved_count,
            source_counts=dataset_source_counts,
        )
        print(
            f"apify dataset {dataset_id} produced {len(items)} social raw item(s) "
            f"after dropping {old_count} old item(s).",
            flush=True,
        )
        all_items.extend(items)
        for source, count in dataset_source_counts.items():
            source_counts[source] = source_counts.get(source, 0) + count

    return all_items, source_counts


def _filter_recent_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    max_age_days = int(os.getenv("SOCIAL_MAX_AGE_DAYS", os.getenv("APIFY_SOCIAL_MAX_AGE_DAYS", "45")))
    if max_age_days <= 0:
        return records, 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    fresh: list[dict[str, Any]] = []
    old_count = 0
    for record in records:
        occurred_at = _parse_timestamp(_first(record, ["occurred_at", "timestamp", "created_at", "published_at", "taken_at", "createTimeISO", "date", "time"]))
        if occurred_at is None or occurred_at >= cutoff:
            fresh.append(record)
        else:
            old_count += 1
    return fresh, old_count


def _parse_timestamp(value: str) -> Optional[datetime]:
    if not value:
        return None
    normalized = str(value).strip().replace("Z", "+00:00")
    try:
        if normalized.isdigit():
            return datetime.fromtimestamp(int(normalized), tz=timezone.utc)
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _expand_record(record: dict[str, Any], dataset_id: str) -> list[dict[str, Any]]:
    posts = record.get("posts")
    if not isinstance(posts, list) or not posts:
        return [_normalize_record(record, dataset_id)]

    expanded: list[dict[str, Any]] = []
    parent_place = _first(record, ["name", "place_name", "locationName", "location_name", "venue", "poiName", "poi_name"])
    possible_names = [value for value in [parent_place, record.get("slug")] if value]
    for post in posts:
        if not isinstance(post, dict):
            continue
        location = post.get("location") if isinstance(post.get("location"), dict) else {}
        user = post.get("user") if isinstance(post.get("user"), dict) else {}
        code = _first(post, ["code", "shortCode", "shortcode"])
        caption = post.get("caption")
        caption_text = ""
        if isinstance(caption, dict):
            caption_text = str(caption.get("text") or "").strip()
        elif caption is not None:
            caption_text = str(caption).strip()

        normalized = dict(record)
        normalized.update(post)
        normalized["source"] = "instagram"
        normalized["source_url"] = f"https://www.instagram.com/p/{code}/" if code else _first(record, ["url", "inputUrl", "source_url"])
        normalized["caption"] = caption_text or _first(post, ["text", "description", "title"])
        normalized["occurred_at"] = post.get("taken_at") or _first(post, ["timestamp", "created_at", "published_at"])
        normalized["place_name"] = str(location.get("name") or parent_place or "").strip()
        normalized["possible_place_names"] = [*possible_names, str(location.get("name") or "").strip()]
        normalized["lat"] = location.get("lat") if location.get("lat") is not None else record.get("lat")
        normalized["lng"] = location.get("lng") if location.get("lng") is not None else record.get("lng")
        normalized["likes"] = post.get("like_count") if post.get("like_count") is not None else post.get("likesCount")
        normalized["comments"] = post.get("comment_count") if post.get("comment_count") is not None else post.get("commentsCount")
        normalized["author_id"] = str(user.get("username") or user.get("id") or "").strip() or _first(record, ["ownerUsername", "username"])
        normalized["collection_method"] = "apify_dataset_export"
        normalized["collector"] = f"apify:{dataset_id}"
        expanded.append(_normalize_record(normalized, dataset_id))
    return expanded


def _fetch_dataset_items(dataset_id: str, token: str, limit: int) -> list[dict[str, Any]]:
    query = urlencode({"clean": "true", "format": "json", "limit": str(limit)})
    request = Request(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


def _normalize_record(record: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    normalized = dict(record)
    normalized.setdefault("collection_method", "apify_dataset_export")
    normalized.setdefault("collector", f"apify:{dataset_id}")

    url = _first(normalized, ["source_url", "url", "postUrl", "post_url", "webVideoUrl", "videoWebUrl", "inputUrl", "permalink"])
    if url and "source_url" not in normalized:
        normalized["source_url"] = url

    text = _first(normalized, ["caption", "text", "description", "title", "note_title", "desc", "videoDescription"])
    if text and "caption" not in normalized:
        normalized["caption"] = text

    timestamp = _first(normalized, ["occurred_at", "timestamp", "created_at", "published_at", "taken_at", "createTimeISO", "date", "time"])
    if timestamp and "occurred_at" not in normalized:
        normalized["occurred_at"] = timestamp

    location = _first(normalized, ["place_name", "locationName", "location_name", "venue", "poiName", "poi_name"])
    if location and "place_name" not in normalized:
        normalized["place_name"] = location


    if "author_id" not in normalized:
        author = _first(normalized, ["author_id", "username", "ownerUsername", "ownerId", "ownerFullName"])
        if author:
            normalized["author_id"] = author

    _copy_metric(normalized, "likesCount", "likes")
    _copy_metric(normalized, "commentsCount", "comments")
    _copy_metric(normalized, "videoViewCount", "views")
    _copy_metric(normalized, "videoPlayCount", "views")
    _copy_metric(normalized, "viewCount", "views")

    if "source" not in normalized:
        normalized["source"] = _infer_source(url, dataset_id)

    return normalized


def _copy_metric(record: dict[str, Any], source_key: str, target_key: str) -> None:
    if target_key not in record and record.get(source_key) is not None:
        record[target_key] = record[source_key]


def _infer_source(url: str, dataset_id: str) -> str:
    value = f"{url} {dataset_id}".lower()
    if "xiaohongshu" in value or "xhs" in value or "rednote" in value:
        return "xhs"
    if "tiktok" in value or "douyin" in value:
        return "tiktok"
    if "instagram" in value:
        return "instagram"
    return "social_metadata"


def _first(record: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _source_counts(items: list[SocialMetadataItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.platform] = counts.get(item.platform, 0) + 1
    return counts


def _dominant_platform(source_counts: dict[str, int]) -> str:
    if not source_counts:
        return "social_metadata"
    return max(source_counts.items(), key=lambda item: item[1])[0]


def _record_apify_run(**kwargs: Any) -> None:
    try:
        record_social_source_run(provider="apify", **kwargs)
    except Exception as exc:
        print(f"apify source run logging failed: {exc}", flush=True)
