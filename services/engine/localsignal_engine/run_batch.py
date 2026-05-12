from localsignal_engine.db import write_signals
from localsignal_engine.sample_data import MENTIONS, PLACES
from localsignal_engine.scoring import extract_signals


def main() -> None:
    signals = extract_signals(PLACES, MENTIONS)
    write_signals(signals)
    print(f"Wrote {len(signals)} signals.")


if __name__ == "__main__":
    main()
