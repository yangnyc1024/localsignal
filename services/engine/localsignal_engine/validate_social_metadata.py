import json
import os
from pathlib import Path
from typing import Any


TEXT_FIELDS = ["caption", "text", "body", "description", "title", "note_title", "ocr_text", "image_text", "transcript"]
PLACE_FIELDS = ["place_id", "place_name", "venue", "location_name", "business_name"]
TIMESTAMP_FIELDS = ["occurred_at", "timestamp", "created_at", "published_at", "taken_at"]
ALLOWED_SOURCES = {"instagram", "instagram_post", "instagram_reel", "ig", "tiktok", "tiktok_metadata", "douyin", "xhs", "xiaohongshu", "rednote", "red_note", "小红书"}


def main() -> None:
    paths = _configured_paths()
    if not paths:
        print("No social metadata paths configured. Set SOCIAL_JSON_PATHS or INSTAGRAM_JSON_PATH/TIKTOK_JSON_PATH/XHS_JSON_PATH.")
        return

    total_records = 0
    total_errors = 0
    total_warnings = 0

    for path in paths:
        errors, warnings, count = _validate_path(path)
        total_records += count
        total_errors += len(errors)
        total_warnings += len(warnings)

        print(f"{path}: {count} record(s), {len(errors)} error(s), {len(warnings)} warning(s)")
        for message in errors:
            print(f"  ERROR: {message}")
        for message in warnings:
            print(f"  WARN: {message}")

    print(f"Validated {total_records} social metadata record(s): {total_errors} error(s), {total_warnings} warning(s).")
    if total_errors:
        raise SystemExit(1)


def _validate_path(raw_path: str) -> tuple[list[str], list[str], int]:
    path = _local_path(raw_path)
    errors: list[str] = []
    warnings: list[str] = []

    if not path.exists():
        return [f"file does not exist: {path}"], warnings, 0
    if path.is_dir():
        all_errors: list[str] = []
        all_warnings: list[str] = []
        total_count = 0
        files = sorted(item for item in path.glob("**/*") if item.suffix.lower() in {".json", ".jsonl"})
        if not files:
            return [f"directory contains no .json/.jsonl files: {path}"], warnings, 0
        for item in files:
            item_errors, item_warnings, item_count = _validate_path(str(item))
            all_errors.extend(f"{item}: {message}" for message in item_errors)
            all_warnings.extend(f"{item}: {message}" for message in item_warnings)
            total_count += item_count
        return all_errors, all_warnings, total_count

    try:
        records = _records_from_path(path)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"], warnings, 0
    except ValueError as exc:
        return [str(exc)], warnings, 0
    if not records:
        return ["file must contain a record object or a list/wrapper of record objects"], warnings, 0

    for index, record in enumerate(records, start=1):
        record_errors, record_warnings = _validate_record(record)
        errors.extend(f"record {index}: {message}" for message in record_errors)
        warnings.extend(f"record {index}: {message}" for message in record_warnings)

    return errors, warnings, len(records)


def _records_from_path(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"jsonl line {line_number} must be an object")
            records.append(value)
        return records
    payload = json.loads(path.read_text())
    return _records(payload)


def _validate_record(record: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    source = str(record.get("source") or record.get("platform") or "").strip()
    if not source:
        errors.append("missing source/platform")
    elif source.lower().replace("-", "_").replace(" ", "_") not in ALLOWED_SOURCES:
        warnings.append(f"unknown source/platform '{source}'")

    if not _first(record, ["source_url", "url", "permalink", "post_url", "media_url"]):
        errors.append("missing source_url/url/permalink")

    if not _first(record, TEXT_FIELDS):
        errors.append("missing caption/text/body/description/title/note_title/ocr_text")

    if not _first(record, TIMESTAMP_FIELDS):
        errors.append("missing occurred_at/timestamp/created_at/published_at/taken_at")

    if not _has_place_hint(record):
        warnings.append("missing place hint; item will likely stay unresolved until reviewed")

    if not _first(record, ["collection_method", "collection_basis", "collector"]):
        warnings.append("missing collection_method/collection_basis/collector audit field")

    if any(key in record for key in ["email", "phone", "address_book", "private_notes"]):
        errors.append("contains private/sensitive fields that should not be imported")

    return errors, warnings


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


def _has_place_hint(record: dict[str, Any]) -> bool:
    if _first(record, PLACE_FIELDS):
        return True
    possible_names = record.get("possible_place_names") or record.get("candidate_place_names")
    if isinstance(possible_names, list) and any(str(value).strip() for value in possible_names):
        return True
    location = record.get("location") or record.get("place")
    return isinstance(location, dict) and bool(str(location.get("name") or "").strip())


def _configured_paths() -> list[str]:
    raw = os.getenv("SOCIAL_JSON_PATHS", "").strip()
    paths = [item.strip() for item in raw.split(",") if item.strip()]
    directory = os.getenv("SOCIAL_JSON_DIR", "").strip()
    if directory:
        paths.append(directory)
    for name in ["INSTAGRAM_JSON_PATH", "TIKTOK_JSON_PATH", "XHS_JSON_PATH", "XIAOHONGSHU_JSON_PATH"]:
        value = os.getenv(name, "").strip()
        paths.extend(item.strip() for item in value.split(",") if item.strip())
    return list(dict.fromkeys(paths))


def _local_path(raw_path: str) -> Path:
    if raw_path.startswith("/data/social/"):
        return Path("data/social") / raw_path.removeprefix("/data/social/")
    return Path(raw_path)


def _first(record: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


if __name__ == "__main__":
    main()
