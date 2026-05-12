from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from localsignal_engine.models import Mention, Place, Signal

KEYWORDS = [
    "salt bread",
    "line",
    "manhattan",
    "wifi",
    "outlet",
    "quiet",
    "remote",
    "wait",
    "service",
    "crowded",
]


def week_start(today: Optional[datetime] = None) -> str:
    value = today or datetime.now(timezone.utc)
    start = value - timedelta(days=value.weekday())
    return start.date().isoformat()


def extract_signals(places: list[Place], mentions: list[Mention]) -> list[Signal]:
    by_place: dict[str, list[Mention]] = defaultdict(list)
    for mention in mentions:
        by_place[mention.place_id].append(mention)

    place_lookup = {place.id: place for place in places}
    signals: list[Signal] = []

    for place_id, place_mentions in by_place.items():
        place = place_lookup[place_id]
        text = " ".join(mention.body.lower() for mention in place_mentions)
        keyword_counts = Counter(keyword for keyword in KEYWORDS if keyword in text)
        source_count = len({mention.source for mention in place_mentions})
        outside_regions = {
            mention.author_region
            for mention in place_mentions
            if mention.author_region and mention.author_region != place.city
        }
        avg_sentiment = sum((mention.sentiment or 0) for mention in place_mentions) / len(place_mentions)

        if keyword_counts:
            top_keywords = [keyword for keyword, _count in keyword_counts.most_common(4)]
            signal_type = classify_signal(top_keywords, avg_sentiment)
            score = score_signal(len(place_mentions), len(top_keywords), source_count, len(outside_regions), avg_sentiment)
            title, summary = explain_signal(place, signal_type, top_keywords, outside_regions, avg_sentiment)

            signals.append(
                Signal(
                    place=place,
                    signal_type=signal_type,
                    title=title,
                    summary=summary,
                    evidence={
                        "mention_count": len(place_mentions),
                        "source_count": source_count,
                        "outside_region_count": len(outside_regions),
                        "average_sentiment": round(avg_sentiment, 3),
                        "keywords": top_keywords,
                        "sources": sorted({mention.source for mention in place_mentions}),
                    },
                    score=round(score, 2),
                    week_start=week_start(),
                    keywords=top_keywords,
                )
            )

    return sorted(signals, key=lambda signal: signal.score, reverse=True)


def classify_signal(keywords: list[str], avg_sentiment: float) -> str:
    if avg_sentiment < -0.1 or {"wait", "service", "crowded"}.intersection(keywords):
        return "sentiment_shift"
    if {"wifi", "outlet", "quiet", "remote"}.intersection(keywords):
        return "behavior_shift"
    return "keyword_spike"


def score_signal(
    mention_count: int,
    keyword_count: int,
    source_count: int,
    outside_region_count: int,
    avg_sentiment: float,
) -> float:
    novelty = min(keyword_count * 8, 28)
    velocity = min(mention_count * 12, 36)
    diversity = min(source_count * 10, 20)
    regional_pull = min(outside_region_count * 6, 12)
    sentiment_bonus = max(avg_sentiment, 0) * 8
    concern_bonus = abs(min(avg_sentiment, 0)) * 10
    return velocity + novelty + diversity + regional_pull + sentiment_bonus + concern_bonus


def explain_signal(
    place: Place,
    signal_type: str,
    keywords: list[str],
    outside_regions: set[Optional[str]],
    avg_sentiment: float,
) -> tuple[str, str]:
    if signal_type == "behavior_shift":
        return (
            f"{place.name} is becoming a remote-work hotspot",
            f"Recent mentions increasingly point to {', '.join(keywords[:3])}, suggesting a weekday use case beyond casual cafe visits.",
        )

    if signal_type == "sentiment_shift":
        return (
            f"{place.name} shows early signs of quality drift",
            f"The place still has activity, but recent language around {', '.join(keywords[:3])} suggests a change locals may want to watch.",
        )

    regional_note = ""
    if outside_regions:
        regional_note = " with attention coming from outside the immediate neighborhood"
    return (
        f"{place.name} is suddenly rising",
        f"Mentions around {', '.join(keywords[:3])} are clustering this week{regional_note}.",
    )
