import re
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from psycopg.types.json import Jsonb

from app.config import settings
from app.db import get_connection
from app.models import (
    FeedbackCreate,
    FeedbackDTO,
    EmailDeliveryDTO,
    ReportDTO,
    IngestionRunDTO,
    AlwaysHotDTO,
    BaselineContextDTO,
    PipelineActionDTO,
    SignalDetailDTO,
    SignalDTO,
    SocialSourceRunDTO,
    SubscriberCreate,
    SubscriberDTO,
)
from app.openai_pipeline import OpenAIPipelineError, embed_texts, openai_enabled, vector_literal
from app.openai_pipeline import generate_signal_json
from app.pipeline import build_llm_prompt, confidence_from_metrics, extract_keywords, score_candidate, slugify

app = FastAPI(
    title="LocalSignal API",
    description="API for local change intelligence reports and feedback.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/signals", response_model=list[SignalDTO])
def list_signals(
    city: Optional[str] = None,
    category: Optional[str] = None,
    signal_type: Optional[str] = None,
    time_window: Optional[str] = None,
    limit: int = 50,
    conn=Depends(get_connection),
) -> list[dict]:
    rows = conn.execute(
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
        FROM signals s
        JOIN places p ON p.id = s.place_id
        LEFT JOIN place_profiles pp ON pp.place_id = p.id
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


@app.get("/reports/latest", response_model=ReportDTO)
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


@app.get("/api/baseline/always-hot", response_model=list[AlwaysHotDTO])
def always_hot(limit: int = 5, conn=Depends(get_connection)) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
          p.id AS place_id,
          p.name AS place_name,
          p.category,
          p.neighborhood,
          p.city,
          bp.baseline_status AS status,
          bp.baseline_heat_score::float AS heat_score,
          bp.baseline_summary AS summary,
          bp.recurring_keywords,
          bp.source_diversity
        FROM baseline_profiles bp
        JOIN places p ON p.id = bp.place_id
        WHERE bp.baseline_heat_score > 0
        ORDER BY bp.baseline_heat_score DESC, bp.trailing_365d_mentions DESC
        LIMIT %s
        """,
        (min(limit, 10),),
    ).fetchall()
    return rows


@app.get("/api/source-health/social", response_model=list[SocialSourceRunDTO])
def social_source_health(limit: int = 20, conn=Depends(get_connection)) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
          id,
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
          error,
          started_at::text,
          finished_at::text
        FROM social_source_runs
        ORDER BY finished_at DESC
        LIMIT %s
        """,
        (min(limit, 50),),
    ).fetchall()
    return [dict(row) for row in rows]


@app.get("/signals/{slug}", response_model=SignalDetailDTO)
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


