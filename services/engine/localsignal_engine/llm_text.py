import re
from typing import Any, Optional


BANNED_WORDS = {
    "best",
    "top rated",
    "must try",
    "recommendation",
    "recommended",
    "market dynamics",
    "business reputation",
    "decision making",
    "consumer perception",
    "consumer",
    "consumers",
    "customer experience",
    "customers",
    "dining choices",
    "expectations",
    "promotional activity",
    "patrons",
    "demand",
    "establishment",
    "establishments",
    "detected",
}

BRIEFING_BANNED_WORDS = {
    "confidence",
    "source diversity",
    "source count",
    "source type",
    "signal type",
    "taxonomy",
    "anomaly",
    "detected",
    "evidence receipt",
    "repeated clue",
    "dashboard",
    "metric",
    "baseline",
    "activity",
    "chatter",
    "momentum",
    "engagement",
    "experience",
    "quality",
    "service quality",
    "customer",
    "customers",
    "customer experience",
    "consumer",
    "consumers",
    "demand",
    "popularity",
    "popular",
    "market",
    "patrons",
    "diverse dining visits",
    "dining visits",
    "restaurant atmospheres",
    "recent uptick",
    "recommendation",
    "recommended",
}

BRIEFING_SIGNALISH_PATTERNS = {
    "activity is picking up at",
    "restaurant activity",
    "is changing at",
    "keeps coming up at",
    "talk is shifting at",
    "use is changing at",
}


class LlmEnrichmentError(RuntimeError):
    pass


def _clean_output(value: str, fallback: str, max_length: int = 700) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").replace("\x00", "")).strip()
    return cleaned[:max_length] if cleaned else fallback


def _clean_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_clean_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_clean_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key).replace("\x00", ""): _clean_json_value(item) for key, item in value.items()}
    return value


def _sanitize_banned_words(value: Any, banned_words: Optional[list[str]] = None) -> Any:
    replacements = {
        "activity": "movement",
        "anomaly": "unusual read",
        "baseline": "usual rhythm",
        "chatter": "talk",
        "confidence": "read",
        "dashboard": "brief",
        "detection": "read",
        "engagement": "attention",
        "experience": "visit",
        "evidence receipt": "source note",
        "metric": "read",
        "momentum": "movement",
        "popular": "busy",
        "popularity": "busy-ness",
        "quality": "food",
        "repeated clue": "repeated cue",
        "service quality": "service",
        "source count": "source mix",
        "source diversity": "source mix",
        "source type": "source",
        "signal type": "read type",
        "taxonomy": "category",
        "dining choices": "local read",
        "diverse dining visits": "different meals",
        "dining visits": "meals",
        "restaurant atmospheres": "dinner settings",
        "recent uptick": "recent mentions",
        "expectations": "read",
        "demand": "pull",
        "consumer perception": "local read",
        "customer experience": "visit language",
        "customers": "visitors",
        "customer": "visitor",
        "patrons": "visitors",
        "market dynamics": "local movement",
        "business reputation": "local read",
        "decision making": "local read",
        "promotional activity": "promotion",
        "recommendation": "signal",
        "recommended": "noted",
        "top rated": "highly rated",
        "must try": "notable",
        "best": "notable",
    }
    active = banned_words or list(replacements)
    if isinstance(value, str):
        cleaned = value
        for word in active:
            cleaned = re.sub(re.escape(word), replacements.get(word, ""), cleaned, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", cleaned).strip()
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _sanitize_banned_words(item, active)
    elif isinstance(value, dict):
        for key, item in list(value.items()):
            if key == "signal_slug":
                continue
            value[key] = _sanitize_banned_words(item, active)
    return value


def _clean_place_name(value: str) -> str:
    cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\$B|\x1b\(B", "", value)
    cleaned = re.sub(r"\(\s*(?:[0-9a-fA-F]{2,4}\s*)+\)", "", cleaned)
    cleaned = re.sub(r"\b[0-9a-fA-F]{6,}\b", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip() or "This place"


def _truncate_sentence(value: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    clipped = re.sub(r"\b(and|or|through|around|near)$", "", clipped, flags=re.IGNORECASE).rstrip(" ,;:")
    if "." in clipped:
        sentence = clipped.rsplit(".", 1)[0].strip()
        if len(sentence) >= limit * 0.45:
            sentence = re.sub(r"\b(and|or|through|around|near)$", "", sentence, flags=re.IGNORECASE).rstrip(" ,;:")
            return sentence + "."
    return clipped + "."


def _normalize_slug(value: Any) -> str:
    return str(value or "").strip().strip("/")


def _natural_join(values: list[str]) -> str:
    cleaned = [value for value in values if value]
    if len(cleaned) <= 1:
        return cleaned[0] if cleaned else ""
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    return [value for value in values if not (value in seen or seen.add(value))]
