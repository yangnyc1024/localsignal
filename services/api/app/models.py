from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class PlaceDTO(BaseModel):
    id: UUID
    name: str
    category: str
    city: str
    neighborhood: Optional[str] = None


class SignalDTO(BaseModel):
    id: UUID
    signal_type: str
    title: str
    summary: str
    evidence: dict[str, Any]
    score: float
    city: str
    week_start: str
    place: PlaceDTO


class ReportDTO(BaseModel):
    id: UUID
    title: str
    region: str
    week_start: str
    intro: str
    signals: list[SignalDTO]


class FeedbackCreate(BaseModel):
    signal_id: UUID
    event_type: Literal["click", "save", "share", "dismiss"]
    session_id: Optional[str] = None


class FeedbackDTO(BaseModel):
    id: UUID
    signal_id: UUID
    event_type: str
    session_id: Optional[str] = None


class SubscriberCreate(BaseModel):
    email: str
    region: str = "Fort Lee / Edgewater / Palisades Park"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address.")
        return normalized


class SubscriberDTO(BaseModel):
    id: UUID
    email: str
    region: str
    status: str


class EmailDeliveryDTO(BaseModel):
    id: UUID
    recipient_email: str
    subject: str
    status: str
    provider: str
    error: Optional[str] = None
    created_at: str