@app.post("/api/ingest/run", response_model=PipelineActionDTO)
def trigger_ingestion(
    dry_run: bool = True,
    x_admin_token: Optional[str] = Header(default=None),
    conn=Depends(get_connection),
) -> dict:
    _require_admin(x_admin_token)
    migrated = 0
    chunks = 0
    if not dry_run:
        mentions = conn.execute(
            """
            SELECT
              id,
              place_id,
              source,
              source_url,
              author_region,
              body,
              occurred_at,
              rating,
              sentiment
            FROM mentions
            ORDER BY occurred_at DESC
            """
        ).fetchall()
        for mention in mentions:
            raw_item = conn.execute(
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
                VALUES (%s, %s, %s, %s, %s, '{}'::jsonb, %s::jsonb, %s::jsonb, 1, 'resolved')
                ON CONFLICT (platform, url) WHERE url IS NOT NULL
                DO UPDATE SET
                  place_id = EXCLUDED.place_id,
                  text = EXCLUDED.text,
                  occurred_at = EXCLUDED.occurred_at,
                  geo_metadata = EXCLUDED.geo_metadata,
                  raw_json = EXCLUDED.raw_json,
                  updated_at = now()
                RETURNING id
                """,
                (
                    mention["source"],
                    mention["source_url"],
                    mention["place_id"],
                    mention["body"],
                    mention["occurred_at"],
                    Jsonb({"region": mention["author_region"]} if mention["author_region"] else {}),
                    Jsonb({"legacy_mention_id": str(mention["id"]), "rating": mention["rating"]}),
                ),
            ).fetchone()
            if not raw_item:
                raw_item = conn.execute(
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
                    VALUES (%s, %s, %s, %s, '{}'::jsonb, %s::jsonb, %s::jsonb, 1, 'resolved')
                    RETURNING id
                    """,
                    (
                        mention["source"],
                        mention["place_id"],
                        mention["body"],
                        mention["occurred_at"],
                        Jsonb({"region": mention["author_region"]} if mention["author_region"] else {}),
                        Jsonb({"legacy_mention_id": str(mention["id"]), "rating": mention["rating"]}),
                    ),
                ).fetchone()
            migrated += 1

            exists = conn.execute(
                "SELECT 1 FROM evidence_chunks WHERE raw_source_item_id = %s LIMIT 1",
                (raw_item["id"],),
            ).fetchone()
            if exists:
                continue

            conn.execute(
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
                VALUES (%s, %s, %s, %s, %s, %s, '{}'::jsonb)
                """,
                (
                    raw_item["id"],
                    mention["place_id"],
                    mention["body"],
                    extract_keywords(mention["body"]),
                    mention["sentiment"],
                    mention["occurred_at"],
                ),
            )
            chunks += 1
        conn.commit()

    metrics = {
        "dry_run": dry_run,
        "legacy_mentions_migrated": migrated,
        "evidence_chunks_created": chunks,
        "supported_sources": ["google_reviews", "reddit", "tiktok_metadata", "instagram_metadata", "local_blogs_news"],
        "note": "Live ingestion remains owned by the engine adapters; this endpoint records an admin pipeline trigger.",
    }
    _record_pipeline_run(conn, "ingest", "succeeded", metrics)
    return {
        "step": "ingest",
        "status": "succeeded",
        "metrics": metrics,
        "message": "Ingestion trigger recorded. Use the engine scheduler to fetch source data.",
    }


@app.post("/api/signals/detect", response_model=PipelineActionDTO)
def trigger_signal_detection(
    dry_run: bool = True,
    x_admin_token: Optional[str] = Header(default=None),
    conn=Depends(get_connection),
) -> dict:
    _require_admin(x_admin_token)
    rows = _current_signal_rows(conn)
    candidates = []
    for row in rows:
        evidence = row.get("evidence") or {}
        metrics = {
            **evidence,
            "keyword_count": len(evidence.get("keywords", [])),
            "signal_score": row["score"],
        }
        candidate_score, component_scores = score_candidate(metrics)
        candidates.append(
            {
                "place_id": str(row["place"]["id"]),
                "signal_type": row["signal_type"],
                "time_window": row.get("time_window") or f"Last {evidence.get('current_window_days', 14)} days",
                "detected_metrics": metrics,
                "component_scores": component_scores,
                "candidate_score": candidate_score,
                "trigger_reason": row["summary"],
            }
        )

    if not dry_run:
        for candidate in candidates:
            conn.execute(
                """
                INSERT INTO signal_candidates (
                  place_id,
                  signal_type,
                  time_window,
                  detected_metrics,
                  component_scores,
                  candidate_score,
                  trigger_reason
                )
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                """,
                (
                    candidate["place_id"],
                    candidate["signal_type"],
                    candidate["time_window"],
                    Jsonb(candidate["detected_metrics"]),
                    Jsonb(candidate["component_scores"]),
                    candidate["candidate_score"],
                    candidate["trigger_reason"],
                ),
            )
        conn.commit()

    metrics = {"dry_run": dry_run, "candidates_generated": len(candidates), "candidates": candidates[:10]}
    _record_pipeline_run(conn, "detect", "succeeded", metrics)
    return {
        "step": "detect",
        "status": "succeeded",
        "metrics": metrics,
        "message": "Signal candidates computed from real signal/evidence metrics.",
    }


@app.post("/api/signals/generate", response_model=PipelineActionDTO)
def trigger_llm_generation(
    x_admin_token: Optional[str] = Header(default=None),
    conn=Depends(get_connection),
) -> dict:
    _require_admin(x_admin_token)
    if not openai_enabled():
        metrics = {"provider_call_performed": False, "error": "OPENAI_API_KEY is not configured."}
        _record_pipeline_run(conn, "generate", "failed", metrics, metrics["error"])
        raise HTTPException(status_code=400, detail=metrics["error"])

    candidates = conn.execute(
        """
        SELECT
          sc.id::text,
          sc.place_id,
          sc.signal_type,
          sc.time_window,
          sc.detected_metrics,
          sc.component_scores,
          sc.candidate_score::float,
          sc.trigger_reason,
          json_build_object(
            'id', p.id,
            'name', p.name,
            'category', p.category,
            'address', p.address,
            'neighborhood', p.neighborhood,
            'city', p.city
          ) AS place
        FROM signal_candidates sc
        JOIN places p ON p.id = sc.place_id
        WHERE sc.status = 'draft'
        ORDER BY sc.candidate_score DESC, sc.created_at DESC
        LIMIT 10
        """
    ).fetchall()
    generated = []
    failures = []
    skipped = []
    for candidate in candidates:
        try:
            gate_reason = _candidate_gate_reason(candidate)
            if gate_reason:
                skipped.append({"candidate_id": candidate["id"], "reason": gate_reason})
                continue
            evidence_chunks = _retrieve_candidate_evidence(conn, candidate)
            if len(evidence_chunks) < settings.signal_generate_min_evidence_count:
                skipped.append(
                    {
                        "candidate_id": candidate["id"],
                        "reason": (
                            f"Only {len(evidence_chunks)} evidence chunk(s); "
                            f"minimum is {settings.signal_generate_min_evidence_count}."
                        ),
                    }
                )
                continue
            prompt = build_llm_prompt(candidate["place"], candidate, evidence_chunks)
            llm_result = generate_signal_json(prompt)
            signal_id = _write_generated_signal(conn, candidate, llm_result, evidence_chunks)
            generated.append({"candidate_id": candidate["id"], "signal_id": str(signal_id)})
        except OpenAIPipelineError as exc:
            failures.append({"candidate_id": candidate["id"], "error": str(exc)})

    metrics = {
        "candidate_count": len(candidates),
        "signals_generated": len(generated),
        "skipped": skipped,
        "failures": failures,
        "json_schema": build_llm_prompt({}, {}, [])["json_schema"],
        "provider_call_performed": bool(candidates),
        "embedding_model": settings.openai_embedding_model,
        "generation_model": settings.openai_model,
    }
    status_value = "succeeded" if not failures else "failed"
    _record_pipeline_run(conn, "generate", status_value, metrics, failures[0]["error"] if failures else None)
    if failures and not generated:
        raise HTTPException(status_code=502, detail=failures[0]["error"])
    return {
        "step": "generate",
        "status": status_value,
        "metrics": metrics,
        "message": "LLM generation completed for draft signal candidates.",
    }


@app.post("/api/signals/publish", response_model=PipelineActionDTO)
def publish_ready_signals(
    x_admin_token: Optional[str] = Header(default=None),
    conn=Depends(get_connection),
) -> dict:
    _require_admin(x_admin_token)
    rows = conn.execute(
        """
        SELECT id, evidence, metrics, confidence_reason
        FROM signals
        WHERE status = 'draft'
        """
    ).fetchall()
    publishable = [row for row in rows if _passes_publish_checks(row)]
    for row in publishable:
        conn.execute(
            """
            UPDATE signals
            SET status = 'published', published_at = COALESCE(published_at, now())
            WHERE id = %s
            """,
            (row["id"],),
        )
    conn.commit()

    metrics = {"draft_count": len(rows), "published_count": len(publishable)}
    _record_pipeline_run(conn, "publish", "succeeded", metrics)
    return {
        "step": "publish",
        "status": "succeeded",
        "metrics": metrics,
        "message": "Draft signals passing quality checks were published.",
    }


@app.post("/feedback", response_model=FeedbackDTO, status_code=status.HTTP_201_CREATED)
def create_feedback(payload: FeedbackCreate, conn=Depends(get_connection)) -> dict:
    signal_exists = conn.execute(
        "SELECT 1 FROM signals WHERE id = %s",
        (payload.signal_id,),
    ).fetchone()

    if not signal_exists:
        raise HTTPException(status_code=404, detail="Signal not found.")

    row = conn.execute(
        """
        INSERT INTO feedback_events (signal_id, event_type, session_id)
        VALUES (%s, %s, %s)
        RETURNING id, signal_id, event_type, session_id
        """,
        (payload.signal_id, payload.event_type, payload.session_id),
    ).fetchone()
    conn.commit()
    return row


@app.post("/subscribers", response_model=SubscriberDTO, status_code=status.HTTP_201_CREATED)
def create_subscriber(payload: SubscriberCreate, conn=Depends(get_connection)) -> dict:
    row = conn.execute(
        """
        INSERT INTO subscribers (email, region, status, updated_at)
        VALUES (%s, %s, 'active', now())
        ON CONFLICT (email)
        DO UPDATE SET
          region = EXCLUDED.region,
          status = 'active',
          updated_at = now()
        RETURNING id, email, region, status
        """,
        (payload.email, payload.region),
    ).fetchone()
    conn.commit()
    return row


@app.get("/email-deliveries", response_model=list[EmailDeliveryDTO])
def list_email_deliveries(conn=Depends(get_connection)) -> list[dict]:
    return conn.execute(
        """
        SELECT
          id,
          recipient_email,
          subject,
          status,
          provider,
          error,
          created_at::text AS created_at
        FROM email_deliveries
        ORDER BY created_at DESC
        LIMIT 50
        """
    ).fetchall()


@app.get("/ingestion-runs", response_model=list[IngestionRunDTO])
def list_ingestion_runs(conn=Depends(get_connection)) -> list[dict]:
    return conn.execute(
        """
        SELECT
          id,
          status,
          source_counts,
          live_mentions_written,
          signals_generated,
          report_id,
          error,
          started_at::text AS started_at,
          finished_at::text AS finished_at
        FROM ingestion_runs
        ORDER BY started_at DESC
        LIMIT 50
        """
    ).fetchall()


@app.options("/{path:path}")
def options_handler(path: str) -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _signal_row(row: dict) -> dict:
    normalized = {**row}
    evidence = {**(row.get("evidence") or {})}
    place_profile = _place_profile_from_row(row)
    if place_profile:
        evidence["place_profile"] = place_profile
    normalized["evidence"] = evidence
    normalized.pop("place_profile", None)
    return {
        **normalized,
        "slug": row.get("slug") or slugify(row["title"]),
        "momentum_driver": _momentum_driver(row),
        "evidence_assessment": _evidence_assessment(row),
        "confidence": row.get("confidence_level") or _confidence(row),
        "signal_strength": _signal_strength(row)[0],
        "signal_strength_reason": _signal_strength(row)[1],
    }


def _restaurant_brief(conn, place_id: str) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT metadata
        FROM place_documents
        WHERE place_id = %s
          AND content_type = 'restaurant_brief'
        ORDER BY fetched_at DESC
        LIMIT 1
        """,
        (place_id,),
    ).fetchone()
    metadata = row["metadata"] if row else None
    if not isinstance(metadata, dict) or not metadata.get("what_it_is"):
        return None
    return {
        "what_it_is": metadata.get("what_it_is") or "",
        "official_context_note": metadata.get("official_context_note") or "Official context, not signal evidence.",
        "signature_menu_items": metadata.get("signature_menu_items") or [],
        "highlight_items": metadata.get("highlight_items") or [],
        "location_format": metadata.get("location_format") or "",
        "vibe_tags": metadata.get("vibe_tags") or [],
        "occasions": metadata.get("occasions") or [],
        "source_chips": metadata.get("source_chips") or [],
        "trust_note": metadata.get("trust_note") or "Context only; recent movement is handled in the signal sections below.",
    }


