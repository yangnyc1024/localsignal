import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from localsignal_engine.ingestion.social_metadata import SocialMetadataItem
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
    report_id: Optional[UUID] = None,
    error: Optional[str] = None,
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
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return
    with psycopg.connect(database_url) as conn:
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
                Jsonb(source_counts or {}),
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
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to load places.")

    with psycopg.connect(database_url) as conn:
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
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to upsert discovered places.")
    if not places:
        return 0

    written = 0
    with psycopg.connect(database_url) as conn:
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
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to write mentions.")
    if not mentions:
        return 0

    written = 0
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for mention in mentions:
                if _insert_mention(cur, mention):
                    written += 1
        conn.commit()
    return written


def write_raw_source_items_from_mentions(mentions: list[Mention]) -> tuple[int, int]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to write raw source items.")
    if not mentions:
        return 0, 0

    raw_written = 0
    chunks_written = 0
    with psycopg.connect(database_url) as conn:
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
                        Jsonb({"source": mention.source}),
                    ),
                )
                if cur.fetchone():
                    chunks_written += 1
        conn.commit()
    return raw_written, chunks_written


def write_social_metadata_items(items: list[SocialMetadataItem]) -> tuple[int, int, int, int, int]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to write social metadata items.")
    if not items:
        return 0, 0, 0, 0, 0

    raw_written = 0
    mentions_written = 0
    chunks_written = 0
    review_count = 0
    unresolved_count = 0
    with psycopg.connect(database_url) as conn:
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
                        Jsonb(
                            {
                                "source": item.platform,
                                "resolution_confidence": item.place_resolution_confidence,
                                "engagement_metrics": item.engagement_metrics,
                            }
                        ),
                    ),
                )
                if cur.fetchone():
                    chunks_written += 1
        conn.commit()
    return raw_written, mentions_written, chunks_written, review_count, unresolved_count


def link_evidence_chunks_to_signals(limit_per_signal: int = 10) -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to link evidence chunks.")

    linked = 0
    with psycopg.connect(database_url) as conn:
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
                Jsonb(mention.engagement_metrics or {}),
                Jsonb(_geo_metadata_for_mention(mention)),
                Jsonb({**(mention.raw_json or {}), "rating": mention.rating}),
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
            Jsonb(mention.engagement_metrics or {}),
            Jsonb(_geo_metadata_for_mention(mention)),
            Jsonb({**(mention.raw_json or {}), "rating": mention.rating}),
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
                Jsonb(item.engagement_metrics),
                Jsonb(item.geo_metadata),
                Jsonb(item.raw_json),
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
            Jsonb(item.engagement_metrics),
            Jsonb(item.geo_metadata),
            Jsonb(item.raw_json),
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
    return re.sub(r"\s+", " ", text).strip()


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
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to write signals.")

    signal_ids: list[UUID] = []
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for signal in signals:
                product = _product_fields(signal)
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
                        Jsonb(product["metrics"]),
                        product["time_window"],
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
                product = _product_fields(signal)
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
                        Jsonb(product["metrics"]),
                        product["time_window"],
                        Jsonb(signal.evidence),
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



def _story_fields_for_signal(signal: Signal) -> dict:
    evidence = signal.evidence
    keywords = [str(keyword) for keyword in evidence.get("keywords", [])]
    category = signal.place.category.replace("_", " ").title()
    topic, keyword_text = _story_topic(keywords, category)
    area = signal.place.neighborhood or signal.place.city
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    if signal.signal_type == "sentiment_shift":
        phenomenon_title = f"{signal.place.name} has a changing wait-time read" if topic == "Wait-time" else f"{signal.place.name} has a changing {topic.lower()} read"
    elif signal.signal_type == "behavior_shift":
        phenomenon_title = f"{signal.place.name} has a changing {topic.lower()} visit read"
    elif signal.signal_type == "review_velocity_spike":
        phenomenon_title = f"{signal.place.name} is getting more recent attention for {topic.lower()}"
    else:
        phenomenon_title = f"{signal.place.name} is showing repeated language around {topic.lower()}"
    return {
        "phenomenon_title": phenomenon_title,
        "food_or_cuisine_type": category,
        "place_anchor_reason": f"{signal.place.name} is the place where this food read is anchored, not a blanket recommendation.",
        "reader_hook": phenomenon_title,
        "what_to_notice": f"Watch the repeated language around {keyword_text}; do not read this as a best-of ranking.",
        "skeptic_note": "Evidence is still narrow until it repeats across more independent sources.",
        "good_for": f"People tracking {keyword_text} movement near {area}.",
        "watch_out": "Read this as movement evidence, not a taste ranking.",
        "best_read_as": "A local food signal to notice, with judgment left to the reader.",
        "evidence_receipt": {
            "recent_mentions": str(mention_count or "Building"),
            "source_types": str(source_count or 1),
            "repeated_terms": keyword_text,
            "freshness": f"Last {evidence.get('current_window_days', 7)} days",
            "evidence_read": _confidence_from_evidence(evidence)[0],
        },
    }


