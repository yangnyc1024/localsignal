"""Signal generation: tokenisation, scoring, classification, and explanation."""
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from localsignal_engine.models import Mention, Place, Signal
from localsignal_engine.place.names import display_place_name


# ── constants ────────────────────────────────────────────────────────────────

STOPWORDS = {
    "about", "after", "again", "also", "always", "all", "and", "are",
    "author", "any", "because", "been", "but", "can", "day", "for", "from",
    "get", "had", "has", "have", "into", "its", "just", "more", "near",
    "new", "not", "now", "one", "ordered", "our", "out", "over", "place",
    "relative", "she", "still", "time", "the", "their", "there", "that",
    "they", "this", "very", "week", "were", "was", "when", "whatever",
    "which", "will", "with", "would", "you", "your",
}

# Generic praise/service vocabulary that appears in almost every Google review.
# It carries no change information, so it must not become a signal keyword or
# inflate keyword-based scoring; food- and behavior-specific terms should win.
GENERIC_PRAISE_TERMS = {
    "amazing", "atmosphere", "attentive", "awesome", "definitely", "delicious",
    "excellent", "experience", "food", "friendly", "good", "great", "kind",
    "love", "loved", "nice", "really", "recommend", "server", "servers",
    "service", "staff", "waiter", "waitress", "wonderful",
}

POSITIVE_TERMS = {
    "amazing", "best", "busy", "excellent", "favorite", "fresh", "great",
    "hidden", "popular", "quiet", "recommend", "trending", "worth",
}

NEGATIVE_TERMS = {
    "bad", "crowded", "decline", "expensive", "long", "overrated", "slow",
    "wait", "worse",
}


# ── public API ────────────────────────────────────────────────────────────────

def week_start(today: Optional[datetime] = None) -> str:
    value = today or datetime.now(timezone.utc)
    start = value - timedelta(days=value.weekday())
    return start.date().isoformat()


def generate_report_signals(
    places: list[Place],
    mentions: list[Mention],
    current_window_days: int = 7,
    baseline_window_days: int = 28,
) -> list[Signal]:
    now = datetime.now(timezone.utc)
    current_cutoff = now - timedelta(days=current_window_days)
    baseline_cutoff = current_cutoff - timedelta(days=baseline_window_days)
    place_lookup = {place.id: place for place in places}
    by_place: dict[str, list[Mention]] = defaultdict(list)

    for mention in mentions:
        if mention.place_id in place_lookup and mention.occurred_at >= baseline_cutoff:
            by_place[mention.place_id].append(mention)

    signals: list[Signal] = []
    for place_id, place_mentions in by_place.items():
        current_mentions = [m for m in place_mentions if m.occurred_at >= current_cutoff]
        baseline_mentions = [m for m in place_mentions if baseline_cutoff <= m.occurred_at < current_cutoff]
        if not current_mentions:
            continue

        place = place_lookup[place_id]
        current_tokens = _tokens(current_mentions)
        baseline_tokens = _tokens(baseline_mentions)
        keywords = _top_keywords(current_tokens, baseline_tokens)
        source_count = len({m.source for m in current_mentions})
        current_sentiment = _average_sentiment(current_mentions)
        baseline_sentiment = _average_sentiment(baseline_mentions)
        sentiment_delta = current_sentiment - baseline_sentiment
        velocity_ratio = _velocity_ratio(len(current_mentions), len(baseline_mentions), current_window_days, baseline_window_days)
        outside_regions = {
            m.author_region
            for m in current_mentions
            if m.author_region and m.author_region.lower() != place.city.lower()
        }
        signal_type = _classify(velocity_ratio, sentiment_delta, keywords)
        score = _score(
            current_count=len(current_mentions),
            source_count=source_count,
            keyword_count=len(keywords),
            velocity_ratio=velocity_ratio,
            sentiment_delta=sentiment_delta,
            outside_region_count=len(outside_regions),
        )
        title, summary = _explain(place, signal_type, keywords, velocity_ratio, sentiment_delta, source_count)

        signals.append(
            Signal(
                place=place,
                signal_type=signal_type,
                title=title,
                summary=summary,
                evidence={
                    "ml_engine": "velocity_keyword_sentiment_v1",
                    "current_window_days": current_window_days,
                    "baseline_window_days": baseline_window_days,
                    "current_mention_count": len(current_mentions),
                    "baseline_mention_count": len(baseline_mentions),
                    "velocity_ratio": round(velocity_ratio, 2),
                    "source_count": source_count,
                    "outside_region_count": len(outside_regions),
                    "average_sentiment": round(current_sentiment, 3),
                    "sentiment_delta": round(sentiment_delta, 3),
                    "keywords": keywords,
                    "sources": sorted({m.source for m in current_mentions}),
                },
                score=round(score, 2),
                week_start=week_start(now),
                keywords=keywords,
            )
        )

    return sorted(signals, key=lambda s: s.score, reverse=True)[:12]


# ── private helpers ───────────────────────────────────────────────────────────

