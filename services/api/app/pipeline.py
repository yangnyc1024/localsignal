import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any


FOOD_TRIGGER_TERMS = {
    "line",
    "wait",
    "sold out",
    "worth the drive",
    "came from manhattan",
    "viral",
    "new menu",
    "opening",
    "soft opening",
    "reservation",
    "packed",
    "quiet work spot",
    "late night",
    "wifi",
    "outlet",
    "remote",
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "signal"


def score_candidate(metrics: dict[str, Any]) -> tuple[float, dict[str, float]]:
    component_scores = {
        "mention_velocity_score": _normalize(metrics.get("velocity_ratio"), cap=6),
        "keyword_growth_score": _normalize(metrics.get("keyword_count"), cap=8),
        "source_diversity_score": _normalize(metrics.get("source_count"), cap=4),
        "recency_score": _normalize(metrics.get("recency_score", 1), cap=1),
        "sentiment_score": _normalize(abs(float(metrics.get("sentiment_delta") or 0)), cap=0.5),
        "geo_spread_score": _normalize(metrics.get("outside_region_count"), cap=3),
    }
    score = (
        0.25 * component_scores["mention_velocity_score"]
        + 0.20 * component_scores["keyword_growth_score"]
        + 0.20 * component_scores["source_diversity_score"]
        + 0.15 * component_scores["recency_score"]
        + 0.10 * component_scores["sentiment_score"]
        + 0.10 * component_scores["geo_spread_score"]
    )
    return round(score, 2), component_scores


def confidence_from_metrics(metrics: dict[str, Any], place_resolution_confidence: float = 1) -> tuple[str, float, str]:
    source_count = int(metrics.get("source_count") or 0)
    mention_count = int(metrics.get("current_mention_count") or metrics.get("mention_count") or 0)
    keyword_count = int(metrics.get("keyword_count") or len(metrics.get("keywords", [])))
    outside_regions = int(metrics.get("outside_region_count") or 0)

    score = min(
        100,
        (source_count * 22)
        + (min(mention_count, 5) * 10)
        + (min(keyword_count, 5) * 4)
        + (outside_regions * 6)
        + (place_resolution_confidence * 18),
    )

    if score >= 78:
        return (
            "High",
            round(score, 2),
            f"High confidence because the signal repeats across {source_count} source(s), {mention_count} recent mention(s), and has consistent place resolution.",
        )
    if score >= 48:
        return (
            "Medium",
            round(score, 2),
            f"Medium confidence because the signal has some repetition, but source diversity or time consistency is still developing.",
        )
    return (
        "Low",
        round(score, 2),
        "Low confidence because the signal has limited repetition, weak source diversity, or ambiguous evidence.",
    )


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_keywords(text: str) -> list[str]:
    lowered = clean_text(text).lower()
    phrase_hits = [term for term in FOOD_TRIGGER_TERMS if term in lowered]
    tokens = re.findall(r"[a-z][a-z0-9'-]{2,}", lowered)
    stopwords = {
        "and",
        "the",
        "for",
        "with",
        "this",
        "that",
        "from",
        "place",
        "food",
        "good",
        "very",
        "still",
    }
    common = [token for token, _ in Counter(token for token in tokens if token not in stopwords).most_common(8)]
    seen: set[str] = set()
    return [keyword for keyword in [*phrase_hits, *common] if not (keyword in seen or seen.add(keyword))][:10]


def llm_signal_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "title",
            "phenomenon_title",
            "short_summary",
            "ai_summary",
            "what_changed",
            "why_this_matters",
            "confidence_reason",
            "tags",
            "food_or_cuisine_type",
            "place_anchor_reason",
            "reader_hook",
            "what_to_notice",
            "skeptic_note",
            "good_for",
            "watch_out",
            "best_read_as",
            "evidence_receipt",
            "place_profile",
            "food_signal",
            "evidence_ids",
        ],
        "properties": {
            "title": {"type": "string"},
            "phenomenon_title": {"type": "string"},
            "short_summary": {"type": "string"},
            "ai_summary": {"type": "string"},
            "what_changed": {"type": "array", "items": {"type": "string"}},
            "why_this_matters": {"type": "string"},
            "confidence_reason": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "food_or_cuisine_type": {"type": "string"},
            "place_anchor_reason": {"type": "string"},
            "reader_hook": {"type": "string"},
            "what_to_notice": {"type": "string"},
            "skeptic_note": {"type": "string"},
            "good_for": {"type": "string"},
            "watch_out": {"type": "string"},
            "best_read_as": {"type": "string"},
            "evidence_receipt": {
                "type": "object",
                "additionalProperties": False,
                "required": ["recent_mentions", "source_types", "repeated_terms", "freshness", "evidence_read"],
                "properties": {
                    "recent_mentions": {"type": "string"},
                    "source_types": {"type": "string"},
                    "repeated_terms": {"type": "string"},
                    "freshness": {"type": "string"},
                    "evidence_read": {"type": "string"}
                }
            },
            "place_profile": {
                "type": "object",
                "additionalProperties": False,
                "required": ["known_for", "food_types", "signature_items", "flavor_cues", "occasions", "caveats", "source_count"],
                "properties": {
                    "known_for": {"type": "string"},
                    "food_types": {"type": "array", "items": {"type": "string"}},
                    "signature_items": {"type": "array", "items": {"type": "string"}},
                    "flavor_cues": {"type": "array", "items": {"type": "string"}},
                    "occasions": {"type": "array", "items": {"type": "string"}},
                    "caveats": {"type": "string"},
                    "source_count": {"type": "integer"}
                }
            },
            "food_signal": {
                "type": "object",
                "additionalProperties": False,
                "required": ["summary", "primary_pull", "flavor_cue", "occasion", "confidence", "evidence_basis", "image_query", "image_alt"],
                "properties": {
                    "summary": {"type": "string"},
                    "primary_pull": {"type": "string"},
                    "flavor_cue": {"type": "string"},
                    "occasion": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["High", "Medium", "Low"]},
                    "evidence_basis": {"type": "string"},
                    "image_query": {"type": "string"},
                    "image_alt": {"type": "string"}
                }
            },
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
    }


