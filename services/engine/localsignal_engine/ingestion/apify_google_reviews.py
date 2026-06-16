"""Apify Google Maps Reviews scraper integration.

Uses actor `compass/google-maps-reviews-scraper` to fetch full review
history for each place and ingest it into place_documents (content_type
= "review") so the LLM enrichment pipeline has richer evidence.

Environment variables
---------------------
APIFY_TOKEN                     Required. Apify API token.
APIFY_GMAPS_MAX_REVIEWS         Max reviews per place (default 50).
APIFY_GMAPS_SORT                Sort order: newest | mostRelevant (default newest).
APIFY_GMAPS_WAIT_SECONDS        Timeout for actor run (default 600).
APIFY_GMAPS_MAX_CHARGE_USD      Max spend per run in USD (default 2.0).
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from localsignal_engine.models import Place

logger = logging.getLogger(__name__)

ACTOR_ID = "compass~google-maps-reviews-scraper"
DEFAULT_MAX_REVIEWS = 50
DEFAULT_SORT = "newest"
DEFAULT_WAIT_SECONDS = 600
DEFAULT_MAX_CHARGE_USD = 2.0


# ── public entry point ────────────────────────────────────────────────────────

def fetch_google_reviews(places: list[Place]) -> list[dict[str, Any]]:
    """Run Apify actor for all places and return normalised review records.

    Each record has the shape expected by place/scraping.py's
    ingest_google_place_documents flow:
      {place_id, text, rating, author_name, published_at, review_url}

    Returns an empty list if APIFY_TOKEN is not set or no places have a
    google_place_id.
    """
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        logger.info("APIFY_TOKEN not set; skipping Apify Google Reviews fetch.")
        return []

    eligible = [p for p in places if p.google_place_id]
    if not eligible:
        logger.info("No places have a google_place_id; skipping Apify Google Reviews fetch.")
        return []

    max_reviews = int(os.getenv("APIFY_GMAPS_MAX_REVIEWS", str(DEFAULT_MAX_REVIEWS)))
    sort_reviews_by = os.getenv("APIFY_GMAPS_SORT", DEFAULT_SORT)
    max_charge = float(os.getenv("APIFY_GMAPS_MAX_CHARGE_USD", str(DEFAULT_MAX_CHARGE_USD)))

    actor_input = {
        "placeIds": [p.google_place_id for p in eligible],
        "maxReviews": max_reviews,
        "sortReviewsBy": sort_reviews_by,
        "language": "en",
    }

    logger.info(
        "Starting Apify Google Reviews actor for %d place(s) (max %d reviews each).",
        len(eligible), max_reviews,
    )

    try:
        run = _start_run(token, actor_input, max_charge)
    except Exception as exc:
        logger.warning("Failed to start Apify Google Reviews actor: %s", exc)
        return []

    run_id = run["id"]
    logger.info("Apify run %s started.", run_id)

    try:
        finished = _wait_for_run(token, run_id)
    except TimeoutError as exc:
        logger.warning("Apify Google Reviews run %s timed out: %s", run_id, exc)
        return []
    except Exception as exc:
        logger.warning("Apify Google Reviews run %s failed: %s", run_id, exc)
        return []

    status = finished.get("status")
    dataset_id = (finished.get("defaultDatasetId") or "").strip()

    if status != "SUCCEEDED" or not dataset_id:
        logger.warning("Apify run %s finished with status=%s; no usable dataset.", run_id, status)
        return []

    logger.info("Apify run %s succeeded; fetching dataset %s.", run_id, dataset_id)

    try:
        raw_items = _fetch_dataset(token, dataset_id, limit=len(eligible) * max_reviews + 100)
    except Exception as exc:
        logger.warning("Failed to fetch Apify dataset %s: %s", dataset_id, exc)
        return []

    # Build a lookup: google_place_id → Place.id
    place_id_map = {p.google_place_id: p.id for p in eligible}
    records = _normalise(raw_items, place_id_map)
    logger.info("Apify Google Reviews: %d raw items → %d normalised review(s).", len(raw_items), len(records))
    return records


# ── Apify API helpers ─────────────────────────────────────────────────────────

def _start_run(token: str, actor_input: dict[str, Any], max_charge: float) -> dict[str, Any]:
    query = urlencode({"maxTotalChargeUsd": str(max_charge)})
    request = Request(
        f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs?{query}",
        data=json.dumps(actor_input).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["data"]


def _wait_for_run(token: str, run_id: str) -> dict[str, Any]:
    timeout_seconds = int(os.getenv("APIFY_GMAPS_WAIT_SECONDS", str(DEFAULT_WAIT_SECONDS)))
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        run = _get_run(token, run_id)
        if run.get("status") in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
            return run
        time.sleep(15)
    raise TimeoutError(f"Timed out waiting for Apify run {run_id} after {timeout_seconds}s.")


def _get_run(token: str, run_id: str) -> dict[str, Any]:
    request = Request(
        f"https://api.apify.com/v2/actor-runs/{run_id}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["data"]


def _fetch_dataset(token: str, dataset_id: str, limit: int = 5000) -> list[dict[str, Any]]:
    query = urlencode({"clean": "true", "format": "json", "limit": str(limit)})
    request = Request(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


# ── normalisation ─────────────────────────────────────────────────────────────

def _normalise(raw_items: list[dict[str, Any]], place_id_map: dict[str, str]) -> list[dict[str, Any]]:
    """Convert Apify compass review records to our internal shape."""
    records: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue

        # The actor outputs one item per place containing a `reviews` list,
        # OR one item per review depending on the actor version.
        reviews = item.get("reviews")
        if isinstance(reviews, list):
            # Batch output: item is a place wrapper
            google_place_id = item.get("placeId") or item.get("id") or ""
            internal_id = place_id_map.get(google_place_id)
            if not internal_id:
                continue
            for review in reviews:
                record = _review_record(review, internal_id, item)
                if record:
                    records.append(record)
        else:
            # Flat output: item is a single review
            google_place_id = item.get("placeId") or item.get("id") or ""
            internal_id = place_id_map.get(google_place_id)
            if not internal_id:
                continue
            record = _review_record(item, internal_id, {})
            if record:
                records.append(record)
    return records


def _review_record(review: dict[str, Any], place_id: str, place_wrapper: dict[str, Any]) -> Optional[dict[str, Any]]:
    text = str(review.get("text") or review.get("reviewText") or "").strip()
    if len(text) < 30:
        return None
    return {
        "place_id": place_id,
        "text": text,
        "rating": _safe_float(review.get("stars") or review.get("rating")),
        "author_name": str(review.get("reviewerName") or review.get("name") or ""),
        "published_at": _parse_date(
            review.get("publishedAtDate") or review.get("date") or review.get("publishAt")
        ),
        "review_url": str(
            review.get("reviewUrl") or review.get("url") or
            place_wrapper.get("url") or ""
        ),
    }


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        normalized = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)