def _place_profile_from_row(row: dict) -> Optional[dict]:
    profile = row.get("place_profile")
    if not isinstance(profile, dict):
        return None

    known_for = str(profile.get("known_for") or "").strip()
    food_types = [item for item in profile.get("food_types", []) if item]
    signature_items = [item for item in profile.get("signature_items", []) if item]
    flavor_cues = [item for item in profile.get("flavor_cues", []) if item]
    occasions = [item for item in profile.get("occasions", []) if item]
    caveats = str(profile.get("caveats") or "").strip()
    source_count = int(profile.get("source_count") or 0)
    if not (known_for or food_types or signature_items or flavor_cues or occasions or caveats or source_count):
        return None

    return {
        "known_for": known_for,
        "food_types": food_types,
        "signature_items": signature_items,
        "flavor_cues": flavor_cues,
        "occasions": occasions,
        "caveats": caveats,
        "source_count": source_count,
        "profile": profile.get("profile") or {},
        "updated_at": profile.get("updated_at"),
    }


def _related_signal_row(row: dict) -> dict:
    place = row.get("place") or {}
    return {
        "slug": row.get("slug") or slugify(row["title"]),
        "title": row["title"],
        "place_name": row.get("place_name") or place.get("name"),
        "neighborhood": row.get("neighborhood") or place.get("neighborhood"),
        "signal_type": row["signal_type"],
        "score": row["score"],
    }


