import logging
import json
import os
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from localsignal_engine.db import record_social_source_run

logger = logging.getLogger(__name__)


ACTOR_ID = "apify~instagram-scraper"
DEFAULT_PLACE_QUERIES = [
    "Fort Lee NJ food",
    "Fort Lee NJ Korean food",
    "Fort Lee NJ bakery",
    "Fort Lee NJ cafe",
    "Edgewater NJ food",
    "Edgewater NJ cafe",
    "Palisades Park NJ Korean food",
    "Palisades Park NJ bakery",
]

DEFAULT_HASHTAG_QUERIES = [
    "fortleefood",
    "fortleenj",
    "fortleeeats",
    "edgewaternj",
    "edgewaterfood",
    "palisadesparknj",
    "palisadesparkfood",
    "bergencountyfood",
    "northjerseyeats",
    "northjerseyfood",
    "njfood",
    "njfoodies",
    "koreanfoodnj",
    "njbakery",
    "njcafe",
    "fortleekorean",
]


def main() -> None:
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        raise RuntimeError("APIFY_TOKEN is required to run Instagram search automation.")

    place_queries = _csv("APIFY_INSTAGRAM_PLACE_QUERIES") or _csv("APIFY_INSTAGRAM_SEARCH_QUERIES") or DEFAULT_PLACE_QUERIES
    hashtag_queries = _csv("APIFY_INSTAGRAM_HASHTAG_QUERIES") or DEFAULT_HASHTAG_QUERIES
    modes = _csv("APIFY_INSTAGRAM_SEARCH_MODES") or ["place", "hashtag"]
    search_limit = int(os.getenv("APIFY_INSTAGRAM_SEARCH_LIMIT", "3"))
    results_limit = int(os.getenv("APIFY_INSTAGRAM_RESULTS_LIMIT", "10"))
    newer_than = os.getenv("APIFY_INSTAGRAM_ONLY_NEWER_THAN", "30 days").strip()
    max_charge = float(os.getenv("APIFY_INSTAGRAM_MAX_CHARGE_USD", "0.5"))
    follow_place_results = os.getenv("APIFY_INSTAGRAM_FOLLOW_PLACE_RESULTS", "true").lower() == "true"
    max_place_urls = int(os.getenv("APIFY_INSTAGRAM_MAX_PLACE_URLS", "16"))

    dataset_ids: list[str] = []
    place_urls: list[str] = []

    if "place" in modes:
        for query in place_queries:
            dataset_id = _run_search(token, query, "place", search_limit, results_limit, newer_than, max_charge)
            if dataset_id:
                discovered_urls = _dataset_urls(token, dataset_id, max_place_urls)
                _record_search_run(
                    search_type="place",
                    query=query,
                    dataset_id=dataset_id,
                    status="succeeded",
                    total_records=len(discovered_urls),
                )
                if follow_place_results:
                    place_urls.extend(discovered_urls)
                else:
                    dataset_ids.append(dataset_id)

    if follow_place_results and place_urls:
        unique_urls = list(dict.fromkeys(place_urls))[:max_place_urls]
        actor_input = {
            "directUrls": unique_urls,
            "resultsType": "posts",
            "resultsLimit": results_limit,
            "addParentData": True,
            "onlyPostsNewerThan": newer_than,
        }
        run = _start_run(token, actor_input, max_charge)
        logger.info(f"started Instagram place-post run {run['id']} for {len(unique_urls)} location URL(s)")
        finished = _wait_for_run(token, run["id"])
        status = finished.get("status")
        dataset_id = finished.get("defaultDatasetId")
        logger.info(f"Instagram place-post run {run['id']} finished with {status}; dataset={dataset_id}")
        if status == "SUCCEEDED" and dataset_id:
            _record_search_run(
                search_type="place-post",
                query=f"{len(unique_urls)} Instagram location URL(s)",
                dataset_id=dataset_id,
                status="succeeded",
                total_records=len(unique_urls),
            )
            dataset_ids.append(dataset_id)
        else:
            _record_search_run(
                search_type="place-post",
                query=f"{len(unique_urls)} Instagram location URL(s)",
                dataset_id=dataset_id,
                status="failed",
                error=f"Apify run finished with {status}",
            )

    if "hashtag" in modes:
        for query in hashtag_queries:
            dataset_id = _run_search(token, query, "hashtag", search_limit, results_limit, newer_than, max_charge)
            if dataset_id:
                _record_search_run(
                    search_type="hashtag",
                    query=query,
                    dataset_id=dataset_id,
                    status="succeeded",
                    total_records=_dataset_item_count(token, dataset_id),
                )
                dataset_ids.append(dataset_id)

    if dataset_ids:
        _merge_env_dataset_ids(dataset_ids)
        logger.info("APIFY_SOCIAL_DATASET_IDS updated with: " + ",".join(dataset_ids))
    else:
        logger.info("No successful Instagram search datasets were produced.")


