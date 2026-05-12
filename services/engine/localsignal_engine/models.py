from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    category: str
    city: str
    neighborhood: Optional[str] = None


@dataclass(frozen=True)
class Mention:
    place_id: str
    source: str
    body: str
    occurred_at: datetime
    author_region: Optional[str] = None
    rating: Optional[float] = None
    sentiment: Optional[float] = None


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
