import json

from localsignal_engine.sample_data import MENTIONS, PLACES
from localsignal_engine.scoring import extract_signals


def main() -> None:
    signals = extract_signals(PLACES, MENTIONS)
    print(
        json.dumps(
            [
                {
                    "place": signal.place.name,
                    "signal_type": signal.signal_type,
                    "title": signal.title,
                    "summary": signal.summary,
                    "score": signal.score,
                    "evidence": signal.evidence,
                }
                for signal in signals
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