def _tokens(mentions: list[Mention]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for mention in mentions:
        words = re.findall(r"[a-z][a-z0-9'-]{2,}", mention.body.lower())
        counter.update(w for w in words if w not in STOPWORDS)
    return counter


def _top_keywords(current: Counter[str], baseline: Counter[str]) -> list[str]:
    scores: list[tuple[str, float]] = []
    for token, count in current.items():
        if token in GENERIC_PRAISE_TERMS:
            continue
        novelty = count / math.sqrt(1 + baseline.get(token, 0))
        if novelty >= 1:
            scores.append((token, novelty))
    return [t for t, _ in sorted(scores, key=lambda x: x[1], reverse=True)[:5]]


def _average_sentiment(mentions: list[Mention]) -> float:
    if not mentions:
        return 0.0
    return sum(_mention_sentiment(m) for m in mentions) / len(mentions)


def _mention_sentiment(mention: Mention) -> float:
    if mention.sentiment is not None:
        return mention.sentiment
    words = set(re.findall(r"[a-z][a-z0-9'-]{2,}", mention.body.lower()))
    positive = len(words & POSITIVE_TERMS)
    negative = len(words & NEGATIVE_TERMS)
    rating_sentiment = (mention.rating - 3) / 2 if mention.rating is not None else 0.0
    lexical_sentiment = (positive - negative) / max(3, positive + negative + 1)
    return max(-1.0, min(1.0, rating_sentiment * 0.7 + lexical_sentiment * 0.3))


def _velocity_ratio(current_count: int, baseline_count: int, current_days: int, baseline_days: int) -> float:
    current_rate = current_count / max(current_days, 1)
    baseline_rate = baseline_count / max(baseline_days, 1)
    return current_rate / max(baseline_rate, 0.05)


def _sentiment_shift_enabled() -> bool:
    # Disabled until evidence_chunks.sentiment is actually populated; until then
    # a published "sentiment shift" cannot be traced back to stored data.
    return os.getenv("SIGNAL_SENTIMENT_SHIFT_ENABLED", "false").lower() == "true"


def _classify(velocity_ratio: float, sentiment_delta: float, keywords: list[str]) -> str:
    if _sentiment_shift_enabled() and (
        sentiment_delta <= -0.15 or {"wait", "slow", "crowded", "overrated"}.intersection(keywords)
    ):
        return "sentiment_shift"
    if {"wifi", "quiet", "remote", "work", "outlet"}.intersection(keywords):
        return "behavior_shift"
    if velocity_ratio >= 1.6:
        return "review_velocity_spike"
    return "keyword_spike"


def _score(
    current_count: int,
    source_count: int,
    keyword_count: int,
    velocity_ratio: float,
    sentiment_delta: float,
    outside_region_count: int,
) -> float:
    return min(
        (
            min(current_count * 7, 28)
            + min(source_count * 10, 30)
            + min(keyword_count * 4, 16)
            + min(math.log1p(velocity_ratio) * 8, 22)
            + min(abs(sentiment_delta) * 28, 10)
            + min(outside_region_count * 4, 8)
        ),
        100,
    )


def _explain(
    place: Place,
    signal_type: str,
    keywords: list[str],
    velocity_ratio: float,
    sentiment_delta: float,
    source_count: int,
) -> tuple[str, str]:
    keyword_text = ", ".join(keywords[:3]) if keywords else "recent mentions"
    place_name = display_place_name(place.display_name or place.name)
    topic = _title_topic(keywords, place.category)
    if signal_type == "sentiment_shift":
        return (
            f"{place_name} has a changing wait-time read" if topic == "Wait-time"
            else f"{place_name} has a changing {topic.lower()} read",
            f"Recent language around {keyword_text} is moving differently from the short-term baseline.",
        )
    if signal_type == "behavior_shift":
        return (
            f"{place_name} has a changing {topic.lower()} visit read",
            f"Recent mentions across {source_count} source(s) increasingly point to {keyword_text}.",
        )
    if signal_type == "review_velocity_spike":
        if source_count >= 3:
            return (
                f"{topic} is spreading across multiple source types at {place_name}",
                f"Recent activity is appearing across {source_count} source types, with repeated language around {keyword_text}.",
            )
        if velocity_ratio >= 5:
            return (
                f"{place_name} is getting more recent attention for {topic.lower()}",
                f"Recent mentions are materially above the short-term baseline, led by language around {keyword_text}.",
            )
        return (
            f"{place_name} is getting more recent attention for {topic.lower()}",
            f"Recent activity is moving ahead of baseline, with new keywords around {keyword_text}.",
        )
    return (
        f"{place_name} is showing repeated language around {topic.lower()}",
        f"The strongest new language this week centers on {keyword_text}, across {source_count} source(s).",
    )


def _title_topic(keywords: list[str], category: str) -> str:
    allowed_terms = {
        "line", "wait", "wait time", "sold out", "worth the drive", "viral", "new menu",
        "opening", "soft opening", "reservation", "packed", "quiet work spot", "late night",
        "pizza", "sourdough", "bread", "pastry", "croissant", "bun", "cake", "dessert",
        "matcha", "cream", "coffee", "latte", "seafood", "crab", "chicken wings", "wings",
        "bbq", "korean bbq", "ramen", "sushi", "gyro", "kebab", "falafel", "empanadas",
    }
    normalized = [k.strip().lower() for k in keywords if k and k.strip()]
    useful = [k for k in normalized if k in allowed_terms]
    if "chicken" in normalized and "wings" in normalized and "chicken wings" not in useful:
        useful.insert(0, "chicken wings")
    if useful:
        label_map = {
            "wait": "Wait-time", "wait time": "Wait-time",
            "late night": "Late-night", "chicken wings": "Chicken wings",
        }
        return label_map.get(useful[0], " ".join(w.capitalize() for w in useful[0].split()))
    return category.replace("_", " ").title() if category else "Food"
