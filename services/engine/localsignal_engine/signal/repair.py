import os
from typing import Any, Optional

from localsignal_engine.llm import _clean_place_name, _dedupe


def _min_evidence_count() -> int:
    return int(os.getenv("LLM_ENRICH_MIN_EVIDENCE_COUNT", os.getenv("SIGNAL_GENERATE_MIN_EVIDENCE_COUNT", "2")))


def _min_source_diversity() -> int:
    return int(os.getenv("LLM_ENRICH_MIN_SOURCE_DIVERSITY", os.getenv("SIGNAL_GENERATE_MIN_SOURCE_DIVERSITY", "1")))


def _profile_string_list(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _food_pull_from_facts(facts: list) -> Optional[dict]:
    """Derive food pull from persisted place_food_facts (highest confidence dish first)."""
    dishes = [f for f in facts if f.get("fact_type") == "dish" and f.get("confidence", 0) >= 0.6]
    if not dishes:
        return None
    top = dishes[0]
    dish = str(top.get("fact_value") or "").strip()
    if not dish:
        return None
    return {
        "primary_pull": dish,
        "flavor_cue": "",
        "occasion": "",
        "image_query": dish.lower(),
        "image_alt": dish,
        "basis": f"Derived from persisted food fact (confidence {top.get('confidence', 0):.2f}).",
    }


def _story_topic(keywords: list, category: str):
    allowed_terms = {
        "line", "wait", "wait time", "sold out", "worth the drive", "viral", "new menu",
        "opening", "soft opening", "reservation", "packed", "quiet work spot", "late night",
        "pizza", "sourdough", "bread", "pastry", "croissant", "bun", "cake", "dessert",
        "matcha", "cream", "coffee", "latte", "seafood", "crab", "chicken wings", "wings",
        "bbq", "korean bbq", "ramen", "sushi", "gyro", "kebab", "falafel", "empanadas",
    }
    normalized = [str(keyword).strip().lower() for keyword in keywords if str(keyword).strip()]
    useful = [keyword for keyword in normalized if keyword in allowed_terms]
    if "chicken" in normalized and "wings" in normalized and "chicken wings" not in useful:
        useful.insert(0, "chicken wings")
    if useful:
        label_map = {"wait": "Wait-time", "wait time": "Wait-time", "late night": "Late-night", "chicken wings": "Chicken wings"}
        topic = label_map.get(useful[0], " ".join(part.capitalize() for part in useful[0].split()))
        return topic, ", ".join(useful[:3])
    fallback = category or "Food"
    return fallback, fallback.lower()


def _story_fields(signal: dict, keywords: list, evidence: dict) -> dict[str, Any]:
    place = signal["place"]
    place_name = place.get("name") or "This place"
    category = str(place.get("category") or "food").replace("_", " ").title()
    title_topic, keyword_text = _story_topic(keywords, category)
    if signal["signal_type"] == "sentiment_shift":
        phenomenon = f"{place_name} has a changing wait-time read" if title_topic == "Wait-time" else f"{place_name} has a changing {title_topic.lower()} read"
    elif signal["signal_type"] == "review_velocity_spike":
        phenomenon = f"{place_name} is getting more recent attention for {title_topic.lower()}"
    elif signal["signal_type"] == "behavior_shift":
        phenomenon = f"{place_name} has a changing {title_topic.lower()} visit read"
    else:
        phenomenon = f"{place_name} is showing repeated language around {title_topic.lower()}"
    return {
        "phenomenon_title": phenomenon,
        "food_or_cuisine_type": category,
        "place_anchor_reason": f"{place_name} is the place where this signal is anchored; it is not a blanket recommendation.",
        "reader_hook": phenomenon,
        "what_to_notice": f"The useful read is the repeated language around {keyword_text}, not a best-of claim.",
        "place_profile": _repair_place_profile(signal, {}, {}, []),
        "food_signal": {
            "summary": f"Food-level evidence is still thin; the current read is around {keyword_text}.",
            "primary_pull": keyword_text,
            "flavor_cue": "",
            "occasion": "",
            "confidence": signal.get("confidence_level") or "Medium",
            "evidence_basis": "Derived from current signal keywords and evidence snippets.",
            "image_query": f"{category} food",
            "image_alt": f"{category} food",
        },
    }


def _repair_food_signal(signal: dict, food_signal: dict, evidence: list, place_context: Optional[dict] = None) -> dict:
    repaired = dict(food_signal or {})
    primary = str(repaired.get("primary_pull") or "").strip()
    if primary and primary.lower() not in {"restaurant", "food", "local food", "place", "general food"}:
        return repaired

    food_facts = (place_context or {}).get("food_facts") or []
    pull = _food_pull_from_facts(food_facts)
    if not pull:
        return repaired

    repaired["primary_pull"] = pull["primary_pull"]
    repaired["signal_dish"] = repaired.get("signal_dish") or ""
    repaired["flavor_cue"] = repaired.get("flavor_cue") or pull.get("flavor_cue") or ""
    repaired["occasion"] = repaired.get("occasion") or pull.get("occasion") or ""
    repaired["image_query"] = repaired.get("image_query") if str(repaired.get("image_query") or "").lower() not in {"restaurant food", "food"} else pull["image_query"]
    repaired["image_alt"] = repaired.get("image_alt") if str(repaired.get("image_alt") or "").lower() not in {"restaurant food", "food"} else pull["image_alt"]
    repaired["summary"] = (
        f"{pull['primary_pull']} is the clearest food-level pull in the retrieved place context. "
        f"{pull.get('basis', 'Recent evidence is still limited, so this should stay evidence-led.')}"
    )
    repaired["evidence_basis"] = repaired.get("evidence_basis") or "Repaired from retrieved place context and current evidence because the LLM returned a generic food label."
    return repaired


def _repair_place_profile(signal: dict, profile: dict, food_signal: dict, evidence: list) -> dict:
    """Sanitise the LLM-generated place_profile dict.

    No rule-based keyword extraction — trust the LLM output and only fill in
    missing fields from food_signal (which is itself LLM-generated).
    """
    repaired = dict(profile or {})

    primary_pull = str(food_signal.get("primary_pull") or "").strip()
    flavor = str(food_signal.get("flavor_cue") or "").strip()
    occasion = str(food_signal.get("occasion") or "").strip()

    if not str(repaired.get("known_for") or "").strip():
        place_name = _clean_place_name(str((signal.get("place") or {}).get("name") or "This place"))
        repaired["known_for"] = f"{place_name} — profile pending next brief refresh." if not primary_pull else f"{place_name} is a {primary_pull} place."

    food_types = [
        t for t in _profile_string_list(repaired.get("food_types"))
        if len(t) < 40 and "." not in t and len(t.split()) <= 4
    ]
    repaired["food_types"] = _dedupe(food_types)

    signature_items = _profile_string_list(repaired.get("signature_items"))
    repaired["signature_items"] = _dedupe(signature_items)[:5]

    flavor_cues = _profile_string_list(repaired.get("flavor_cues"))
    if flavor and flavor not in flavor_cues:
        flavor_cues.append(flavor)
    repaired["flavor_cues"] = _dedupe(flavor_cues)[:4]

    occasions = _profile_string_list(repaired.get("occasions"))
    if occasion and occasion not in occasions:
        occasions.append(occasion)
    repaired["occasions"] = _dedupe(occasions)[:4]

    source_count = int(repaired.get("source_count") or 0)
    repaired["source_count"] = max(source_count, len([row for row in evidence if row.get("chunk_text")]) or 1)
    if not str(repaired.get("caveats") or "").strip():
        repaired["caveats"] = "Profile is based on retrieved place context and current evidence; keep claims limited to those sources."
    return repaired
