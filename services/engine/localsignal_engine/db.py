import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from localsignal_engine.models import Mention, Place, Signal


DEFAULT_REGION = "Fort Lee / Edgewater / Palisades Park"


def start_ingestion_run() -> UUID:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to start ingestion run.")
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            INSERT INTO ingestion_runs (status)
            VALUES ('started')
            RETURNING id
            """
        ).fetchone()
        conn.commit()
    return row[0]


def finish_ingestion_run(
    run_id: UUID,
    status: str,
    source_counts: dict[str, int],
    live_mentions_written: int,
    signals_generated: int,
    report_id: UUID | None = None,
    error: str | None = None,
) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to finish ingestion run.")
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            UPDATE ingestion_runs
            SET
              status = %s,
              source_counts = %s::jsonb,
              live_mentions_written = %s,
              signals_generated = %s,
              report_id = %s,
              error = %s,
              finished_at = now()
            WHERE id = %s
            """,
            (
                status,
                Jsonb(source_counts),
                live_mentions_written,
                signals_generated,
                report_id,
                error,
                run_id,
            ),
        )
        conn.commit()


def load_places() -> list[Place]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to load places.")

    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            """
            SELECT id::text, name, category, city, neighborhood
            FROM places
            ORDER BY city, name
            """
        ).fetchall()
    return [
        Place(
            id=row[0],
            name=row[1],
            category=row[2],
            city=row[3],
            neighborhood=row[4],
        )
        for row in rows
    ]


def write_mentions(mentions: list[Mention]) -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to write mentions.")
    if not mentions:
        return 0

    written = 0
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for mention in mentions:
                cur.execute(
                    """
                    INSERT INTO mentions (
                      place_id,
                      source,
                      source_url,
                      author_region,
                      body,
                      rating,
                      sentiment,
                      occurred_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (place_id, source_url) WHERE source_url IS NOT NULL
                    DO NOTHING
                    RETURNING id
                    """,
                    (
                        mention.place_id,
                        mention.source,
                        mention.source_url,
                        mention.author_region,
                        mention.body,
                        mention.rating,
                        mention.sentiment,
                        mention.occurred_at,
                    ),
                )
                if cur.fetchone():
                    written += 1
        conn.commit()
    return written


def load_recent_mentions(days: int = 35) -> list[Mention]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to load mentions.")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            """
            SELECT
              place_id::text,
              source,
              body,
              occurred_at,
              source_url,
              author_region,
              rating::float,
              sentiment::float
            FROM mentions
            WHERE occurred_at >= %s
            ORDER BY occurred_at DESC
            """,
            (since,),
        ).fetchall()

    return [
        Mention(
            place_id=row[0],
            source=row[1],
            body=row[2],
            occurred_at=row[3],
            source_url=row[4],
            author_region=row[5],
            rating=row[6],
            sentiment=row[7],
        )
        for row in rows
    ]


def write_signals(signals: list[Signal]) -> list[UUID]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to write signals.")

    signal_ids: list[UUID] = []
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
                    ON CONFLICT (place_id, signal_type, week_start)
                    DO UPDATE SET
                      title = EXCLUDED.title,
                      summary = EXCLUDED.summary,
                      evidence = EXCLUDED.evidence,
                      score = EXCLUDED.score,
                      city = EXCLUDED.city,
                      created_at = now()
                    RETURNING id
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
                signal_ids.append(cur.fetchone()[0])
        conn.commit()
    return signal_ids


def write_weekly_report(signals: list[Signal], region: str = DEFAULT_REGION) -> UUID:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to write a weekly report.")
    if not signals:
        raise RuntimeError("No signals available for report generation.")

    week_start = signals[0].week_start
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reports (title, region, week_start, intro)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (region, week_start)
                DO UPDATE SET
                  title = EXCLUDED.title,
                  intro = EXCLUDED.intro,
                  created_at = now()
                RETURNING id
                """,
                (
                    "This Week Nearby",
                    region,
                    week_start,
                    "A quick read on the local places showing unusual momentum, behavior changes, or early quality shifts.",
                ),
            )
            report_id = cur.fetchone()[0]

            signal_ids: list[UUID] = []
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
                    ON CONFLICT (place_id, signal_type, week_start)
                    DO UPDATE SET
                      title = EXCLUDED.title,
                      summary = EXCLUDED.summary,
                      evidence = EXCLUDED.evidence,
                      score = EXCLUDED.score,
                      city = EXCLUDED.city,
                      created_at = now()
                    RETURNING id
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
                signal_ids.append(cur.fetchone()[0])

            cur.execute("DELETE FROM report_signals WHERE report_id = %s", (report_id,))
            for rank, signal_id in enumerate(signal_ids, start=1):
                cur.execute(
                    """
                    INSERT INTO report_signals (report_id, signal_id, rank)
                    VALUES (%s, %s, %s)
                    """,
                    (report_id, signal_id, rank),
                )

        conn.commit()
    return report_id
