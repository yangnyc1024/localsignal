from localsignal_engine.db import write_weekly_report
from localsignal_engine.llm import generate_report_briefing
from localsignal_engine.ml_engine import generate_report_signals
from localsignal_engine.sample_data import MENTIONS, PLACES


def main() -> None:
    signals = generate_report_signals(PLACES, MENTIONS)
    report_id = write_weekly_report(signals)
    briefing_metrics = generate_report_briefing(report_id)
    print(
        f"Wrote demo report {report_id} with {len(signals)} sample-backed signals "
        f"and briefing {briefing_metrics}."
    )


if __name__ == "__main__":
    main()
