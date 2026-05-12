from typing import Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import get_connection
from app.models import (
    FeedbackCreate,
    FeedbackDTO,
    ReportDTO,
    SignalDTO,
    SubscriberCreate,
    SubscriberDTO,
)

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
def list_signals(city: Optional[str] = None, conn=Depends(get_connection)) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
          s.id,
          s.signal_type,
          s.title,
          s.summary,
          s.evidence,
          s.score::float AS score,
          s.city,
          s.week_start::text AS week_start,
          json_build_object(
            'id', p.id,
            'name', p.name,
            'category', p.category,
            'city', p.city,
            'neighborhood', p.neighborhood
          ) AS place
        FROM signals s
        JOIN places p ON p.id = s.place_id
        WHERE (%s IS NULL OR s.city = %s)
        ORDER BY s.week_start DESC, s.score DESC
        LIMIT 50
        """,
        (city, city),
    ).fetchall()
    return rows


@app.get("/reports/latest", response_model=ReportDTO)
def latest_report(conn=Depends(get_connection)) -> dict:
    report = conn.execute(
        """
        SELECT id, title, region, week_start::text AS week_start, intro
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
          s.signal_type,
          s.title,
          s.summary,
          s.evidence,
          s.score::float AS score,
          s.city,
          s.week_start::text AS week_start,
          json_build_object(
            'id', p.id,
            'name', p.name,
            'category', p.category,
            'city', p.city,
            'neighborhood', p.neighborhood
          ) AS place
        FROM report_signals rs
        JOIN signals s ON s.id = rs.signal_id
        JOIN places p ON p.id = s.place_id
        WHERE rs.report_id = %s
        ORDER BY rs.rank ASC
        """,
        (report["id"],),
    ).fetchall()

    return {**report, "signals": signals}


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


@app.options("/{path:path}")
def options_handler(path: str) -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)