def _story_topic(keywords: list[str], category: str) -> tuple[str, str]:
    allowed_terms = {
        "line", "wait", "wait time", "sold out", "worth the drive", "viral", "new menu",
        "opening", "soft opening", "reservation", "packed", "quiet work spot", "late night",
        "pizza", "sourdough", "bread", "pastry", "croissant", "bun", "cake", "dessert",
        "matcha", "cream", "coffee", "latte", "seafood", "crab", "chicken wings", "wings",
        "bbq", "korean bbq", "ramen", "sushi", "gyro", "kebab", "falafel", "empanadas",
    }
    normalized = [str(keyword).strip().lower() for keyword in keywords if str(keyword).strip()]
    useful = [keyword for keyword in normalized if keyword in allowed_terms]
    if "chicken" in normalized and "wings" in normalized and "chicken wings" not in useful:
        useful.insert(0, "chicken wings")
    if useful:
        label_map = {"wait": "Wait-time", "wait time": "Wait-time", "late night": "Late-night", "chicken wings": "Chicken wings"}
        topic = label_map.get(useful[0], " ".join(part.capitalize() for part in useful[0].split()))
        return topic, ", ".join(useful[:3])
    fallback = category or "Food"
    return fallback, fallback.lower()


def _product_fields(signal: Signal) -> dict:
    evidence = signal.evidence
    current_days = evidence.get("current_window_days", 14)
    metrics = _metrics_from_evidence(signal)
    confidence_level, confidence_score, confidence_reason = _confidence_from_evidence(evidence)
    short_summary = _short_summary(signal)
    story_fields = _story_fields_for_signal(signal)
    signal.evidence.update({key: value for key, value in story_fields.items() if key not in signal.evidence or not signal.evidence.get(key)})
    return {
        "slug": _slugify(story_fields.get("phenomenon_title") or signal.title),
        "short_summary": short_summary,
        "ai_summary": _ai_summary(signal, short_summary),
        "why_this_matters": _why_this_matters(signal),
        "confidence_level": confidence_level,
        "confidence_score": confidence_score,
        "confidence_reason": confidence_reason,
        "metrics": metrics,
        "time_window": f"Last {current_days} days",
    }


def _metrics_from_evidence(signal: Signal) -> list[dict]:
    evidence = signal.evidence
    keywords = evidence.get("keywords", [])
    metrics = [
        {
            "label": "Keyword growth",
            "value": f"{len(keywords)} active terms" if keywords else "Emerging",
            "detail": ", ".join(keywords[:3]) if keywords else "New language is clustering around this signal.",
            "trend": "up",
        },
        {
            "label": "Mention velocity",
            "value": f"{float(evidence.get('velocity_ratio')):.1f}x baseline"
            if evidence.get("velocity_ratio") is not None
            else "Above baseline",
            "detail": "Compared with the recent baseline window.",
            "trend": "up",
        },
        {
            "label": "Source diversity",
            "value": f"{int(evidence.get('source_count') or len(evidence.get('sources', [])))} source(s)",
            "detail": "Independent sources make a signal more trustworthy.",
            "trend": "steady",
        },
        {
            "label": "Location spread",
            "value": f"{int(evidence.get('outside_region_count') or 0)} outside area(s)",
            "detail": "Cross-neighborhood attention is treated as momentum.",
            "trend": "up" if evidence.get("outside_region_count") else "steady",
        },
    ]
    return metrics


def _confidence_from_evidence(evidence: dict) -> tuple[str, float, str]:
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    outside_regions = int(evidence.get("outside_region_count") or 0)
    score = min(100, source_count * 24 + min(mention_count, 5) * 12 + outside_regions * 8)
    if score >= 78:
        return "High", float(score), f"High confidence because this repeats across {source_count} source(s) and {mention_count} recent mention(s)."
    if score >= 48:
        return "Medium", float(score), "Medium confidence because the signal has some repetition, but evidence depth is still developing."
    return "Low", float(score), "Low confidence because repetition or source diversity is limited."


def _short_summary(signal: Signal) -> str:
    evidence = signal.evidence
    keywords = evidence.get("keywords", [])
    keyword_text = ", ".join(keywords[:3]) if keywords else "recent food-language"
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    velocity = evidence.get("velocity_ratio")
    spread = int(evidence.get("outside_region_count") or 0)

    if signal.signal_type == "behavior_shift":
        return f"Recent evidence points to a usage shift around {keyword_text}, with {source_count or 1} source type(s) contributing."
    if signal.signal_type == "sentiment_shift":
        return f"Recent language around {keyword_text} suggests a directional quality or service change worth monitoring."
    if spread:
        return f"Attention around {keyword_text} is showing signs of cross-neighborhood pull, not just local familiarity."
    if source_count >= 3:
        return f"Activity is appearing across {source_count} source types, with repeated language around {keyword_text}."
    if velocity is not None and float(velocity) >= 5:
        return f"Recent activity is materially above the short-term baseline, led by language around {keyword_text}."
    return signal.summary


def _ai_summary(signal: Signal, short_summary: str) -> str:
    evidence = signal.evidence
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    return (
        f"{short_summary} The signal is based on {mention_count} recent matched mention(s) "
        f"across {source_count or 1} source type(s), so it should be read as momentum evidence rather than a quality ranking."
    )


def _why_this_matters(signal: Signal) -> str:
    if signal.signal_type == "behavior_shift":
        return f"{signal.place.name} is showing behavior change, which can indicate a new food-use occasion rather than normal attention."
    if signal.signal_type == "sentiment_shift":
        return f"{signal.place.name} has a directional service or wait-time signal worth watching because momentum can change quickly when complaints repeat."
    if signal.signal_type == "review_velocity_spike":
        return f"{signal.place.name} is gaining attention faster than its recent baseline, suggesting broader food discovery momentum."
    return f"{signal.place.name} has new language clustering around it, which can be an early indicator of emerging demand."


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "signal"
