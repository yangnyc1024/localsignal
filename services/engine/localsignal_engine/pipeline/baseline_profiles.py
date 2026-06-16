import logging
import os

import psycopg
from localsignal_engine.db.connection import get_conn

from localsignal_engine.baseline import compute_baseline_profiles
from localsignal_engine.db import load_places

logger = logging.getLogger(__name__)


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to compute baseline profiles.")

    places = load_places()
    with get_conn() as conn:
        updated = compute_baseline_profiles(conn, places)
    logger.info(f"Updated {updated} baseline profile().")


if __name__ == "__main__":
    main()
