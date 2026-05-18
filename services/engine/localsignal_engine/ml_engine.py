import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from localsignal_engine.models import Mention, Place, Signal
from localsignal_engine.scoring import week_start

STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "always",
    "all",
    "and",
    "are",
    "author",
    "any",
    "because",
    "been",
    "but",
    "can",
    "day",
    "for",
    "from",
    "get",
    "had",
    "has",
    "have",
    "into",
    "its",
    "just",
    "more",
    "near",
    "new",
    "not",
    "now",
    "one",
    "ordered",
    "our",
    "out",
    "over",
    "place",
    "relative",
    "she",
    "still",
    "time",
    "the",
    "their",
    "there",
    "that",
    "they",
    "this",
    "very",
    "week",
    "were",
    "was",
    "when",
    "whatever",
    "which",
    "will",
    "with",
    "would",
    "you",
    "your",
}

POSITIVE_TERMS = {
    "amazing",
    "best",
    "busy",
    "excellent",
    "favorite",
    "fresh",
    "great",
    "hidden",
    "popular",
    "quiet",
    "recommend",
    "trending",
    "worth",
}

NEGATIVE_TERMS = {
    "bad",
    "crowded",
    "decline",
    "expensive",
    "long",
    "overrated",
    "slow",
    "wait",
    "worse",
}


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
        current_mentions = [mention for mention in place_mentions if mention.occurred_at >= current_cutoff]
        baseline_mentions = [mention for mention in place_mentions if baseline_cutoff <= mention.occurred_at < current_cutoff]
        if not current_mentions:
            continue

        place = place_lookup[place_id]
        current_tokens = _tokens(current_mentions)
        baseline_tokens = _tokens(baseline_mentions)
        keywords = _top_keywords(current_tokens, baseline_tokens)
        source_count = len({mention.source for mention in current_mentions})
        current_sentiment = _average_sentiment(current_mentions)
        baseline_sentiment = _average_sentiment(baseline_mentions)
        sentiment_delta = current_sentiment - baseline_sentiment
        velocity_ratio = _velocity_ratio(len(current_mentions), len(baseline_mentions), current_window_days, baseline_window_days)
        outside_regions = {
            mention.author_region
            for mention in current_mentions
            if mention.author_region and mention.author_region.lower() != place.city.lower()
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
                    "sources": sorted({mention.source for mention in current_mentions}),
                },
                score=round(score, 2),
                week_start=week_start(now),
                keywords=keywords,
            )
        )

    return sorted(signals, key=lambda signal: signal.score, reverse=True)[:12]


def _tokens(mentions: list[Mention]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for mention in mentions:
        words = re.findall(r"[a-z][a-z0-9'-]{2,}", mention.body.lower())
        counter.update(word for word in words if word not in STOPWORDS)
    return counter


def _top_keywords(current: Counter[str], baseline: Counter[str]) -> list[str]:
    scores: list[tuple[str, float]] = []
    for token, count in current.items():
        novelty = count / math.sqrt(1 + baseline.get(token, 0))
        if novelty >= 1:
            scores.append((token, novelty))
    return [token for token, _score in sorted(scores, key=lambda item: item[1], reverse=True)[:5]]


def _average_sentiment(mentions: list[Mention]) -> float:
    if not mentions:
        return 0
    return sum(_mention_sentiment(mention) for mention in mentions) / len(mentions)


def _mention_sentiment(mention: Mention) -> float:
    if mention.sentiment is not None:
        return mention.sentiment
    words = set(re.findall(r"[a-z][a-z0-9'-]{2,}", mention.body.lower()))
    positive = len(words.intersection(POSITIVE_TERMS))
    negative = len(words.intersection(NEGATIVE_TERMS))
    if mention.rating is not None:
        rating_sentiment = (mention.rating - 3) / 2
    else:
        rating_sentiment = 0
    lexical_sentiment = (positive - negative) / max(3, positive + negative + 1)
    return max(-1, min(1, (rating_sentiment * 0.7) + (lexical_sentiment * 0.3)))


def _velocity_ratio(current_count: int, baseline_count: int, current_days: int, baseline_days: int) -> float:
    current_rate = current_count / max(current_days, 1)
    baseline_rate = baseline_count / max(baseline_days, 1)
    return current_rate / max(baseline_rate, 0.05)


def _classify(velocity_ratio: float, sentiment_delta: float, keywords: list[str]) -> str:
    if sentiment_delta <= -0.15 or {"wait", "slow", "crowded", "overrated"}.intersection(keywords):
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
    score = (
        min(current_count * 7, 28)
        + min(source_count * 10, 30)
        + min(keyword_count * 4, 16)
        + min(math.log1p(velocity_ratio) * 8, 22)
        + min(abs(sentiment_delta) * 28, 10)
        + min(outside_region_count * 4, 8)
    )
    return min(score, 100)


def _explain(
    place: Place,
    signal_type: str,
    keywords: list[str],
    velocity_ratio: float,
    sentiment_delta: float,
    source_count: int,
) -> tuple[str, str]:
    keyword_text = ", ".join(keywords[:3]) if keywords else "recent mentions"
    topic = _title_topic(keywords, place.category)
    area = place.neighborhood or place.city
    if signal_type == "sentiment_shift":
        return (
            f"Wait-time talk is shifting at {place.name}" if topic == "Wait-time" else f"{topic} tone is shifting at {place.name}",
            f"Recent language around {keyword_text} is moving differently from the short-term baseline.",
        )
    if signal_type == "behavior_shift":
        return (
            f"{topic} use is changing at {place.name}",
            f"Recent mentions across {source_count} source(s) increasingly point to {keyword_text}.",
        )
    if signal_type == "review_velocity_spike":
        if source_count >= 3:
            return (
                f"{topic} is spreading across multiple source types at {place.name}",
                f"Recent activity is appearing across {source_count} source types, with repeated language around {keyword_text}.",
            )
        if velocity_ratio >= 5:
            return (
                f"{topic} keeps coming up at {place.name}",
                f"Recent mentions are materially above the short-term baseline, led by language around {keyword_text}.",
            )
        return (
            f"{topic} activity is picking up at {place.name}",
            f"Recent activity is moving ahead of baseline, with new keywords around {keyword_text}.",
        )
    return (
        f"{topic} is becoming the repeated clue at {place.name}",
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
    normalized = [keyword.strip().lower() for keyword in keywords if keyword and keyword.strip()]
    useful = [keyword for keyword in normalized if keyword in allowed_terms]
    if "chicken" in normalized and "wings" in normalized and "chicken wings" not in useful:
        useful.insert(0, "chicken wings")
    if useful:
        label_map = {"wait": "Wait-time", "wait time": "Wait-time", "late night": "Late-night", "chicken wings": "Chicken wings"}
        return label_map.get(useful[0], " ".join(word.capitalize() for word in useful[0].split()))
    if category:
        return category.replace("_", " ").title()
    return "Food"