def _slugify(value: str) -> str:
    return slugify(value)


def _tags(row: dict) -> list[str]:
    evidence = row.get("evidence") or {}
    keywords = [str(keyword) for keyword in evidence.get("keywords", [])[:4]]
    llm_tags = [str(tag) for tag in evidence.get("llm_tags", [])[:4]]
    tags = [row["place"]["category"], _label_for(row["signal_type"]), *llm_tags, *keywords]
    seen: set[str] = set()
    return [tag for tag in tags if tag and not (tag.lower() in seen or seen.add(tag.lower()))]


def _metrics(row: dict) -> list[dict]:
    evidence = row.get("evidence") or {}
    keywords = evidence.get("keywords", [])
    velocity = evidence.get("velocity_ratio")
    source_count = evidence.get("source_count") or len(evidence.get("sources", []))
    spread = evidence.get("outside_region_count")
    current_mentions = evidence.get("current_mention_count")
    sentiment_delta = evidence.get("sentiment_delta")

    metrics = [
        {
            "label": "Keyword growth",
            "value": f"{len(keywords)} active terms" if keywords else "Emerging",
            "detail": ", ".join(keywords[:3]) if keywords else "New language is clustering around this signal.",
            "trend": "up",
        },
        {
            "label": "Mention velocity",
            "value": f"{float(velocity):.1f}x baseline" if velocity is not None else "Above baseline",
            "detail": "Compared with the recent baseline window.",
            "trend": "up",
        },
        {
            "label": "Source diversity",
            "value": f"{int(source_count)} source(s)" if source_count is not None else "Observed",
            "detail": "Signals are stronger when they appear across independent sources.",
            "trend": "steady",
        },
        {
            "label": "Location spread",
            "value": f"{int(spread)} outside area(s)" if spread is not None else row["city"],
            "detail": "Cross-neighborhood attention is treated as a momentum signal.",
            "trend": "up" if spread else "steady",
        },
    ]

    if current_mentions is not None:
        metrics.append(
            {
                "label": "Repeat mentions",
                "value": str(current_mentions),
                "detail": "Recent matched mentions in the current window.",
                "trend": "up" if int(current_mentions) > 1 else "steady",
            }
        )

    if sentiment_delta is not None:
        metrics.append(
            {
                "label": "Sentiment movement",
                "value": f"{float(sentiment_delta):+.2f}",
                "detail": "Directional change, not a star rating.",
                "trend": "down" if float(sentiment_delta) < 0 else "up",
            }
        )

    return metrics


