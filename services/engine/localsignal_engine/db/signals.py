from typing import List
from uuid import UUID

from psycopg.types.json import Jsonb

from localsignal_engine.models import Signal
from localsignal_engine.database.connection import get_conn
from localsignal_engine.signal.story import product_fields
from localsignal_engine.db.ingestion import _clean_json

DEFAULT_REGION = "Fort Lee / Edgewater / Palisades Park"


def write_signals(signals: list) -> list:
    signal_ids = []  # type: List[UUID]
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


def write_weekly_report(signals: list, region: str = DEFAULT_REGION) -> UUID:
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

            signal_ids = []  # type: List[UUID]
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


def _chunk_relevance(chunk_text: str, extracted_keywords: list, signal_keywords: list) -> float:
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


def _specific_signal_terms() -> set:
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


def _generic_review_terms() -> set:
    return {"good", "great", "amazing", "awesome", "nice", "service", "food", "staff", "experience", "atmosphere"}
