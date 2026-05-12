import os

import psycopg
from psycopg.types.json import Jsonb

from localsignal_engine.models import Signal


def write_signals(signals: list[Signal]) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to write signals.")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for signal in signals:
                cur.execute(
                    """
                    INSERT INTO signals (
                      place_id,
                      signal_type,
                      title,
                      summary,
                      evidence,
                      score,
                      city,
                      week_start
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    """,
                    (
                        signal.place.id,
                        signal.signal_type,
                        signal.title,
                        signal.summary,
                        Jsonb(signal.evidence),
                        signal.score,
                        signal.place.city,
                        signal.week_start,
                    ),
                )
        conn.commit()
