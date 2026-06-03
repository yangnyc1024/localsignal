import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from psycopg.types.json import Jsonb

from localsignal_engine.ingestion.social_metadata import SocialMetadataItem
from localsignal_engine.models import Mention
from localsignal_engine.database.connection import get_conn


def start_ingestion_run() -> UUID:
    with get_conn() as conn:
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
    source_counts: dict,
    live_mentions_written: int,
    signals_generated: int,
    report_id: Optional[UUID] = None,
    error: Optional[str] = None,
) -> None:
    with get_conn() as conn:
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
                Jsonb(_clean_json(source_counts)),
                live_mentions_written,
                signals_generated,
                report_id,
                error,
                run_id,
            ),
        )
        conn.commit()


def record_social_source_run(
    *,
    provider: str,
    platform: str = "social_metadata",
    dataset_id: Optional[str] = None,
    query: Optional[str] = None,
    status: str = "succeeded",
    total_records: int = 0,
    normalized_records: int = 0,
    fresh_records: int = 0,
    old_records_dropped: int = 0,
    parsed_items: int = 0,
    resolved_items: int = 0,
    review_items: int = 0,
    unresolved_items: int = 0,
    source_counts: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    import os
    if not os.getenv('DATABASE_URL'):
        return
    with get_conn() as conn:
        _ensure_social_source_runs_table(conn)
        conn.execute(
            """
            INSERT INTO social_source_runs (
              provider,
              platform,
              dataset_id,
              query,
              status,
              total_records,
              normalized_records,
              fresh_records,
              old_records_dropped,
              parsed_items,
              resolved_items,
              review_items,
              unresolved_items,
              source_counts,
              error
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            (
                provider,
                platform,
                dataset_id,
                query,
                status,
                total_records,
                normalized_records,
                fresh_records,
                old_records_dropped,
                parsed_items,
                resolved_items,
                review_items,
                unresolved_items,
                Jsonb(_clean_json(source_counts or {})),
                error,
            ),
        )
        conn.commit()


def _ensure_social_source_runs_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS social_source_runs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          provider TEXT NOT NULL,
          platform TEXT NOT NULL DEFAULT 'social_metadata',
          dataset_id TEXT,
          query TEXT,
          status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
          total_records INTEGER NOT NULL DEFAULT 0,
          normalized_records INTEGER NOT NULL DEFAULT 0,
          fresh_records INTEGER NOT NULL DEFAULT 0,
          old_records_dropped INTEGER NOT NULL DEFAULT 0,
          parsed_items INTEGER NOT NULL DEFAULT 0,
          resolved_items INTEGER NOT NULL DEFAULT 0,
          review_items INTEGER NOT NULL DEFAULT 0,
          unresolved_items INTEGER NOT NULL DEFAULT 0,
          source_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
          error TEXT,
          started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          finished_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_social_source_runs_finished ON social_source_runs(finished_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_social_source_runs_provider_dataset ON social_source_runs(provider, dataset_id)")


def write_mentions(mentions: list) -> int:
    if not mentions:
        return 0

    written = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for mention in mentions:
                if _insert_mention(cur, mention):
                    written += 1
        conn.commit()
    return written


def write_raw_source_items_from_mentions(mentions: list) -> tuple:
    if not mentions:
        return 0, 0

    raw_written = 0
    chunks_written = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for mention in mentions:
                raw_id = _upsert_raw_source_item(cur, mention)
                if raw_id:
                    raw_written += 1
                else:
                    raw_id = _existing_raw_source_item_id(cur, mention)

                if not raw_id:
                    continue
                if mention.source == "google_places":
                    continue

                cur.execute(
                    """
                    SELECT 1
                    FROM evidence_chunks
                    WHERE raw_source_item_id = %s
                    LIMIT 1
                    """,
                    (raw_id,),
                )
                if cur.fetchone():
                    continue

                cur.execute(
                    """
                    INSERT INTO evidence_chunks (
                      raw_source_item_id,
                      place_id,
                      chunk_text,
                      extracted_keywords,
                      sentiment,
                      occurred_at,
                      metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        raw_id,
                        mention.place_id,
                        _clean_text(mention.body),
                        _extract_food_keywords(mention.body),
                        mention.sentiment,
                        mention.occurred_at,
                        Jsonb(_clean_json({"source": mention.source})),
                    ),
                )
                if cur.fetchone():
                    chunks_written += 1
        conn.commit()
    return raw_written, chunks_written


def write_social_metadata_items(items: list) -> tuple:
    if not items:
        return 0, 0, 0, 0, 0

    raw_written = 0
    mentions_written = 0
    chunks_written = 0
    review_count = 0
    unresolved_count = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for item in items:
                raw_id = _upsert_social_raw_source_item(cur, item)
                if raw_id:
                    raw_written += 1
                else:
                    raw_id = _existing_social_raw_source_item_id(cur, item)

                if item.resolution_status == "review":
                    review_count += 1
                elif item.resolution_status == "unresolved":
                    unresolved_count += 1

                if not raw_id or item.resolution_status != "resolved" or not item.place_id:
                    continue

                mention = Mention(
                    place_id=item.place_id,
                    source=item.platform,
                    source_url=item.url,
                    body=item.text,
                    occurred_at=item.occurred_at,
                    author_region=str(item.geo_metadata.get("region") or item.geo_metadata.get("city") or "") or None,
                    engagement_metrics=item.engagement_metrics,
                    geo_metadata=item.geo_metadata,
                    raw_json=item.raw_json,
                )
                if _insert_mention(cur, mention):
                    mentions_written += 1

                cur.execute("SELECT 1 FROM evidence_chunks WHERE raw_source_item_id = %s LIMIT 1", (raw_id,))
                if cur.fetchone():
                    continue
                cur.execute(
                    """
                    INSERT INTO evidence_chunks (
                      raw_source_item_id,
                      place_id,
                      chunk_text,
                      extracted_keywords,
                      occurred_at,
                      metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        raw_id,
                        item.place_id,
                        _clean_text(item.text),
                        _extract_food_keywords(item.text),
                        item.occurred_at,
                        Jsonb(_clean_json(
                            {
                                "source": item.platform,
                                "resolution_confidence": item.place_resolution_confidence,
                                "engagement_metrics": item.engagement_metrics,
                            }
                        )),
                    ),
                )
                if cur.fetchone():
                    chunks_written += 1
        conn.commit()
    return raw_written, mentions_written, chunks_written, review_count, unresolved_count


def load_recent_mentions(days: int = 35) -> list:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with get_conn() as conn:
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
              AND source <> 'google_places'
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


def _upsert_raw_source_item(cur, mention: Mention):
    if mention.source_url:
        cur.execute(
            """
            INSERT INTO raw_source_items (
              platform,
              url,
              place_id,
              text,
              occurred_at,
              engagement_metrics,
              geo_metadata,
              raw_json,
              place_resolution_confidence,
              resolution_status
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, 1, 'resolved')
            ON CONFLICT (platform, url) WHERE url IS NOT NULL
            DO NOTHING
            RETURNING id
            """,
            (
                mention.source,
                mention.source_url,
                mention.place_id,
                _clean_text(mention.body),
                mention.occurred_at,
                Jsonb(_clean_json(mention.engagement_metrics or {})),
                Jsonb(_clean_json(_geo_metadata_for_mention(mention))),
                Jsonb(_clean_json({**(mention.raw_json or {}), "rating": mention.rating})),
            ),
        )
        row = cur.fetchone()
        return row[0] if row else None

    cur.execute(
        """
        INSERT INTO raw_source_items (
          platform,
          place_id,
          text,
          occurred_at,
          engagement_metrics,
          geo_metadata,
          raw_json,
          place_resolution_confidence,
          resolution_status
        )
        SELECT %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, 1, 'resolved'
        WHERE NOT EXISTS (
          SELECT 1
          FROM raw_source_items
          WHERE platform = %s
            AND place_id = %s
            AND text = %s
            AND occurred_at = %s
        )
        RETURNING id
        """,
        (
            mention.source,
            mention.place_id,
            _clean_text(mention.body),
            mention.occurred_at,
            Jsonb(_clean_json(mention.engagement_metrics or {})),
            Jsonb(_clean_json(_geo_metadata_for_mention(mention))),
            Jsonb(_clean_json({**(mention.raw_json or {}), "rating": mention.rating})),
            mention.source,
            mention.place_id,
            _clean_text(mention.body),
            mention.occurred_at,
        ),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _insert_mention(cur, mention: Mention) -> bool:
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
    return bool(cur.fetchone())


def _upsert_social_raw_source_item(cur, item: SocialMetadataItem):
    if item.url:
        cur.execute(
            """
            INSERT INTO raw_source_items (
              platform,
              url,
              author_id,
              place_id,
              text,
              occurred_at,
              engagement_metrics,
              geo_metadata,
              raw_json,
              place_resolution_confidence,
              resolution_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
            ON CONFLICT (platform, url) WHERE url IS NOT NULL
            DO UPDATE SET
              author_id = EXCLUDED.author_id,
              place_id = EXCLUDED.place_id,
              text = EXCLUDED.text,
              occurred_at = EXCLUDED.occurred_at,
              engagement_metrics = EXCLUDED.engagement_metrics,
              geo_metadata = EXCLUDED.geo_metadata,
              raw_json = EXCLUDED.raw_json,
              place_resolution_confidence = EXCLUDED.place_resolution_confidence,
              resolution_status = EXCLUDED.resolution_status,
              updated_at = now()
            RETURNING id
            """,
            (
                item.platform,
                item.url,
                item.author_id,
                item.place_id,
                _clean_text(item.text),
                item.occurred_at,
                Jsonb(_clean_json(item.engagement_metrics)),
                Jsonb(_clean_json(item.geo_metadata)),
                Jsonb(_clean_json(item.raw_json)),
                item.place_resolution_confidence,
                item.resolution_status,
            ),
        )
        row = cur.fetchone()
        return row[0] if row else None

    cur.execute(
        """
        INSERT INTO raw_source_items (
          platform,
          author_id,
          place_id,
          text,
          occurred_at,
          engagement_metrics,
          geo_metadata,
          raw_json,
          place_resolution_confidence,
          resolution_status
        )
        SELECT %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s
        WHERE NOT EXISTS (
          SELECT 1
          FROM raw_source_items
          WHERE platform = %s
            AND text = %s
            AND occurred_at = %s
        )
        RETURNING id
        """,
        (
            item.platform,
            item.author_id,
            item.place_id,
            _clean_text(item.text),
            item.occurred_at,
            Jsonb(_clean_json(item.engagement_metrics)),
            Jsonb(_clean_json(item.geo_metadata)),
            Jsonb(_clean_json(item.raw_json)),
            item.place_resolution_confidence,
            item.resolution_status,
            item.platform,
            _clean_text(item.text),
            item.occurred_at,
        ),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _existing_social_raw_source_item_id(cur, item: SocialMetadataItem):
    if item.url:
        cur.execute("SELECT id FROM raw_source_items WHERE platform = %s AND url = %s LIMIT 1", (item.platform, item.url))
    else:
        cur.execute(
            """
            SELECT id
            FROM raw_source_items
            WHERE platform = %s
              AND text = %s
              AND occurred_at = %s
            LIMIT 1
            """,
            (item.platform, _clean_text(item.text), item.occurred_at),
        )
    row = cur.fetchone()
    return row[0] if row else None


def _existing_raw_source_item_id(cur, mention: Mention):
    if mention.source_url:
        cur.execute(
            """
            SELECT id
            FROM raw_source_items
            WHERE platform = %s AND url = %s
            LIMIT 1
            """,
            (mention.source, mention.source_url),
        )
    else:
        cur.execute(
            """
            SELECT id
            FROM raw_source_items
            WHERE platform = %s
              AND place_id = %s
              AND text = %s
              AND occurred_at = %s
            LIMIT 1
            """,
            (mention.source, mention.place_id, _clean_text(mention.body), mention.occurred_at),
        )
    row = cur.fetchone()
    return row[0] if row else None


def _geo_metadata_for_mention(mention: Mention) -> dict:
    metadata = dict(mention.geo_metadata or {})
    if mention.author_region and "region" not in metadata:
        metadata["region"] = mention.author_region
    return metadata


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).replace("\x00", "")).strip()


def _clean_json(value: Any) -> Any:
    """Recursively strip NUL bytes from any JSON-serialisable value."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k.replace("\x00", "") if isinstance(k, str) else k: _clean_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_json(item) for item in value]
    return value


def _extract_food_keywords(text: str) -> list:
    lowered = _clean_text(text).lower()
    trigger_terms = [
        "line",
        "wait",
        "sold out",
        "worth the drive",
        "came from manhattan",
        "viral",
        "new menu",
        "opening",
        "soft opening",
        "reservation",
        "packed",
        "quiet work spot",
        "late night",
        "wifi",
        "outlet",
        "remote",
    ]
    hits = [term for term in trigger_terms if term in lowered]
    tokens = re.findall(r"[a-z][a-z0-9'-]{2,}", lowered)
    stopwords = {
        "and",
        "the",
        "for",
        "with",
        "this",
        "that",
        "from",
        "place",
        "food",
        "good",
        "very",
        "relative",
        "time",
        "author",
        "last",
        "week",
        "http",
        "https",
    }
    ranked = []
    for token in tokens:
        if token in stopwords or token in ranked:
            continue
        ranked.append(token)
    seen = set()  # type: ignore[var-annotated]
    return [keyword for keyword in [*hits, *ranked] if not (keyword in seen or seen.add(keyword))][:10]