def _momentum_driver(row: dict) -> str:
    evidence = row.get("evidence") or {}
    keywords = evidence.get("keywords", [])
    velocity = evidence.get("velocity_ratio")
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    spread = int(evidence.get("outside_region_count") or 0)
    place_name = row["place"]["name"]

    if row["signal_type"] == "behavior_shift":
        keyword_text = ", ".join(keywords[:2]) if keywords else "behavior-language"
        return f"Behavior shift around {keyword_text} across {source_count or 1} source(s)."
    if row["signal_type"] == "sentiment_shift":
        keyword_text = ", ".join(keywords[:2]) if keywords else "service language"
        return f"Sentiment movement tied to {keyword_text}."
    if spread:
        keyword_text = ", ".join(keywords[:2]) if keywords else "recent food-language"
        return f"Cross-neighborhood attention is forming around {keyword_text}."
    if source_count >= 3:
        keyword_text = ", ".join(keywords[:2]) if keywords else "recent food-language"
        return f"Evidence is appearing across {source_count} source types, led by {keyword_text}."
    if velocity is not None:
        if float(velocity) >= 5:
            return f"{place_name} is seeing an unusual lift across {mention_count or 'multiple'} recent mention(s)."
        return f"{place_name} is moving ahead of its recent baseline."
    keyword_text = ", ".join(keywords[:3]) if keywords else "new food-language"
    return f"New signal language is clustering around {keyword_text}."


def _evidence_assessment(row: dict) -> str:
    evidence = row.get("evidence") or {}
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    spread = int(evidence.get("outside_region_count") or 0)
    if source_count >= 2 and mention_count >= 3:
        return f"Strong support: {mention_count} recent mentions across {source_count} sources."
    if mention_count >= 2:
        return f"Developing support: {mention_count} recent mentions, with evidence still building."
    if spread:
        return "Early support: cross-area signal is present, but repetition is limited."
    return "Evidence coverage is still building for this signal."


def _what_changed(row: dict) -> list[str]:
    evidence = row.get("evidence") or {}
    if evidence.get("what_changed"):
        return [str(change) for change in evidence["what_changed"]]
    changes = [
        _momentum_driver(row),
        _evidence_assessment(row),
    ]
    keywords = evidence.get("keywords", [])
    if keywords:
        changes.append(f"Active language: {', '.join(keywords[:4])}.")
    if evidence.get("outside_region_count"):
        changes.append(f"Detected {int(evidence['outside_region_count'])} outside-area signal(s).")
    return changes


def _evidence_item(row: dict, signal: dict) -> dict:
    geo_metadata = row.get("geo_metadata") or {}
    metadata = row.get("metadata") or {}
    if geo_metadata.get("region"):
        metadata = {**metadata, "region": geo_metadata["region"]}
    return {
        "platform": _platform_label(row["platform"]),
        "timestamp": row["timestamp"],
        "excerpt": row["excerpt"],
        "relevance": _relevance_label(row["excerpt"], signal),
        "metadata": metadata,
        "source_url": row.get("source_url"),
    }


def _relevance_label(text: str, signal: dict) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ["line", "wait", "crowded"]):
        return "wait-time signal"
    if any(term in lowered for term in ["manhattan", "jersey city", "hoboken", "nyc"]):
        return "cross-neighborhood signal"
    if any(term in lowered for term in ["wifi", "remote", "outlet", "quiet"]):
        return "behavior shift signal"
    keywords = (signal.get("evidence") or {}).get("keywords", [])
    if keywords:
        return "keyword momentum signal"
    return "supporting mention"


def _why_this_matters(row: dict) -> str:
    place_name = row["place"]["name"]
    signal_type = row["signal_type"]
    if signal_type == "behavior_shift":
        return (
            f"{place_name} is showing behavior change, which can indicate a place is becoming useful for a new occasion "
            "rather than simply receiving normal attention."
        )
    if signal_type == "sentiment_shift":
        return (
            f"{place_name} has a directional quality or service signal worth watching because momentum can change quickly "
            "when wait-time or service language repeats."
        )
    if signal_type == "review_velocity_spike":
        return (
            f"{place_name} is gaining attention faster than its recent baseline, suggesting the place may be moving from "
            "local familiarity toward broader food discovery."
        )
    return (
        f"{place_name} has new language clustering around it, which can be an early indicator of emerging demand or a "
        "specific item driving discovery."
    )


def _signal_strength(row: dict) -> tuple[str, str]:
    evidence = row.get("evidence") or {}
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mentions = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    evidence_count = len(row.get("evidence_ids") or evidence.get("evidence_ids") or [])
    score = float(row.get("score") or 0)
    signal_type = str(row.get("signal_type") or "")
    keywords = [str(keyword).lower() for keyword in evidence.get("keywords", [])]
    specific_terms = sum(1 for keyword in keywords if _is_specific_signal_term(keyword))

    if score >= 70 and source_count >= 2 and mentions >= 2 and evidence_count >= 2:
        return (
            "Strong signal",
            f"Multiple source types and {evidence_count} linked evidence item(s) support this as a strong weekly signal.",
        )
    if mentions >= 2 and evidence_count >= 2 and (specific_terms >= 1 or signal_type in {"behavior_shift", "keyword_spike"}):
        return (
            "Watching",
            "Evidence is repeating, but source diversity is still limited; treat this as early movement, not a confirmed cross-platform signal.",
        )
    if mentions >= 2 and evidence_count >= 2:
        return (
            "Watching",
            "There is enough repetition to monitor, but the evidence is mostly from one source or uses broad review language.",
        )
    return (
        "Quiet",
        "The evidence is too thin for a strong signal, so this should stay in monitoring mode.",
    )


