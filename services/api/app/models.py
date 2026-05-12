from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel


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
