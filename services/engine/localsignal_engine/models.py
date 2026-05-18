from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from typing import Optional


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    category: str
    city: str
    neighborhood: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    google_place_id: Optional[str] = None
    map_url: Optional[str] = None


@dataclass(frozen=True)
class Mention:
    place_id: str
    source: str
    body: str
    occurred_at: datetime
    source_url: Optional[str] = None
    author_region: Optional[str] = None
    rating: Optional[float] = None
    sentiment: Optional[float] = None
    engagement_metrics: dict[str, Any] = field(default_factory=dict)
    geo_metadata: dict[str, Any] = field(default_factory=dict)
    raw_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class Signal:
    place: Place
    signal_type: str
    title: str
    summary: str
    evidence: dict
    score: float
    week_start: str
    keywords: list[str] = field(default_factory=list)