def _is_specific_signal_term(term: str) -> bool:
    if len(term) < 4:
        return False
    generic = {
        "good",
        "great",
        "amazing",
        "awesome",
        "nice",
        "service",
        "food",
        "place",
        "restaurant",
        "staff",
        "experience",
        "table",
        "atmosphere",
    }
    if term in generic:
        return False
    behavior_terms = {
        "wait",
        "line",
        "packed",
        "reservation",
        "sold out",
        "viral",
        "opening",
        "late night",
        "wifi",
        "remote",
        "outlet",
    }
    food_terms = {
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
    return term in behavior_terms or term in food_terms or any(food in term for food in food_terms)


def _confidence(row: dict) -> str:
    evidence = row.get("evidence") or {}
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mentions = int(evidence.get("current_mention_count") or 0)
    spread = int(evidence.get("outside_region_count") or 0)
    if source_count >= 2 and mentions >= 3:
        return "High"
    if source_count >= 2 or mentions >= 2 or spread >= 1:
        return "Medium"
    return "Low"


def _confidence_reason(row: dict) -> str:
    evidence = row.get("evidence") or {}
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mentions = int(evidence.get("current_mention_count") or 0)
    spread = int(evidence.get("outside_region_count") or 0)
    confidence = _confidence(row)
    if confidence == "High":
        return f"High confidence because the signal repeats across {source_count} sources with {mentions} recent mentions."
    if confidence == "Medium":
        return f"Medium confidence because the signal has {mentions} recent mentions and {spread} outside-area signal(s), but evidence depth is still developing."
    return "Low confidence because the signal is based on limited repetition or source diversity."


def _baseline_context(row: dict) -> dict:
    baseline = row.get("baseline_context") or {}
    evidence = row.get("evidence") or {}
    current_mentions = int(evidence.get("current_mention_count") or 0)
    trailing_30 = int(baseline.get("trailing_30d_mentions") or 0)
    delta = None
    if trailing_30:
        delta = f"{current_mentions} recent signal mention(s) vs {trailing_30} baseline item(s) in the last 30 days"
    elif current_mentions:
        delta = f"{current_mentions} recent signal mention(s) from a quiet baseline"
    return {
        "status": baseline.get("status") or "Quiet baseline",
        "heat_score": float(baseline.get("heat_score") or 0),
        "summary": baseline.get("summary") or "Baseline coverage is still building for this place.",
        "trailing_30d_mentions": trailing_30,
        "trailing_90d_mentions": int(baseline.get("trailing_90d_mentions") or 0),
        "trailing_365d_mentions": int(baseline.get("trailing_365d_mentions") or 0),
        "source_diversity": int(baseline.get("source_diversity") or 0),
        "recurring_keywords": baseline.get("recurring_keywords") or [],
        "delta_vs_baseline": delta,
    }


def _current_signal_rows(conn) -> list[dict]:
    return conn.execute(
        """
        SELECT
          s.id,
          s.signal_type,
          s.title,
          s.summary,
          s.evidence,
          s.score::float AS score,
          s.time_window,
          json_build_object(
            'id', p.id,
            'name', p.name,
            'category', p.category,
            'city', p.city,
            'neighborhood', p.neighborhood
          ) AS place
        FROM signals s
        JOIN places p ON p.id = s.place_id
        WHERE s.status IN ('published', 'draft')
        ORDER BY s.week_start DESC, s.score DESC
        LIMIT 100
        """
    ).fetchall()


def _retrieve_candidate_evidence(conn, candidate: dict, limit: int = 10) -> list[dict]:
    metrics = candidate.get("detected_metrics") or {}
    days = _candidate_time_window_days(candidate)
    keywords = _candidate_keywords(candidate)
    candidate_id = candidate["id"]
    place_id = candidate["place_id"]

    chunks = conn.execute(
        """
        SELECT
          ec.id::text AS id,
          ec.chunk_text,
          ec.extracted_keywords,
          ec.occurred_at,
          ec.embedding IS NOT NULL AS has_embedding,
          rsi.platform,
          rsi.url AS source_url,
          rsi.engagement_metrics,
          rsi.geo_metadata
        FROM evidence_chunks ec
        JOIN raw_source_items rsi ON rsi.id = ec.raw_source_item_id
        WHERE ec.place_id = %s
          AND ec.occurred_at >= now() - (%s || ' days')::interval
        ORDER BY ec.occurred_at DESC
        LIMIT 80
        """,
        (place_id, days),
    ).fetchall()
    _ensure_chunk_embeddings(conn, chunks)

    query_text = " ".join(
        [
            str(candidate["place"].get("name") or ""),
            str(candidate["signal_type"]),
            str(candidate.get("trigger_reason") or ""),
            " ".join(keywords),
        ]
    ).strip()
    query_embedding = embed_texts([query_text])[0]
    semantic_rows = conn.execute(
        """
        SELECT
          ec.id::text AS id,
          ec.chunk_text,
          ec.extracted_keywords,
          ec.occurred_at,
          rsi.platform,
          rsi.url AS source_url,
          rsi.engagement_metrics,
          rsi.geo_metadata,
          1 - (ec.embedding <=> %s::vector) AS semantic_score
        FROM evidence_chunks ec
        JOIN raw_source_items rsi ON rsi.id = ec.raw_source_item_id
        WHERE ec.place_id = %s
          AND ec.embedding IS NOT NULL
          AND ec.occurred_at >= now() - (%s || ' days')::interval
        ORDER BY ec.embedding <=> %s::vector
        LIMIT 40
        """,
        (vector_literal(query_embedding), place_id, days, vector_literal(query_embedding)),
    ).fetchall()

    ranked = _rank_evidence_rows(semantic_rows, keywords, limit)
    if len(ranked) < 2:
        raise OpenAIPipelineError("Candidate has fewer than 2 retrievable evidence chunks.")
    conn.execute("DELETE FROM signal_candidate_evidence WHERE signal_candidate_id = %s", (candidate_id,))
    for rank, row in enumerate(ranked, start=1):
        conn.execute(
            """
            INSERT INTO signal_candidate_evidence (signal_candidate_id, evidence_chunk_id, relevance_score, rank)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (signal_candidate_id, evidence_chunk_id)
            DO UPDATE SET relevance_score = EXCLUDED.relevance_score, rank = EXCLUDED.rank
            """,
            (candidate_id, row["id"], row["relevance_score"], rank),
        )
    conn.commit()
    return [_prompt_evidence_chunk(row) for row in ranked]


def _candidate_time_window_days(candidate: dict) -> int:
    metrics = candidate.get("detected_metrics") or {}
    if metrics.get("current_window_days"):
        return int(metrics["current_window_days"])
    match = re.search(r"(\d+)", str(candidate.get("time_window") or ""))
    return int(match.group(1)) if match else 30


def _candidate_keywords(candidate: dict) -> list[str]:
    metrics = candidate.get("detected_metrics") or {}
    keywords = metrics.get("keywords") or []
    return [str(keyword).lower() for keyword in keywords if keyword][:10]


def _candidate_gate_reason(candidate: dict) -> Optional[str]:
    metrics = candidate.get("detected_metrics") or {}
    candidate_score = float(candidate.get("candidate_score") or 0)
    source_diversity = int(metrics.get("source_count") or len(metrics.get("sources", [])) or 0)

    if candidate_score < settings.signal_generate_min_candidate_score:
        return (
            f"Candidate score {candidate_score:.1f} is below "
            f"{settings.signal_generate_min_candidate_score:.1f}."
        )
    if source_diversity < settings.signal_generate_min_source_diversity:
        return (
            f"Source diversity {source_diversity} is below "
            f"{settings.signal_generate_min_source_diversity}."
        )
    return None


def _ensure_chunk_embeddings(conn, chunks: list[dict]) -> None:
    missing = [chunk for chunk in chunks if not chunk.get("has_embedding")]
    if not missing:
        return
    embeddings = embed_texts([chunk["chunk_text"] for chunk in missing])
    for chunk, embedding in zip(missing, embeddings):
        conn.execute(
            "UPDATE evidence_chunks SET embedding = %s::vector WHERE id = %s",
            (vector_literal(embedding), chunk["id"]),
        )
    conn.commit()


def _rank_evidence_rows(rows: list[dict], keywords: list[str], limit: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    ranked = []
    for row in rows:
        text = (row.get("chunk_text") or "").lower()
        extracted = {str(keyword).lower() for keyword in row.get("extracted_keywords") or []}
        keyword_hits = sum(1 for keyword in keywords if keyword in text or keyword in extracted)
        specificity_hits = sum(1 for term in _specific_signal_terms() if term in text or term in extracted)
        generic_hits = sum(1 for term in _generic_review_terms() if term in text or term in extracted)
        occurred_at = row["occurred_at"]
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        age_days = max((now - occurred_at).days, 0)
        recency_boost = max(0, 1 - (age_days / 30)) * 0.1
        quality_boost = min(specificity_hits * 0.12, 0.36) + min(keyword_hits * 0.06, 0.24)
        generic_penalty = 0.08 if generic_hits and not specificity_hits else 0
        length_boost = 0.04 if len(text) >= 80 else 0
        score = float(row.get("semantic_score") or 0) + quality_boost + recency_boost + length_boost - generic_penalty
        ranked.append({**row, "relevance_score": round(max(score, 0), 4)})

    selected = []
    platform_counts: dict[str, int] = {}
    for row in sorted(ranked, key=lambda item: item["relevance_score"], reverse=True):
        platform = row.get("platform") or "unknown"
        if platform_counts.get(platform, 0) >= 3 and len(selected) < limit - 2:
            continue
        selected.append(row)
        platform_counts[platform] = platform_counts.get(platform, 0) + 1
        if len(selected) >= limit:
            break
    return selected


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


def _prompt_evidence_chunk(row: dict) -> dict:
    return {
        "id": row["id"],
        "platform": row["platform"],
        "source_url": row.get("source_url"),
        "timestamp": row["occurred_at"].isoformat(),
        "chunk_text": row["chunk_text"],
        "extracted_keywords": row.get("extracted_keywords") or [],
        "engagement_metrics": row.get("engagement_metrics") or {},
        "geo_metadata": row.get("geo_metadata") or {},
        "relevance_score": row["relevance_score"],
    }


def _write_generated_signal(conn, candidate: dict, llm_result: dict, evidence_chunks: list[dict]) -> UUID:
    metrics = candidate.get("detected_metrics") or {}
    confidence_level, confidence_score, confidence_reason = confidence_from_metrics(metrics)
    confidence_reason = llm_result.get("confidence_reason") or confidence_reason
    evidence_ids = _supported_evidence_ids(llm_result.get("evidence_ids") or [], evidence_chunks)
    if not evidence_ids:
        evidence_ids = [chunk["id"] for chunk in evidence_chunks[:5]]
    evidence_uuid_ids = [UUID(evidence_id) for evidence_id in evidence_ids]
    place = candidate["place"]
    title = llm_result.get("phenomenon_title") or llm_result["title"]
    evidence = {
        **metrics,
        "component_scores": candidate.get("component_scores") or {},
        "candidate_id": candidate["id"],
        "evidence_ids": evidence_ids,
        "llm_tags": llm_result.get("tags") or [],
        "what_changed": llm_result.get("what_changed") or [],
        "sources": sorted({chunk["platform"] for chunk in evidence_chunks}),
        "phenomenon_title": title,
        "food_or_cuisine_type": llm_result.get("food_or_cuisine_type"),
        "place_anchor_reason": llm_result.get("place_anchor_reason"),
        "reader_hook": llm_result.get("reader_hook"),
        "what_to_notice": llm_result.get("what_to_notice"),
        "skeptic_note": llm_result.get("skeptic_note"),
        "good_for": llm_result.get("good_for"),
        "watch_out": llm_result.get("watch_out"),
        "best_read_as": llm_result.get("best_read_as"),
        "evidence_receipt": llm_result.get("evidence_receipt") or {},
        "place_profile": llm_result.get("place_profile") or {},
        "food_signal": llm_result.get("food_signal") or {},
    }
    row = conn.execute(
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
          evidence_ids,
          status,
          time_window,
          evidence,
          score,
          city,
          week_start
        )
        VALUES (
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s::jsonb,
          %s,
          'draft',
          %s,
          %s::jsonb,
          %s,
          %s,
          date_trunc('week', now())::date
        )
        RETURNING id
        """,
        (
            slugify(f"{place.get('name', '')}-{title}"),
            candidate["place_id"],
            candidate["signal_type"],
            title,
            llm_result["short_summary"],
            llm_result["short_summary"],
            llm_result["ai_summary"],
            llm_result["why_this_matters"],
            confidence_level,
            confidence_score,
            confidence_reason,
            Jsonb(_metrics({"evidence": metrics, "city": place.get("city"), "place": place})),
            evidence_uuid_ids,
            candidate["time_window"],
            Jsonb(evidence),
            candidate["candidate_score"],
            place.get("city") or "",
        ),
    ).fetchone()
    signal_id = row["id"]
    for rank, evidence_id in enumerate(evidence_ids, start=1):
        relevance = next((chunk["relevance_score"] for chunk in evidence_chunks if chunk["id"] == evidence_id), 0)
        conn.execute(
            """
            INSERT INTO signal_evidence (signal_id, evidence_chunk_id, relevance_score, rank)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (signal_id, evidence_chunk_id)
            DO UPDATE SET relevance_score = EXCLUDED.relevance_score, rank = EXCLUDED.rank
            """,
            (signal_id, evidence_id, relevance, rank),
        )
    conn.execute("UPDATE signal_candidates SET status = 'generated' WHERE id = %s", (candidate["id"],))
    conn.commit()
    return signal_id


def _supported_evidence_ids(ids: list[str], evidence_chunks: list[dict]) -> list[str]:
    available = {chunk["id"] for chunk in evidence_chunks}
    seen: set[str] = set()
    return [evidence_id for evidence_id in ids if evidence_id in available and not (evidence_id in seen or seen.add(evidence_id))]


def _record_pipeline_run(conn, step: str, status_value: str, metrics: dict, error: Optional[str] = None) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_runs (step, status, metrics, error, finished_at)
        VALUES (%s, %s, %s::jsonb, %s, now())
        """,
        (step, status_value, Jsonb(metrics), error),
    )
    conn.commit()


def _require_admin(token: Optional[str]) -> None:
    expected = settings.admin_token
    if expected and token != expected:
        raise HTTPException(status_code=403, detail="Admin token is required.")


def _passes_publish_checks(row: dict) -> bool:
    evidence = row.get("evidence") or {}
    metrics = row.get("metrics") or []
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    return bool(row.get("confidence_reason")) and bool(metrics) and source_count >= 1 and mention_count >= 2


def _platform_label(source: str) -> str:
    labels = {
        "google_reviews": "Google Reviews",
        "google_places": "Google Reviews",
        "reddit": "Reddit",
        "rss": "Local web",
        "google_news": "Google News",
        "yelp": "Local listing",
    }
    return labels.get(source, source.replace("_", " ").title())


def _label_for(signal_type: str) -> str:
    labels = {
        "keyword_spike": "Keyword spike",
        "behavior_shift": "Behavior shift",
        "sentiment_shift": "Sentiment shift",
        "new_place_detected": "New place",
        "review_velocity_spike": "Rising fast",
    }
    return labels.get(signal_type, "Food signal")
