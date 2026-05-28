from fastapi import APIRouter, Depends, HTTPException, status

from app.db import get_connection
from app.models import FeedbackCreate, FeedbackDTO, SubscriberCreate, SubscriberDTO

router = APIRouter()


@router.post("/feedback", response_model=FeedbackDTO, status_code=status.HTTP_201_CREATED)
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


@router.post("/subscribers", response_model=SubscriberDTO, status_code=status.HTTP_201_CREATED)
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
