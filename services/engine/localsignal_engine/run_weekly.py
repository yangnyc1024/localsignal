import os

from localsignal_engine.db import load_places, load_recent_mentions, write_mentions, write_weekly_report
from localsignal_engine.email import send_latest_digest
from localsignal_engine.ingestion.live import fetch_live_mentions
from localsignal_engine.ml_engine import generate_report_signals
from localsignal_engine.sample_data import MENTIONS, PLACES


def run_once() -> None:
    places = load_places()
    mentions = fetch_live_mentions(places)
    written_count = write_mentions(mentions)

    if not mentions and _fallback_to_sample():
        print("No live mentions found; falling back to sample mentions.", flush=True)
        places = PLACES
        mentions = MENTIONS

    if mentions is MENTIONS:
        model_mentions = mentions
    else:
        model_mentions = load_recent_mentions(days=_current_window_days() + _baseline_window_days())

    signals = generate_report_signals(
        places=places,
        mentions=model_mentions,
        current_window_days=_current_window_days(),
        baseline_window_days=_baseline_window_days(),
    )
    if not signals:
        raise RuntimeError("No signals generated from live ingestion.")

    report_id = write_weekly_report(signals)
    delivery_count = send_latest_digest()
    print(
        f"Wrote report {report_id}, stored {written_count} live mentions, and queued {delivery_count} digest deliveries."
    )


def _fallback_to_sample() -> bool:
    return os.getenv("INGESTION_FALLBACK_TO_SAMPLE", "true").lower() == "true"


def _current_window_days() -> int:
    return int(os.getenv("ML_CURRENT_WINDOW_DAYS", "7"))


def _baseline_window_days() -> int:
    return int(os.getenv("ML_BASELINE_WINDOW_DAYS", "28"))


def main() -> None:
    run_once()


if __name__ == "__main__":
    main()
