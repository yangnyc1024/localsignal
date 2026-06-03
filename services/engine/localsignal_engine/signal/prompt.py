import re
from typing import Any, Optional

from localsignal_engine.llm_text import _clean_output


def _latin_place_name(name: str) -> str:
    """Return the Latin/ASCII portion of a place name, stripping CJK characters."""
    latin = re.sub(r"[ᄀ-ᇿ㄰-㆏가-힯一-鿿぀-ヿ＀-￯]+", "", name)
    latin = re.sub(r"^\s*\(\s*(.*?)\s*\)\s*$", r"\1", latin.strip())
    latin = re.sub(r"\s+", " ", latin).strip()
    return latin or name


def _safe_title(value: str, fallback: str) -> str:
    """Clean LLM title output and reject garbled hex/encoding artifacts."""
    cleaned = _clean_output(value, fallback)
    if re.search(r"\b[0-9a-fA-F]{8,}\b", cleaned):
        return fallback
    return cleaned


def _json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
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
                    "evidence_read": {"type": "string"},
                },
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
                    "source_count": {"type": "integer"},
                },
            },
            "food_signal": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "summary",
                    "primary_pull",
                    "signal_dish",
                    "flavor_cue",
                    "occasion",
                    "confidence",
                    "evidence_basis",
                    "image_query",
                    "image_alt",
                ],
                "properties": {
                    "summary": {"type": "string"},
                    "primary_pull": {"type": "string"},
                    "signal_dish": {"type": "string"},
                    "flavor_cue": {"type": "string"},
                    "occasion": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["High", "Medium", "Low"]},
                    "evidence_basis": {"type": "string"},
                    "image_query": {"type": "string"},
                    "image_alt": {"type": "string"},
                },
            },
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
    }


def _prompt(signal: dict, evidence: list, place_context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    place = dict(signal["place"])
    place["display_name"] = _latin_place_name(place.get("name") or "")
    return {
        "instructions": [
            "You generate calm analytical food signal interpretation for LocalSignal.",
            "Use only the provided metrics, evidence chunks, place profile, and retrieved place documents.",
            "Treat official_description documents as context-only place identity. They may describe what the place says about itself, but they must not be used as proof of recent momentum, demand, sentiment, or popularity.",
            "Do not invent sources, dates, ratings, engagement, popularity, or unsupported claims.",
            "Avoid Yelp-like wording such as best, top rated, must try, recommendation, or recommended.",
            "The product is a food signal, not a restaurant recommendation.",
            "Write for a local resident deciding what changed nearby, not for a business owner or market analyst.",
            "Avoid business strategy language such as market dynamics, business reputation, consumer perception, or decision making.",
            "ALWAYS use place.display_name (not place.name) when writing human-readable text including titles, summaries, and descriptions. place.name may contain non-Latin characters.",
            "phenomenon_title: write a specific food-focused description of what is happening. Do NOT copy or mirror the current_title pattern. Bad: 'X is getting more recent attention for Y'. Good: 'Katsu cutlets drawing repeat visits in Palisades Park' or 'Bingsu sentiment shifting at Cafe Miel'. Include a specific food item or behavior when evidence supports it. Keep under 12 words.",
            "Use the place as an anchor, not as the product. Avoid titles like '<place> has activity lift'.",
            "Do not use the word detected.",
            "Explain what changed in concrete terms: mention pace, repeated dishes/food terms, wait/crowd/lateness behavior, source diversity, or confidence.",
            "Also produce reader framing fields: reader_hook, what_to_notice, skeptic_note, good_for, watch_out, best_read_as, place_anchor_reason, food_or_cuisine_type, evidence_receipt.",
            "Also produce place_profile and food_signal.",
            "place_context.food_facts contains verified dish and behavior facts extracted from restaurant briefs — treat these as high-confidence anchors when populating food_signal.signal_dish and place_profile.signature_items.",
            "place_profile describes the durable place identity from official_description, menu, place profile, food_facts, and other stable context.",
            "place_profile.food_types must contain short cuisine-category labels only (e.g. 'Korean BBQ', 'Cajun seafood', 'Italian', 'Dessert cafe'). Never put sentences, service descriptions, or primary_pull text into food_types.",
            "food_signal describes what food, flavor, or occasion is pulling the current signal.",
            "food_signal.primary_pull must be a food item, dish category, or cuisine — never a service behavior, staff name, or atmosphere descriptor. If recent evidence is mostly about service, still name the place's known food anchor from place_context (e.g. 'Korean BBQ', 'bingsu', 'pancakes'). Service signals belong in food_signal.summary only.",
            "food_signal.flavor_cue is required — write a 1-3 word taste or texture descriptor (e.g. 'crispy', 'spicy', 'grilled', 'rich broth', 'sweet and chewy'). If not explicit in evidence, infer from the cuisine type in place_context.",
            "Separate durable place identity from recent signal movement: if the place is known for crab but recent evidence is about service, say that clearly.",
            "If food-level evidence is thin, say so in food_signal.summary and lower food_signal.confidence.",
            "For food_signal.signal_dish: name the single most-mentioned specific dish or menu item found in evidence_chunks, using the exact name as it appears in reviews (e.g. 'Wang Tonkatsu', not just 'tonkatsu'). If no specific dish name appears in evidence, use empty string.",
            "For food_signal.image_query, write a short visual food query such as 'cajun seafood boil crab' or 'korean bbq grill'. Do not write a URL.",
            "Make card-level fields distinct: reader_hook should name the concrete dish, behavior, scene, or uncertainty; what_to_notice should not repeat the title; skeptic_note should state the main limitation calmly.",
            "If sentiment moved, describe it as a directional signal, not a review verdict.",
            "Use simple local wording like: recent mentions, repeated language, more attention than baseline, evidence is still developing.",
            "Do not say dining choices, expectations, demand, promotional activity, patrons, consumers, or customer experience.",
            "Never tell the reader what to do. Give the signal and let the reader decide.",
            "Prefer one modest sentence for why_this_matters.",
            "Do not use percentages unless they are explicitly present in computed metrics.",
            "Output valid JSON only.",
        ],
        "place": place,
        "candidate": {
            "id": signal["id"],
            "signal_type": signal["signal_type"],
            "score": signal["score"],
            "current_title": signal["title"],
            "current_summary": signal["summary"],
            "computed_metrics": signal.get("evidence") or {},
            "structured_metrics": signal.get("metrics") or [],
            "confidence_level": signal.get("confidence_level"),
            "confidence_score": signal.get("confidence_score"),
            "confidence_reason": signal.get("confidence_reason"),
        },
        "place_context": place_context or {"place_profile": None, "retrieved_place_documents": [], "food_facts": []},
        "evidence_chunks": evidence,
        "json_schema": _json_schema(),
    }
