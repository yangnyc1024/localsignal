import os

from localsignal_engine.db import (
    finish_ingestion_run,
    load_places,
    load_recent_mentions,
    start_ingestion_run,
    write_mentions,
    write_weekly_report,
)
from localsignal_engine.email import send_latest_digest
from localsignal_engine.ingestion.live import fetch_live_mentions
from localsignal_engine.ml_engine import generate_report_signals


def run_once() -> None:
    run_id = start_ingestion_run()
    source_counts: dict[str, int] = {}
    written_count = 0
    signals_generated = 0
    report_id = None

    places = load_places()
    try:
        mentions, source_counts = fetch_live_mentions(places)
        written_count = write_mentions(mentions)

        if not mentions and _fallback_to_sample():
            raise RuntimeError("Sample fallback has been removed from the production weekly job.")

        model_mentions = load_recent_mentions(days=_current_window_days() + _baseline_window_days())
        signals = generate_report_signals(
            places=places,
            mentions=model_mentions,
            current_window_days=_current_window_days(),
            baseline_window_days=_baseline_window_days(),
        )
        signals_generated = len(signals)
        if not signals:
            raise RuntimeError("No signals generated from live ingestion.")

        report_id = write_weekly_report(signals)
        delivery_count = send_latest_digest()
        finish_ingestion_run(
            run_id=run_id,
            status="succeeded",
            source_counts=source_counts,
            live_mentions_written=written_count,
            signals_generated=signals_generated,
            report_id=report_id,
        )
        print(
            f"Wrote report {report_id}, stored {written_count} live mentions, and queued {delivery_count} digest deliveries."
        )
    except Exception as exc:
        finish_ingestion_run(
            run_id=run_id,
            status="failed",
            source_counts=source_counts,
            live_mentions_written=written_count,
            signals_generated=signals_generated,
            report_id=report_id,
            error=str(exc),
        )
        raise


def _fallback_to_sample() -> bool:
    return os.getenv("INGESTION_FALLBACK_TO_SAMPLE", "false").lower() == "true"


def _current_window_days() -> int:
    return int(os.getenv("ML_CURRENT_WINDOW_DAYS", "7"))


def _baseline_window_days() -> int:
    return int(os.getenv("ML_BASELINE_WINDOW_DAYS", "28"))


def main() -> None:
    run_once()


if __name__ == "__main__":
    main()
