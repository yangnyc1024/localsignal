import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from localsignal_engine.ingestion.social_metadata import SocialMetadataItem
from localsignal_engine.models import Mention, Place, Signal
from localsignal_engine.database.connection import get_conn
from localsignal_engine.signal.story import (
    confidence_from_evidence,
    product_fields,
    story_fields_for_signal,
)


DEFAULT_REGION = "Fort Lee / Edgewater / Palisades Park"


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
    source_counts: dict[str, int],
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
    source_counts: Optional[dict[str, int]] = None,
    error: Optional[str] = None,
) -> None:
    if not __import__('os').getenv('DATABASE_URL'):
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


def load_places() -> list[Place]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id::text, name, category, city, neighborhood, latitude, longitude, google_place_id, map_url
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
            latitude=row[5],
            longitude=row[6],
            google_place_id=row[7],
            map_url=row[8],
        )
        for row in rows
    ]


def upsert_places_from_discovery(places: list[dict]) -> int:
    if not places:
        return 0

    written = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_places_google_place_id ON places(google_place_id) WHERE google_place_id IS NOT NULL"
            )
            for place in places:
                cur.execute(
                    """
                    INSERT INTO places (
                      name,
                      category,
                      address,
                      city,
                      neighborhood,
                      latitude,
                      longitude,
                      google_place_id,
                      map_url
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (google_place_id) WHERE google_place_id IS NOT NULL
                    DO UPDATE SET
                      name = EXCLUDED.name,
                      category = EXCLUDED.category,
                      address = EXCLUDED.address,
                      city = EXCLUDED.city,
                      neighborhood = EXCLUDED.neighborhood,
                      latitude = EXCLUDED.latitude,
                      longitude = EXCLUDED.longitude,
                      map_url = EXCLUDED.map_url
                    RETURNING id
                    """,
                    (
                        place["name"],
                        place["category"],
                        place.get("address"),
                        place["city"],
                        place.get("neighborhood"),
                        place.get("latitude"),
                        place.get("longitude"),
                        place.get("google_place_id"),
                        place.get("map_url"),
                    ),
                )
                if cur.fetchone():
                    written += 1
        conn.commit()
    return written


def write_mentions(mentions: list[Mention]) -> int:
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


def write_raw_source_items_from_mentions(mentions: list[Mention]) -> tuple[int, int]:
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


def write_social_metadata_items(items: list[SocialMetadataItem]) -> tuple[int, int, int, int, int]:
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


