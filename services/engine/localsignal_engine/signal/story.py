"""Signal story-field derivation — pure business logic, no DB access."""
import re
from typing import Any

from localsignal_engine.models import Signal
from localsignal_engine.place.names import display_place_name

# Short, stable per-type slug fragments. The slug key matches the DB
# uniqueness key (place_id, signal_type, week_start), so this format is
# guaranteed unique and never leaks generated prose into URLs.
_SLUG_TYPE_LABELS = {
    "review_velocity_spike": "attention",
    "keyword_spike": "keywords",
    "sentiment_shift": "sentiment",
    "behavior_shift": "behavior",
    "new_place_detected": "new-place",
}

_SLUG_PLACE_MAX_CHARS = 32


def story_fields_for_signal(signal: Signal) -> dict:
    evidence = signal.evidence
    place_name = display_place_name(signal.place.display_name or signal.place.name)
    keywords = [str(k) for k in evidence.get("keywords", [])]
    category = signal.place.category.replace("_", " ").title()
    topic, keyword_text = story_topic(keywords, category)
    area = signal.place.neighborhood or signal.place.city
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    if signal.signal_type == "sentiment_shift":
        phenomenon_title = (
            f"{place_name} has a changing wait-time read"
            if topic == "Wait-time"
            else f"{place_name} has a changing {topic.lower()} read"
        )
    elif signal.signal_type == "behavior_shift":
        phenomenon_title = f"{place_name} has a changing {topic.lower()} visit read"
    elif signal.signal_type == "review_velocity_spike":
        phenomenon_title = f"{place_name} is getting more recent attention for {topic.lower()}"
    else:
        phenomenon_title = f"{place_name} is showing repeated language around {topic.lower()}"
    return {
        "phenomenon_title": phenomenon_title,
        "food_or_cuisine_type": category,
        "place_anchor_reason": f"{place_name} is the place where this food read is anchored, not a blanket recommendation.",
        "reader_hook": phenomenon_title,
        "what_to_notice": f"Watch the repeated language around {keyword_text}; do not read this as a best-of ranking.",
        "skeptic_note": "Evidence is still narrow until it repeats across more independent sources.",
        "good_for": f"People tracking {keyword_text} movement near {area}.",
        "watch_out": "Read this as movement evidence, not a taste ranking.",
        "best_read_as": "A local food signal to notice, with judgment left to the reader.",
        "evidence_receipt": {
            "recent_mentions": str(mention_count or "Building"),
            "source_types": str(source_count or 1),
            "repeated_terms": keyword_text,
            "freshness": f"Last {evidence.get('current_window_days', 7)} days",
            "evidence_read": confidence_from_evidence(evidence)[0],
        },
    }


def story_topic(keywords: list[str], category: str) -> tuple[str, str]:
    allowed_terms = {
        "line", "wait", "wait time", "sold out", "worth the drive", "viral", "new menu",
        "opening", "soft opening", "reservation", "packed", "quiet work spot", "late night",
        "pizza", "sourdough", "bread", "pastry", "croissant", "bun", "cake", "dessert",
        "matcha", "cream", "coffee", "latte", "seafood", "crab", "chicken wings", "wings",
        "bbq", "korean bbq", "ramen", "sushi", "gyro", "kebab", "falafel", "empanadas",
    }
    normalized = [str(k).strip().lower() for k in keywords if str(k).strip()]
    useful = [k for k in normalized if k in allowed_terms]
    if "chicken" in normalized and "wings" in normalized and "chicken wings" not in useful:
        useful.insert(0, "chicken wings")
    if useful:
        label_map = {
            "wait": "Wait-time", "wait time": "Wait-time",
            "late night": "Late-night", "chicken wings": "Chicken wings",
        }
        topic = label_map.get(useful[0], " ".join(p.capitalize() for p in useful[0].split()))
        return topic, ", ".join(useful[:3])
    fallback = category or "Food"
    return fallback, fallback.lower()


def product_fields(signal: Signal) -> dict:
    evidence = signal.evidence
    current_days = evidence.get("current_window_days", 14)
    metrics = metrics_from_evidence(signal)
    confidence_level, confidence_score, confidence_reason = confidence_from_evidence(evidence)
    short = short_summary(signal)
    fields = story_fields_for_signal(signal)
    signal.evidence.update({k: v for k, v in fields.items() if k not in signal.evidence or not signal.evidence.get(k)})
    return {
        "slug": signal_slug(signal),
        "short_summary": short,
        "ai_summary": ai_summary(signal, short),
        "why_this_matters": why_this_matters(signal),
        "confidence_level": confidence_level,
        "confidence_score": confidence_score,
        "confidence_reason": confidence_reason,
        "metrics": metrics,
        "time_window": f"Last {current_days} days",
    }