def build_llm_prompt(place: dict, candidate: dict, evidence_chunks: list[dict]) -> dict[str, Any]:
    return {
        "instructions": [
            "You generate calm analytical food signal interpretation for LocalSignal.",
            "Use only the provided metrics and evidence chunks.",
            "Do not invent sources, claims, dates, popularity, ratings, or engagement.",
            "Avoid Yelp-like wording such as best, top rated, must try, or recommendation.",
            "Write the title as a food/local phenomenon first, not a place-first claim.",
            "Use the place only as an anchor where activity is showing up.",
            "Include reader_hook, what_to_notice, skeptic_note, good_for, watch_out, best_read_as, place_anchor_reason, food_or_cuisine_type, and evidence_receipt for reader framing.",
            "Also produce place_profile and food_signal.",
            "food_signal should name the food, flavor, or occasion pulling the current signal. If food-level evidence is thin, say so and lower confidence.",
            "For food_signal.image_query, write a short visual food query, not a URL.",
            "Make card-level fields distinct: reader_hook should name the concrete dish, behavior, scene, or uncertainty; what_to_notice should not repeat the title; skeptic_note should state the main limitation calmly.",
            "Output valid JSON only.",
        ],
        "place": place,
        "candidate": candidate,
        "evidence_chunks": evidence_chunks,
        "allowed_signal_types": [
            "KEYWORD_SPIKE",
            "REVIEW_VELOCITY",
            "CROSS_NEIGHBORHOOD_MOMENTUM",
            "VIRAL_MENU_ITEM",
            "WAIT_TIME_INCREASE",
            "REMOTE_WORK_SHIFT",
            "LATE_NIGHT_DEMAND",
            "NEW_OPENING_MOMENTUM",
        ],
        "json_schema": llm_signal_json_schema(),
    }


def recency_score(timestamp: datetime) -> float:
    now = datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = now - timestamp
    return max(0, 1 - (age / timedelta(days=30)))


def _normalize(value: Any, cap: float) -> float:
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        numeric = 0
    return round(min(max(numeric / cap, 0), 1) * 100, 2)
