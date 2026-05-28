from fastapi import APIRouter, Depends, HTTPException

from app.db import get_connection
from app.models import ReportDTO
from app.presenters.signals import _signal_row

router = APIRouter()


@router.get("/reports/latest", response_model=ReportDTO)
def latest_report(conn=Depends(get_connection)) -> dict:
    report = conn.execute(
        """
        SELECT id, title, region, week_start::text AS week_start, intro, briefing
        FROM reports
        ORDER BY week_start DESC, created_at DESC
        LIMIT 1
        """
    ).fetchone()

    if not report:
        raise HTTPException(status_code=404, detail="No reports have been generated yet.")

    signals = conn.execute(
        """
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
        FROM report_signals rs
        JOIN signals s ON s.id = rs.signal_id
        JOIN places p ON p.id = s.place_id
        LEFT JOIN place_profiles pp ON pp.place_id = p.id
        WHERE rs.report_id = %s
        ORDER BY rs.rank ASC
        """,
        (report["id"],),
    ).fetchall()

    return {**report, "signals": [_signal_row(signal) for signal in signals]}
