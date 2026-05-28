from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_connection
from app.models import SignalDTO, SignalDetailDTO
from app.pipeline import slugify
from app.presenters.signals import (
    _baseline_context,
    _confidence,
    _confidence_reason,
    _evidence_item,
    _metrics,
    _related_signal_row,
    _restaurant_brief,
    _signal_row,
    _tags,
    _what_changed,
    _why_this_matters,
)

router = APIRouter()

# Shared SELECT fragment for signal list queries (excludes food_signal — not
# needed in card view; detail query fetches it separately).
_SIGNAL_SELECT = """
    SELECT
      s.id,
      s.slug,
      s.signal_type,
      s.title,
      COALESCE(s.short_summary, s.summary) AS summary,
      s.evidence,
      s.evidence_ids,
      s.score::float AS score,
      s.city,
      s.week_start::text AS week_start,
      json_build_object(
        'known_for', COALESCE(pp.known_for, ''),
        'food_types', COALESCE(pp.food_types, ARRAY[]::TEXT[]),
        'signature_items', COALESCE(pp.signature_items, ARRAY[]::TEXT[]),
        'flavor_cues', COALESCE(pp.flavor_cues, ARRAY[]::TEXT[]),
        'occasions', COALESCE(pp.occasions, ARRAY[]::TEXT[]),
        'caveats', COALESCE(pp.caveats, ''),
        'source_count', COALESCE(pp.source_count, 0),
        'profile', COALESCE(pp.profile, '{}'::jsonb),
        'updated_at', pp.updated_at::text
      ) AS place_profile,
      json_build_object(
        'id', p.id,
        'name', p.name,
        'address', p.address,
        'category', p.category,
        'city', p.city,
        'neighborhood', p.neighborhood,
        'lat', p.latitude,
        'lng', p.longitude,
        'google_place_id', p.google_place_id,
        'map_url', p.map_url
      ) AS place
    FROM signals s
    JOIN places p ON p.id = s.place_id
    LEFT JOIN place_profiles pp ON pp.place_id = p.id
"""


@router.get("/signals", response_model=list[SignalDTO])
def list_signals(
    city: Optional[str] = None,
    category: Optional[str] = None,
    signal_type: Optional[str] = None,
    time_window: Optional[str] = None,
    limit: int = 50,
    conn=Depends(get_connection),
) -> list[dict]:
    rows = conn.execute(
        _SIGNAL_SELECT + """
        WHERE s.status = 'published'
          AND (%s::text IS NULL OR s.city = %s)
          AND (%s::text IS NULL OR p.category = %s)
          AND (%s::text IS NULL OR s.signal_type = %s)
          AND (%s::text IS NULL OR s.time_window = %s)
        ORDER BY s.week_start DESC, s.score DESC
        LIMIT %s
        """,
        (city, city, category, category, signal_type, signal_type, time_window, time_window, min(limit, 100)),
    ).fetchall()
    return [_signal_row(row) for row in rows]


