import os

import psycopg

from localsignal_engine.baseline import compute_baseline_profiles
from localsignal_engine.db import load_places


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to compute baseline profiles.")

    places = load_places()
    with psycopg.connect(database_url) as conn:
        updated = compute_baseline_profiles(conn, places)
    print(f"Updated {updated} baseline profile(s).")


if __name__ == "__main__":
    main()
