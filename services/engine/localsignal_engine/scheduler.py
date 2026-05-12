import os
import time
from datetime import datetime, timezone

from localsignal_engine.run_weekly import run_once


def main() -> None:
    interval_seconds = int(os.getenv("WEEKLY_INTERVAL_SECONDS", "604800"))
    run_on_start = os.getenv("WEEKLY_RUN_ON_START", "true").lower() == "true"

    print(
        f"LocalSignal scheduler started. interval_seconds={interval_seconds} run_on_start={run_on_start}",
        flush=True,
    )

    if run_on_start:
        _run_cycle()

    while True:
        time.sleep(interval_seconds)
        _run_cycle()


def _run_cycle() -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    print(f"Starting weekly cycle at {started_at}", flush=True)
    try:
        run_once()
    except Exception as exc:
        print(f"Weekly cycle failed: {exc}", flush=True)
        return
    print("Weekly cycle completed.", flush=True)


if __name__ == "__main__":
    main()
