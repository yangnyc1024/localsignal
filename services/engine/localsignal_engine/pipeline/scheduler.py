import logging
import os
import time
from datetime import datetime, timezone

from localsignal_engine.logging_config import configure_logging
from localsignal_engine.pipeline.evidence import main as run_evidence_ingestion
from localsignal_engine.pipeline.weekly import run_once as run_weekly_cycle
from localsignal_engine.pipeline.apify_instagram import main as run_instagram_scrape

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    daily_enabled = _enabled("DAILY_EVIDENCE_ENABLED", default=True)
    weekly_enabled = _enabled("WEEKLY_REPORT_ENABLED", default=True)
    instagram_enabled = _enabled("INSTAGRAM_SCRAPE_ENABLED", default=True)
    daily_interval = int(os.getenv("DAILY_EVIDENCE_INTERVAL_SECONDS", "86400"))
    weekly_interval = int(os.getenv("WEEKLY_INTERVAL_SECONDS", "604800"))
    instagram_interval = int(os.getenv("INSTAGRAM_SCRAPE_INTERVAL_SECONDS", "259200"))  # 3 days
    run_on_start = _enabled("SCHEDULER_RUN_ON_START", default=True)

    logger.info(
        "LocalSignal scheduler started. daily_enabled=%s interval=%s "
        "weekly_enabled=%s interval=%s instagram_enabled=%s interval=%s run_on_start=%s",
        daily_enabled, daily_interval, weekly_enabled, weekly_interval,
        instagram_enabled, instagram_interval, run_on_start,
    )

    last_daily = 0.0
    last_weekly = 0.0
    last_instagram = 0.0
    if run_on_start:
        if daily_enabled:
            _run("daily evidence ingestion", run_evidence_ingestion)
            last_daily = time.time()
        if instagram_enabled:
            _run("instagram scrape", run_instagram_scrape)
            last_instagram = time.time()
        if weekly_enabled:
            _run("weekly report cycle", run_weekly_cycle)
            last_weekly = time.time()

    while True:
        now = time.time()
        if daily_enabled and now - last_daily >= daily_interval:
            _run("daily evidence ingestion", run_evidence_ingestion)
            last_daily = now
        if instagram_enabled and now - last_instagram >= instagram_interval:
            _run("instagram scrape", run_instagram_scrape)
            last_instagram = now
        if weekly_enabled and now - last_weekly >= weekly_interval:
            _run("weekly report cycle", run_weekly_cycle)
            last_weekly = now
        time.sleep(60)


def _run(label: str, fn) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    logger.info(f"Starting {label} at {started_at}")
    try:
        fn()
    except Exception as exc:
        logger.warning(f"{label} failed: {exc}")
        return
    logger.info(f"{label} completed.")


def _enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() == "true"


if __name__ == "__main__":
    main()
