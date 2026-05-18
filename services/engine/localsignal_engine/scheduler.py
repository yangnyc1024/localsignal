import os
import time
from datetime import datetime, timezone

from localsignal_engine.run_evidence_ingestion import main as run_evidence_ingestion
from localsignal_engine.run_weekly import run_once as run_weekly_cycle


def main() -> None:
    daily_enabled = _enabled("DAILY_EVIDENCE_ENABLED", default=True)
    weekly_enabled = _enabled("WEEKLY_REPORT_ENABLED", default=False)
    daily_interval = int(os.getenv("DAILY_EVIDENCE_INTERVAL_SECONDS", "86400"))
    weekly_interval = int(os.getenv("WEEKLY_INTERVAL_SECONDS", "604800"))
    run_on_start = _enabled("SCHEDULER_RUN_ON_START", default=True)

    print(
        "LocalSignal scheduler started. "
        f"daily_enabled={daily_enabled} daily_interval={daily_interval} "
        f"weekly_enabled={weekly_enabled} weekly_interval={weekly_interval} "
        f"run_on_start={run_on_start}",
        flush=True,
    )

    last_daily = 0.0
    last_weekly = 0.0
    if run_on_start:
        if daily_enabled:
            _run("daily evidence ingestion", run_evidence_ingestion)
            last_daily = time.time()
        if weekly_enabled:
            _run("weekly report cycle", run_weekly_cycle)
            last_weekly = time.time()

    while True:
        now = time.time()
        if daily_enabled and now - last_daily >= daily_interval:
            _run("daily evidence ingestion", run_evidence_ingestion)
            last_daily = now
        if weekly_enabled and now - last_weekly >= weekly_interval:
            _run("weekly report cycle", run_weekly_cycle)
            last_weekly = now
        time.sleep(60)


def _run(label: str, fn) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    print(f"Starting {label} at {started_at}", flush=True)
    try:
        fn()
    except Exception as exc:
        print(f"{label} failed: {exc}", flush=True)
        return
    print(f"{label} completed.", flush=True)


def _enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() == "true"


if __name__ == "__main__":
    main()