def metrics_from_evidence(signal: Signal) -> list[dict]:
    evidence = signal.evidence
    keywords = evidence.get("keywords", [])
    return [
        {
            "label": "Keyword growth",
            "value": f"{len(keywords)} active terms" if keywords else "Emerging",
            "detail": ", ".join(keywords[:3]) if keywords else "New language is clustering around this signal.",
            "trend": "up",
        },
        {
            "label": "Mention velocity",
            "value": (
                f"{float(evidence.get('velocity_ratio')):.1f}x baseline"
                if evidence.get("velocity_ratio") is not None
                else "Above baseline"
            ),
            "detail": "Compared with the recent baseline window.",
            "trend": "up",
        },
        {
            "label": "Source diversity",
            "value": f"{int(evidence.get('source_count') or len(evidence.get('sources', [])))} source(s)",
            "detail": "Independent sources make a signal more trustworthy.",
            "trend": "steady",
        },
        {
            "label": "Location spread",
            "value": f"{int(evidence.get('outside_region_count') or 0)} outside area(s)",
            "detail": "Cross-neighborhood attention is treated as momentum.",
            "trend": "up" if evidence.get("outside_region_count") else "steady",
        },
    ]


def confidence_from_evidence(evidence: dict) -> tuple[str, float, str]:
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    outside_regions = int(evidence.get("outside_region_count") or 0)
    score = min(100, source_count * 24 + min(mention_count, 5) * 12 + outside_regions * 8)
    if score >= 78:
        return (
            "High", float(score),
            f"High confidence because this repeats across {source_count} source(s) and {mention_count} recent mention(s).",
        )
    if score >= 48:
        return "Medium", float(score), "Medium confidence because the signal has some repetition, but evidence depth is still developing."
    return "Low", float(score), "Low confidence because repetition or source diversity is limited."


def short_summary(signal: Signal) -> str:
    evidence = signal.evidence
    keywords = evidence.get("keywords", [])
    keyword_text = ", ".join(keywords[:3]) if keywords else "recent food-language"
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    velocity = evidence.get("velocity_ratio")
    spread = int(evidence.get("outside_region_count") or 0)
    if signal.signal_type == "behavior_shift":
        return f"Recent evidence points to a usage shift around {keyword_text}, with {source_count or 1} source type(s) contributing."
    if signal.signal_type == "sentiment_shift":
        return f"Recent language around {keyword_text} suggests a directional quality or service change worth monitoring."
    if spread:
        return f"Attention around {keyword_text} is showing signs of cross-neighborhood pull, not just local familiarity."
    if source_count >= 3:
        return f"Activity is appearing across {source_count} source types, with repeated language around {keyword_text}."
    if velocity is not None and float(velocity) >= 5:
        return f"Recent activity is materially above the short-term baseline, led by language around {keyword_text}."
    return signal.summary


def ai_summary(signal: Signal, short: str) -> str:
    evidence = signal.evidence
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    return (
        f"{short} The signal is based on {mention_count} recent matched mention(s) "
        f"across {source_count or 1} source type(s), so it should be read as momentum evidence rather than a quality ranking."
    )


def why_this_matters(signal: Signal) -> str:
    place_name = display_place_name(signal.place.display_name or signal.place.name)
    if signal.signal_type == "behavior_shift":
        return f"{place_name} is showing behavior change, which can indicate a new food-use occasion rather than normal attention."
    if signal.signal_type == "sentiment_shift":
        return (
            f"{place_name} has a directional service or wait-time signal worth watching "
            "because momentum can change quickly when complaints repeat."
        )
    if signal.signal_type == "review_velocity_spike":
        return f"{place_name} is gaining attention faster than its recent baseline, suggesting broader food discovery momentum."
    return f"{place_name} has new language clustering around it, which can be an early indicator of emerging demand."


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "signal"


def signal_slug(signal: Signal) -> str:
    place_part = slugify(display_place_name(signal.place.display_name or signal.place.name))
    kept: list[str] = []
    for word in place_part.split("-"):
        if len("-".join(kept + [word])) > _SLUG_PLACE_MAX_CHARS:
            break
        kept.append(word)
    place_part = "-".join(kept) or "place"
    type_part = _SLUG_TYPE_LABELS.get(signal.signal_type, "signal")
    return f"{place_part}-{type_part}-{signal.week_start}"
