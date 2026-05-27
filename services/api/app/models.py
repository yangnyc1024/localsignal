from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PlaceDTO(BaseModel):
    id: UUID
    name: str
    category: str
    address: Optional[str] = None
    city: str
    neighborhood: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    google_place_id: Optional[str] = None
    map_url: Optional[str] = None


class SignalDTO(BaseModel):
    id: UUID
    slug: str
    signal_type: str
    title: str
    summary: str
    momentum_driver: str
    evidence_assessment: str
    confidence: Literal["High", "Medium", "Low"]
    signal_strength: Literal["Strong signal", "Watching", "Quiet"]
    signal_strength_reason: str
    evidence: dict[str, Any]
    score: float
    city: str
    week_start: str
    place: PlaceDTO


class SignalMetricDTO(BaseModel):
    label: str
    value: str
    detail: Optional[str] = None
    trend: Literal["up", "down", "steady"] = "steady"


class SignalEvidenceDTO(BaseModel):
    platform: str
    timestamp: str
    excerpt: str
    relevance: str
    metadata: dict[str, Any] = {}
    source_url: Optional[str] = None


class RelatedSignalDTO(BaseModel):
    slug: str
    title: str
    place_name: str
    neighborhood: Optional[str] = None
    signal_type: str
    score: float


class BaselineContextDTO(BaseModel):
    status: str
    heat_score: float
    summary: str
    trailing_30d_mentions: int
    trailing_90d_mentions: int
    trailing_365d_mentions: int
    source_diversity: int
    recurring_keywords: list[str]
    delta_vs_baseline: Optional[str] = None


class RestaurantBriefDTO(BaseModel):
    what_it_is: str
    official_context_note: str
    signature_menu_items: list[str] = Field(default_factory=list)
    location_format: str
    source_chips: list[str] = Field(default_factory=list)
    trust_note: str


class FoodFactDTO(BaseModel):
    fact_type: Literal["dish", "occasion", "behavior"]
    fact_value: str
    evidence_text: str
    source: str
    source_url: Optional[str] = None
    confidence: float
    occurred_at: Optional[str] = None


class SignalDetailDTO(SignalDTO):
    rank: int
    region: str
    date_range: str
    tags: list[str]
    ai_summary: str
    what_changed: list[str]
    why_this_matters: str
    confidence_reason: str
    baseline_context: BaselineContextDTO
    metrics: list[SignalMetricDTO]
    restaurant_brief: Optional[RestaurantBriefDTO] = None
    food_facts: list[FoodFactDTO] = Field(default_factory=list)
    evidence_items: list[SignalEvidenceDTO]
    related_signals: list[RelatedSignalDTO]


class ReportDTO(BaseModel):
    id: UUID
    title: str
    region: str
    week_start: str
    intro: str
    briefing: dict[str, Any] = Field(default_factory=dict)
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


class IngestionRunDTO(BaseModel):
    id: UUID
    status: str
    source_counts: dict[str, int]
    live_mentions_written: int
    signals_generated: int
    report_id: Optional[UUID] = None
    error: Optional[str] = None
    started_at: str
    finished_at: Optional[str] = None


class SocialSourceRunDTO(BaseModel):
    id: UUID
    provider: str
    platform: str
    dataset_id: Optional[str] = None
    query: Optional[str] = None
    status: str
    total_records: int
    normalized_records: int
    fresh_records: int
    old_records_dropped: int
    parsed_items: int
    resolved_items: int
    review_items: int
    unresolved_items: int
    source_counts: dict[str, int]
    error: Optional[str] = None
    started_at: str
    finished_at: str


class PipelineActionDTO(BaseModel):
    step: str
    status: str
    metrics: dict[str, Any]
    message: str


class AlwaysHotDTO(BaseModel):
    place_id: UUID
    place_name: str
    category: str
    neighborhood: Optional[str] = None
    city: str
    status: str
    heat_score: float
    summary: str
    recurring_keywords: list[str]
    source_diversity: int