@router.get("/signals/{slug}", response_model=SignalDetailDTO)
def signal_detail(slug: str, conn=Depends(get_connection)) -> dict:
    rows = conn.execute(
        """
        SELECT
          s.id,
          s.slug,
          s.signal_type,
          s.title,
          COALESCE(s.short_summary, s.summary) AS summary,
          COALESCE(s.ai_summary, s.summary) AS ai_summary,
          s.why_this_matters,
          s.confidence_level,
          s.confidence_score::float AS confidence_score,
          s.confidence_reason,
          s.metrics,
          s.time_window,
          s.evidence,
          s.food_signal,
          s.evidence_ids,
          s.score::float AS score,
          s.city,
          s.week_start::text AS week_start,
          r.region,
          rs.rank,
          json_build_object(
            'known_for', COALESCE(pp.known_for, ''),
            'food_types', COALESCE(pp.food_types, ARRAY[]::TEXT[]),
            'signature_items', COALESCE(pp.signature_items, ARRAY[]::TEXT[]),
            'flavor_cues', COALESCE(pp.flavor_cues, ARRAY[]::TEXT[]),
            'occasions', COALESCE(pp.occasions, ARRAY[]::TEXT[]),
            'caveats', COALESCE(pp.caveats, ''),
            'source_count', COALESCE(pp.source_count, 0),
            'profile', COALESCE(pp.profile, '{}'::jsonb),
            'updated_at', pp.updated_at::text
          ) AS place_profile,
          json_build_object(
            'status', COALESCE(bp.baseline_status, 'Quiet baseline'),
            'heat_score', COALESCE(bp.baseline_heat_score::float, 0),
            'summary', COALESCE(bp.baseline_summary, ''),
            'trailing_30d_mentions', COALESCE(bp.trailing_30d_mentions, 0),
            'trailing_90d_mentions', COALESCE(bp.trailing_90d_mentions, 0),
            'trailing_365d_mentions', COALESCE(bp.trailing_365d_mentions, 0),
            'source_diversity', COALESCE(bp.source_diversity, 0),
            'recurring_keywords', COALESCE(bp.recurring_keywords, ARRAY[]::TEXT[])
          ) AS baseline_context,
          json_build_object(
            'id', p.id,
            'name', p.name,
            'address', p.address,
            'category', p.category,
            'city', p.city,
            'neighborhood', p.neighborhood,
            'lat', p.latitude,
            'lng', p.longitude,
            'google_place_id', p.google_place_id,
            'map_url', p.map_url
          ) AS place
        FROM report_signals rs
        JOIN reports r ON r.id = rs.report_id
        JOIN signals s ON s.id = rs.signal_id
        JOIN places p ON p.id = s.place_id
        LEFT JOIN baseline_profiles bp ON bp.place_id = p.id
        LEFT JOIN place_profiles pp ON pp.place_id = p.id
        ORDER BY r.week_start DESC, r.created_at DESC, rs.rank ASC
        """
    ).fetchall()

    signal = next((row for row in rows if (row.get("slug") or slugify(row["title"])) == slug), None)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found.")

    evidence = signal.get("evidence") or {}
    current_days = int(evidence.get("current_window_days") or 14)
    restaurant_brief = _restaurant_brief(conn, signal["place"]["id"])
    evidence_chunks = conn.execute(
        """
        SELECT
          ec.id::text AS id,
          rsi.platform,
          ec.occurred_at::text AS timestamp,
          ec.chunk_text AS excerpt,
          ec.extracted_keywords,
          ec.metadata,
          rsi.url AS source_url,
          rsi.engagement_metrics,
          rsi.geo_metadata
        FROM signal_evidence se
        JOIN evidence_chunks ec ON ec.id = se.evidence_chunk_id
        JOIN raw_source_items rsi ON rsi.id = ec.raw_source_item_id
        WHERE se.signal_id = %s
        ORDER BY se.rank ASC
        LIMIT 10
        """,
        (signal["id"],),
    ).fetchall()

    if not evidence_chunks:
        evidence_chunks = conn.execute(
            """
            SELECT
              NULL AS id,
              source AS platform,
              occurred_at::text AS timestamp,
              body AS excerpt,
              ARRAY[]::TEXT[] AS extracted_keywords,
              '{}'::jsonb AS metadata,
              source_url,
              '{}'::jsonb AS engagement_metrics,
              jsonb_build_object('region', author_region) AS geo_metadata
            FROM mentions
            WHERE place_id = %s
              AND occurred_at >= (now() - (%s || ' days')::interval)
            ORDER BY occurred_at DESC
            LIMIT 8
            """,
            (signal["place"]["id"], current_days),
        ).fetchall()

    if not evidence_chunks:
        evidence_chunks = conn.execute(
            """
            SELECT
              id::text AS id,
              source AS platform,
              COALESCE(occurred_at, fetched_at)::text AS timestamp,
              content AS excerpt,
              ARRAY[]::TEXT[] AS extracted_keywords,
              metadata,
              source_url,
              '{}'::jsonb AS engagement_metrics,
              '{}'::jsonb AS geo_metadata
            FROM place_documents
            WHERE place_id = %s
              AND content_type IN ('signal_evidence', 'review', 'place_profile', 'official_description', 'menu', 'website')
            ORDER BY
              CASE content_type
                WHEN 'signal_evidence' THEN 0
                WHEN 'review' THEN 1
                WHEN 'place_profile' THEN 2
                WHEN 'official_description' THEN 3
                ELSE 3
              END,
              COALESCE(occurred_at, fetched_at) DESC
            LIMIT 8
            """,
            (signal["place"]["id"],),
        ).fetchall()

    related_rows = conn.execute(
        """
        SELECT
          rsig.id,
          COALESCE(rsig.slug, regexp_replace(lower(rsig.title), '[^a-z0-9]+', '-', 'g')) AS slug,
          rsig.title,
          rsig.signal_type,
          rsig.score::float AS score,
          json_build_object(
            'name', rp.name,
            'neighborhood', rp.neighborhood,
            'category', rp.category
          ) AS place
        FROM signal_relations sr
        JOIN signals rsig ON rsig.id = sr.related_signal_id
        JOIN places rp ON rp.id = rsig.place_id
        WHERE sr.signal_id = %s
        ORDER BY sr.rank ASC
        LIMIT 3
        """,
        (signal["id"],),
    ).fetchall()

    related = [_related_signal_row(row) for row in related_rows] or [
        _related_signal_row(row)
        for row in rows
        if row["id"] != signal["id"]
        and (
            row["city"] == signal["city"]
            or row["place"]["category"] == signal["place"]["category"]
            or set(_tags(row)).intersection(_tags(signal))
        )
    ][:3]

    return {
        **_signal_row(signal),
        "rank": signal["rank"],
        "region": signal["region"],
        "date_range": signal.get("time_window") or f"Last {current_days} days",
        "tags": _tags(signal),
        "ai_summary": signal.get("ai_summary") or signal["summary"],
        "what_changed": _what_changed(signal),
        "why_this_matters": signal.get("why_this_matters") or _why_this_matters(signal),
        "confidence": signal.get("confidence_level") or _confidence(signal),
        "confidence_reason": signal.get("confidence_reason") or _confidence_reason(signal),
        "baseline_context": _baseline_context(signal),
        "metrics": signal.get("metrics") or _metrics(signal),
        "restaurant_brief": restaurant_brief,
        "evidence_items": [_evidence_item(row, signal) for row in evidence_chunks],
        "related_signals": related,
    }
