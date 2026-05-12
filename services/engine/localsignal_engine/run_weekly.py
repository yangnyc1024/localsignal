from localsignal_engine.db import write_weekly_report
from localsignal_engine.email import send_latest_digest
from localsignal_engine.sample_data import MENTIONS, PLACES
from localsignal_engine.scoring import extract_signals


def run_once() -> None:
    signals = extract_signals(PLACES, MENTIONS)
    report_id = write_weekly_report(signals)
    delivery_count = send_latest_digest()
    print(f"Wrote report {report_id} and queued {delivery_count} digest deliveries.")


def main() -> None:
    run_once()


if __name__ == "__main__":
    main()
