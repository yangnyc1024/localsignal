from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from psycopg.types.json import Jsonb

from app.config import settings
from app.db import get_connection
from app.models import (
    AlwaysHotDTO,
    EmailDeliveryDTO,
    IngestionRunDTO,
    PipelineActionDTO,
    SocialSourceRunDTO,
)
from app.openai_pipeline import OpenAIPipelineError, openai_enabled
from app.pipeline import build_llm_prompt, extract_keywords, score_candidate
from app.openai_pipeline import generate_signal_json
from app.presenters.signals import (
    _candidate_gate_reason,
    _current_signal_rows,
    _metrics,
    _passes_publish_checks,
    _record_pipeline_run,
    _require_admin,
    _retrieve_candidate_evidence,
    _write_generated_signal,
)

router = APIRouter()


@router.get("/api/baseline/always-hot", response_model=list[AlwaysHotDTO])
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


@router.get("/api/source-health/social", response_model=list[SocialSourceRunDTO])
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


@router.post("/api/ingest/run", response_model=PipelineActionDTO)
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


@router.post("/api/signals/detect", response_model=PipelineActionDTO)
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


@router.post("/api/signals/generate", response_model=PipelineActionDTO)
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


@router.post("/api/signals/publish", response_model=PipelineActionDTO)
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


@router.get("/email-deliveries", response_model=list[EmailDeliveryDTO])
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


@router.get("/ingestion-runs", response_model=list[IngestionRunDTO])
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