def link_evidence_chunks_to_signals(limit_per_signal: int = 10) -> int:

    linked = 0
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
              id,
              place_id,
              evidence
            FROM signals
            WHERE status = 'published'
            ORDER BY week_start DESC, score DESC
            """
        ).fetchall()

        with conn.cursor() as cur:
            for signal_id, place_id, evidence in rows:
                keywords = [str(keyword).lower() for keyword in (evidence or {}).get("keywords", [])]
                current_days = int((evidence or {}).get("current_window_days") or 14)
                cur.execute("DELETE FROM signal_evidence WHERE signal_id = %s", (signal_id,))
                chunks = cur.execute(
                    """
                    SELECT
                      e.id,
                      lower(e.chunk_text) AS chunk_text,
                      e.extracted_keywords,
                      e.occurred_at
                    FROM evidence_chunks e
                    JOIN raw_source_items r ON r.id = e.raw_source_item_id
                    WHERE e.place_id = %s
                      AND e.occurred_at >= now() - (%s || ' days')::interval
                      AND r.platform <> 'google_places'
                      AND length(e.chunk_text) >= 25
                    ORDER BY occurred_at DESC
                    LIMIT 30
                    """,
                    (place_id, current_days),
                ).fetchall()
                ranked = sorted(
                    (
                        (_chunk_relevance(chunk_text, extracted_keywords, keywords), chunk_id)
                        for chunk_id, chunk_text, extracted_keywords, _occurred_at in chunks
                    ),
                    key=lambda item: item[0],
                    reverse=True,
                )[:limit_per_signal]

                linked_ids = []
                for rank, (score, chunk_id) in enumerate(ranked, start=1):
                    if score <= 0:
                        continue
                    cur.execute(
                        """
                        INSERT INTO signal_evidence (signal_id, evidence_chunk_id, relevance_score, rank)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (signal_id, evidence_chunk_id)
                        DO UPDATE SET
                          relevance_score = EXCLUDED.relevance_score,
                          rank = EXCLUDED.rank
                        """,
                        (signal_id, chunk_id, score, rank),
                    )
                    linked_ids.append(chunk_id)
                    linked += 1
                cur.execute("UPDATE signals SET evidence_ids = %s WHERE id = %s", (linked_ids, signal_id))
        conn.commit()
    return linked


def load_recent_mentions(days: int = 35) -> list[Mention]:

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


def _extract_food_keywords(text: str) -> list[str]:
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
    seen: set[str] = set()
    return [keyword for keyword in [*hits, *ranked] if not (keyword in seen or seen.add(keyword))][:10]


def _chunk_relevance(chunk_text: str, extracted_keywords: list[str], signal_keywords: list[str]) -> float:
    text = chunk_text.lower()
    extracted = {str(keyword).lower() for keyword in extracted_keywords or []}
    keywords = [keyword.lower() for keyword in signal_keywords if keyword]
    keyword_hits = sum(1 for keyword in keywords if keyword in text or keyword in extracted)
    specificity_hits = sum(1 for term in _specific_signal_terms() if term in text or term in extracted)
    generic_hits = sum(1 for term in _generic_review_terms() if term in text or term in extracted)

    if not keywords and not specificity_hits:
        return 0.15

    score = 0.18 + min(keyword_hits * 0.12, 0.36) + min(specificity_hits * 0.16, 0.42)
    if generic_hits and not specificity_hits:
        score -= 0.12
    if len(text) >= 80:
        score += 0.06
    return max(0.05, min(1.0, score))


def _specific_signal_terms() -> set[str]:
    return {
        "line",
        "wait",
        "packed",
        "sold out",
        "worth the drive",
        "came from manhattan",
        "viral",
        "new menu",
        "opening",
        "soft opening",
        "reservation",
        "late night",
        "wifi",
        "remote",
        "outlet",
        "bread",
        "pizza",
        "coffee",
        "chicken",
        "wings",
        "salt",
        "salty",
        "noodle",
        "tofu",
        "bbq",
        "sauce",
        "dessert",
        "matcha",
        "bakery",
        "brunch",
        "pancake",
        "vegetables",
        "mala",
        "malatang",
    }


def _generic_review_terms() -> set[str]:
    return {"good", "great", "amazing", "awesome", "nice", "service", "food", "staff", "experience", "atmosphere"}


def write_signals(signals: list[Signal]) -> list[UUID]:
    signal_ids: list[UUID] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            for signal in signals:
                product = product_fields(signal)
                cur.execute(
                    """
                    INSERT INTO signals (
                      slug,
                      place_id,
                      signal_type,
                      title,
                      summary,
                      short_summary,
                      ai_summary,
                      why_this_matters,
                      confidence_level,
                      confidence_score,
                      confidence_reason,
                      metrics,
                      time_window,
                      status,
                      published_at,
                      evidence,
                      score,
                      city,
                      week_start
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'published', now(), %s::jsonb, %s, %s, %s)
                    ON CONFLICT (place_id, signal_type, week_start)
                    DO UPDATE SET
                      slug = EXCLUDED.slug,
                      title = EXCLUDED.title,
                      summary = EXCLUDED.summary,
                      short_summary = EXCLUDED.short_summary,
                      ai_summary = EXCLUDED.ai_summary,
                      why_this_matters = EXCLUDED.why_this_matters,
                      confidence_level = EXCLUDED.confidence_level,
                      confidence_score = EXCLUDED.confidence_score,
                      confidence_reason = EXCLUDED.confidence_reason,
                      metrics = EXCLUDED.metrics,
                      time_window = EXCLUDED.time_window,
                      status = EXCLUDED.status,
                      published_at = COALESCE(signals.published_at, now()),
                      evidence = EXCLUDED.evidence,
                      score = EXCLUDED.score,
                      city = EXCLUDED.city,
                      created_at = now()
                    RETURNING id
                    """,
                    (
                        product["slug"],
                        signal.place.id,
                        signal.signal_type,
                        signal.title,
                        signal.summary,
                        product["short_summary"],
                        product["ai_summary"],
                        product["why_this_matters"],
                        product["confidence_level"],
                        product["confidence_score"],
                        product["confidence_reason"],
                        Jsonb(_clean_json(product["metrics"])),
                        product["time_window"],
                        Jsonb(_clean_json(signal.evidence)),
                        signal.score,
                        signal.place.city,
                        signal.week_start,
                    ),
                )
                signal_ids.append(cur.fetchone()[0])
        conn.commit()
    return signal_ids


def write_weekly_report(signals: list[Signal], region: str = DEFAULT_REGION) -> UUID:
    if not signals:
        raise RuntimeError("No signals available for report generation.")

    week_start = signals[0].week_start
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS briefing JSONB NOT NULL DEFAULT '{}'::jsonb")
            cur.execute(
                """
                INSERT INTO reports (title, region, week_start, intro, briefing)
                VALUES (%s, %s, %s, %s, '{}'::jsonb)
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
                product = product_fields(signal)
                cur.execute(
                    """
                    INSERT INTO signals (
                      slug,
                      place_id,
                      signal_type,
                      title,
                      summary,
                      short_summary,
                      ai_summary,
                      why_this_matters,
                      confidence_level,
                      confidence_score,
                      confidence_reason,
                      metrics,
                      time_window,
                      status,
                      published_at,
                      evidence,
                      score,
                      city,
                      week_start
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'published', now(), %s::jsonb, %s, %s, %s)
                    ON CONFLICT (place_id, signal_type, week_start)
                    DO UPDATE SET
                      slug = EXCLUDED.slug,
                      title = EXCLUDED.title,
                      summary = EXCLUDED.summary,
                      short_summary = EXCLUDED.short_summary,
                      ai_summary = EXCLUDED.ai_summary,
                      why_this_matters = EXCLUDED.why_this_matters,
                      confidence_level = EXCLUDED.confidence_level,
                      confidence_score = EXCLUDED.confidence_score,
                      confidence_reason = EXCLUDED.confidence_reason,
                      metrics = EXCLUDED.metrics,
                      time_window = EXCLUDED.time_window,
                      status = EXCLUDED.status,
                      published_at = COALESCE(signals.published_at, now()),
                      evidence = EXCLUDED.evidence,
                      score = EXCLUDED.score,
                      city = EXCLUDED.city,
                      created_at = now()
                    RETURNING id
                    """,
                    (
                        product["slug"],
                        signal.place.id,
                        signal.signal_type,
                        signal.title,
                        signal.summary,
                        product["short_summary"],
                        product["ai_summary"],
                        product["why_this_matters"],
                        product["confidence_level"],
                        product["confidence_score"],
                        product["confidence_reason"],
                        Jsonb(_clean_json(product["metrics"])),
                        product["time_window"],
                        Jsonb(_clean_json(signal.evidence)),
                        signal.score,
                        signal.place.city,
                        signal.week_start,
                    ),
                )
                signal_ids.append(cur.fetchone()[0])

            cur.execute("DELETE FROM report_signals WHERE report_id = %s", (report_id,))
            for rank, signal_id in enumerate(signal_ids, start=1):
                cur.execute("UPDATE signals SET rank = %s WHERE id = %s", (rank, signal_id))
                cur.execute(
                    """
                    INSERT INTO report_signals (report_id, signal_id, rank)
                    VALUES (%s, %s, %s)
                    """,
                    (report_id, signal_id, rank),
                )

        conn.commit()
    return report_id