def _run_search(
    token: str,
    query: str,
    search_type: str,
    search_limit: int,
    results_limit: int,
    newer_than: str,
    max_charge: float,
) -> Optional[str]:
    actor_input = {
        "search": query,
        "searchType": search_type,
        "resultsType": "posts",
        "searchLimit": search_limit,
        "resultsLimit": results_limit,
        "addParentData": True,
        "onlyPostsNewerThan": newer_than,
    }
    run = _start_run(token, actor_input, max_charge)
    logger.info(f"started Instagram {search_type} search run {run['id']} for {query!r}")
    finished = _wait_for_run(token, run["id"])
    status = finished.get("status")
    dataset_id = finished.get("defaultDatasetId")
    logger.info(f"Instagram {search_type} search run {run['id']} finished with {status}; dataset={dataset_id}")
    if status != "SUCCEEDED" or not dataset_id:
        _record_search_run(
            search_type=search_type,
            query=query,
            dataset_id=dataset_id,
            status="failed",
            error=f"Apify run {run['id']} finished with {status}",
        )
    return dataset_id if status == "SUCCEEDED" and dataset_id else None


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
    timeout_seconds = int(os.getenv("APIFY_INSTAGRAM_WAIT_SECONDS", "600"))
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        run = _get_run(token, run_id)
        if run.get("status") in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
            return run
        time.sleep(10)
    raise TimeoutError(f"Timed out waiting for Apify run {run_id}.")


def _get_run(token: str, run_id: str) -> dict[str, Any]:
    request = Request(
        f"https://api.apify.com/v2/actor-runs/{run_id}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["data"]


def _dataset_urls(token: str, dataset_id: str, limit: int) -> list[str]:
    query = urlencode({"clean": "true", "format": "json", "limit": str(limit)})
    request = Request(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        return []
    urls: list[str] = []
    for row in payload:
        if isinstance(row, dict):
            url = row.get("url") or row.get("inputUrl")
            if url:
                urls.append(str(url))
    return urls


def _dataset_item_count(token: str, dataset_id: str) -> int:
    query = urlencode({"clean": "true", "format": "json", "limit": "1000"})
    request = Request(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return len(payload) if isinstance(payload, list) else 0


def _record_search_run(
    *,
    search_type: str,
    query: str,
    dataset_id: Optional[str],
    status: str,
    total_records: int = 0,
    error: Optional[str] = None,
) -> None:
    try:
        record_social_source_run(
            provider="apify_search",
            platform="instagram",
            dataset_id=dataset_id,
            query=f"{search_type}: {query}",
            status=status,
            total_records=total_records,
            normalized_records=total_records,
            error=error,
        )
    except Exception as exc:
        logger.warning(f"apify search run logging failed: {exc}")


def _merge_env_dataset_ids(dataset_ids: list[str]) -> None:
    env_path = Path(".env")
    existing_text = env_path.read_text() if env_path.exists() else ""
    current: list[str] = []
    lines = existing_text.splitlines()
    for line in lines:
        if line.startswith("APIFY_SOCIAL_DATASET_IDS="):
            current = [item.strip() for item in line.split("=", 1)[1].split(",") if item.strip()]
            break
    merged = list(dict.fromkeys([*current, *dataset_ids]))
    value = ",".join(merged)

    replaced = False
    new_lines = []
    for line in lines:
        if line.startswith("APIFY_SOCIAL_DATASET_IDS="):
            new_lines.append(f"APIFY_SOCIAL_DATASET_IDS={value}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"APIFY_SOCIAL_DATASET_IDS={value}")
    env_path.write_text("\n".join(new_lines).rstrip() + "\n")


def _csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


if __name__ == "__main__":
    main()
