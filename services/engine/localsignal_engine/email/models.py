from dataclasses import dataclass
from typing import Any
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class Subscriber:
    id: UUID
    email: str


@dataclass(frozen=True)
class ReportSignal:
    title: str
    summary: str
    city: str
    score: float
    place_name: str
    place_category: str
    place_neighborhood: Optional[str]
    signal_type: str
    evidence: dict
    confidence_level: Optional[str]
    momentum_driver: Optional[str]
    slug: Optional[str] = None
    food_signal: Optional[dict] = None
    place_profile: Optional[dict] = None


@dataclass(frozen=True)
class Report:
    id: UUID
    title: str
    region: str
    week_start: str
    intro: str
    briefing: dict[str, Any]
    signals: list[ReportSignal]


@dataclass(frozen=True)
class SendResult:
    status: str
    provider: str
    provider_message_id: Optional[str] = None
    error: Optional[str] = None
