from localsignal_engine.db import write_weekly_report
from localsignal_engine.sample_data import MENTIONS, PLACES
from localsignal_engine.scoring import extract_signals


def main() -> None:
    signals = extract_signals(PLACES, MENTIONS)
    report_id = write_weekly_report(signals)
    print(f"Wrote weekly report {report_id} with {len(signals)} signals.")


if __name__ == "__main__":
    main()
