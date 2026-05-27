import json
import os
import re
from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from localsignal_engine.llm_text import (
    BRIEFING_BANNED_WORDS,
    BRIEFING_SIGNALISH_PATTERNS,
    LlmEnrichmentError,
    _clean_json_value,
    _natural_join,
    _normalize_slug,
    _sanitize_banned_words,
    _truncate_sentence,
)


def generate_report_briefing(report_id: UUID, use_llm: Optional[bool] = None) -> dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for briefing generation.")

    should_use_llm = bool(os.getenv("OPENAI_API_KEY")) if use_llm is None else use_llm
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        metrics = _generate_report_briefing(conn, report_id, use_llm=should_use_llm)
        conn.commit()
        return metrics


def _report_signals(conn, report_id: UUID) -> list[dict]:
    return conn.execute(
        """
        SELECT
          s.id::text,
          s.slug,
          s.title,
          s.summary,
          s.signal_type,
          s.score::float,
          s.evidence,
          s.metrics,
          s.confidence_level,
          s.confidence_score::float,
          s.confidence_reason,
          json_build_object(
            'id', p.id,
            'name', p.name,
            'category', p.category,
            'address', p.address,
            'neighborhood', p.neighborhood,
            'city', p.city
          ) AS place
        FROM report_signals rs
        JOIN signals s ON s.id = rs.signal_id
        JOIN places p ON p.id = s.place_id
        WHERE rs.report_id = %s
        ORDER BY rs.rank ASC
        """,
        (report_id,),
    ).fetchall()


def _generate_report_briefing(conn, report_id: UUID, use_llm: bool = True) -> dict[str, Any]:
    report = conn.execute(
        """
        SELECT id::text, title, region, week_start::text AS week_start, intro
        FROM reports
        WHERE id = %s
        """,
        (report_id,),
    ).fetchone()
    if not report:
        return {"generated": False, "reason": "Report not found."}

    signals = _report_signals(conn, report_id)
    if not signals:
        return {"generated": False, "reason": "No report signals."}

    if not use_llm:
        briefing = _fallback_briefing(report, signals)
        _apply_report_briefing(conn, report_id, briefing)
        return {"generated": False, "fallback": True, "reason": "OPENAI_API_KEY is not configured."}

    errors: list[str] = []
    briefing = None
    for attempt in range(3):
        try:
            briefing = _generate_briefing_json(
                _briefing_prompt(report, signals, repair_note=errors[-1] if errors else None)
            )
            _validate_briefing(briefing, signals)
            break
        except LlmEnrichmentError as exc:
            errors.append(str(exc))
            briefing = None

    if briefing is None:
        briefing = _fallback_briefing(report, signals)
        _apply_report_briefing(conn, report_id, briefing)
        return {"generated": False, "fallback": True, "reason": "; retry: ".join(errors)}

    _apply_report_briefing(conn, report_id, briefing)
    return {"generated": True, "fallback": False}


def _briefing_prompt(report: dict, signals: list[dict], repair_note: Optional[str] = None) -> dict[str, Any]:
    instructions = [
        "You are LocalSignal's local editor for a consumer weekly briefing.",
        "Do not write a dashboard. Write one useful local story for a resident.",
        "Use only the supplied report signals. Do not invent places, dates, sources, openings, ratings, popularity, or posts.",
        "Pick one main story that expresses a local behavior or area-level change, not just a restaurant-level metric.",
        "Write from the reader's situation: what might someone want to eat, what visit occasion is forming, and what should they expect if they go.",
        "The main story must naturally cover the places_involved. If the supplied places do not share one tight category, write a broader local-rhythm title instead of forcing a cafe, dessert, or dinner theme.",
        "The title should usually be about people, streets, timing, occasions, or area behavior; avoid making the title only about one place.",
        "Good broader title example: 'A few ordinary food routines are shifting across Fort Lee'.",
        "Bad mismatch example: a cafe title while the places_involved are mostly restaurants.",
        "Prefer titles like 'People seem more willing to wait around River Road' or 'Dessert stops are starting to feel more central around Main Street'.",
        "Avoid titles like 'Wait-time talk is shifting at Don Coqui' or '<place> is seeing an unusual activity lift'.",
        "The why_it_matters field must have a point of view. It should explain what might be changing about how people use the area.",
        "Good why_it_matters example: 'If this keeps up, River Road may be becoming more of a dinner-and-hangout strip than a quick meal area.'",
        "Bad why_it_matters example: 'This is an early signal and not enough to hype yet.'",
        "Keep claims modest and reversible. If evidence is early, say it naturally without sounding like a system disclaimer.",
        "Mention places as examples driving the read, not as recommendations.",
        "Avoid internal words: confidence, source diversity, signal type, detection, anomaly, taxonomy, source count, repeated clue, baseline, activity, chatter, momentum.",
        "Avoid business and review-platform words: demand, popularity, customer, consumer, patrons, recommendation, market, engagement, experience, quality.",
        "Avoid vague lifestyle phrasing like 'diverse dining visits', 'restaurant atmospheres', or 'recent uptick in visits'.",
        "Prefer concrete food and occasion words: crab boil, spicy seafood, Korean BBQ, tofu, coffee, wifi, dessert, waits, lines, late dinner, group dinner, quiet weekday.",
        "Every place, source, and supporting read must reference one of the supplied signal slugs.",
        "If at least three signals are supplied, include exactly three places_involved from three different signal slugs.",
        "Supporting reads should sound like small local observations, not raw system objects.",
        "Do not reuse raw titles like 'Cafe use is changing at Kuppi Coffee Company' as supporting read titles.",
        "Better supporting read title: 'Weekday cafes may be getting quieter and more useful for focused visits'.",
        "For supporting_reads, make the title about a craving or occasion, not abstract movement.",
        "For places_involved.reason, explain the food pull or visit occasion in one reader-friendly sentence.",
        "Output valid JSON only.",
    ]
    if repair_note:
        instructions.append(f"The previous draft failed validation for this reason: {repair_note}. Rewrite to satisfy the validation.")
    return {
        "instructions": instructions,
        "report": report,
        "signals": [_briefing_signal_payload(signal) for signal in signals[:10]],
        "forbidden_public_terms": sorted(BRIEFING_BANNED_WORDS),
        "forbidden_title_patterns": sorted(BRIEFING_SIGNALISH_PATTERNS),
        "json_schema": _briefing_json_schema(),
    }


def _briefing_signal_payload(signal: dict) -> dict[str, Any]:
    evidence = signal.get("evidence") or {}
    place = signal.get("place") or {}
    return {
        "slug": signal.get("slug"),
        "title": signal.get("title"),
        "summary": signal.get("summary"),
        "signal_type": signal.get("signal_type"),
        "score": signal.get("score"),
        "place": {
            "name": place.get("name"),
            "category": place.get("category"),
            "city": place.get("city"),
            "neighborhood": place.get("neighborhood"),
        },
        "llm_fields": {
            "phenomenon_title": evidence.get("phenomenon_title"),
            "reader_hook": evidence.get("reader_hook"),
            "what_to_notice": evidence.get("what_to_notice"),
            "skeptic_note": evidence.get("skeptic_note"),
            "why_this_matters": signal.get("why_this_matters"),
            "best_read_as": evidence.get("best_read_as"),
        },
        "evidence": {
            "keywords": evidence.get("keywords", [])[:6],
            "sources": evidence.get("sources", []),
            "source_count": evidence.get("source_count"),
            "current_mention_count": evidence.get("current_mention_count") or evidence.get("mention_count"),
            "velocity_ratio": evidence.get("velocity_ratio"),
            "evidence_receipt": evidence.get("evidence_receipt") or {},
        },
    }


def _briefing_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "subtitle", "why_it_matters", "places_involved", "supporting_reads", "sources"],
        "properties": {
            "title": {"type": "string"},
            "subtitle": {"type": "string"},
            "why_it_matters": {"type": "string"},
            "places_involved": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "area", "category", "signal_slug", "reason"],
                    "properties": {
                        "name": {"type": "string"},
                        "area": {"type": "string"},
                        "category": {"type": "string"},
                        "signal_slug": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
            "supporting_reads": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "summary", "signal_slug"],
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "signal_slug": {"type": "string"},
                    },
                },
            },
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["label", "detail", "signal_slug"],
                    "properties": {
                        "label": {"type": "string"},
                        "detail": {"type": "string"},
                        "signal_slug": {"type": "string"},
                    },
                },
            },
        },
    }


def _generate_briefing_json(prompt: dict[str, Any]) -> dict[str, Any]:
    try:
        from openai import OpenAI, OpenAIError
    except ImportError as exc:
        raise LlmEnrichmentError("The openai package is not installed.") from exc

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=[
                {
                    "role": "system",
                    "content": "You are LocalSignal's local editor. Return JSON only.",
                },
                {"role": "user", "content": json.dumps(prompt, default=str)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "localsignal_weekly_briefing",
                    "schema": prompt["json_schema"],
                    "strict": True,
                }
            },
        )
    except OpenAIError as exc:
        raise LlmEnrichmentError(f"OpenAI briefing generation failed: {exc}") from exc

    try:
        return json.loads(response.output_text)
    except (AttributeError, json.JSONDecodeError) as exc:
        raise LlmEnrichmentError("OpenAI briefing did not return valid JSON.") from exc


def _validate_briefing(briefing: dict[str, Any], signals: list[dict]) -> None:
    _repair_briefing(briefing, signals)
    available_slugs = {signal.get("slug") for signal in signals if signal.get("slug")}
    if not briefing.get("title") or not briefing.get("subtitle") or not briefing.get("why_it_matters"):
        raise LlmEnrichmentError("Briefing is missing required narrative fields.")
    _validate_public_language(briefing)
    for section in ["places_involved", "supporting_reads", "sources"]:
        items = briefing.get(section) or []
        if not isinstance(items, list):
            raise LlmEnrichmentError(f"Briefing section {section} is not a list.")
        briefing[section] = [item for item in items if _normalize_slug(item.get("signal_slug")) in available_slugs]
    if len(signals) >= 3:
        place_slugs = {item.get("signal_slug") for item in briefing.get("places_involved") or []}
        if len(place_slugs) < 3:
            raise LlmEnrichmentError("Briefing did not include three distinct places.")

    for read in briefing.get("supporting_reads") or []:
        title = str(read.get("title") or "").lower()
        if any(pattern in title for pattern in BRIEFING_SIGNALISH_PATTERNS):
            raise LlmEnrichmentError("Briefing supporting reads reused signal-object wording.")


def _validate_public_language(briefing: dict[str, Any]) -> None:
    _sanitize_banned_words(briefing, list(BRIEFING_BANNED_WORDS))
    public_text = " ".join(
        [
            str(briefing.get("title") or ""),
            str(briefing.get("subtitle") or ""),
            str(briefing.get("why_it_matters") or ""),
            " ".join(str(item.get("reason") or "") for item in briefing.get("places_involved") or []),
            " ".join(str(item.get("title") or "") for item in briefing.get("supporting_reads") or []),
            " ".join(str(item.get("summary") or "") for item in briefing.get("supporting_reads") or []),
            " ".join(str(item.get("label") or "") for item in briefing.get("sources") or []),
            " ".join(str(item.get("detail") or "") for item in briefing.get("sources") or []),
        ]
    ).lower()
    hits = sorted(word for word in BRIEFING_BANNED_WORDS if word in public_text)
    if hits:
        _sanitize_banned_words(briefing, hits)

    title = str(briefing.get("title") or "")
    if len(title) > 95:
        raise LlmEnrichmentError("Briefing title is too long for the public page.")
    if len(str(briefing.get("subtitle") or "")) > 420:
        raise LlmEnrichmentError("Briefing subtitle is too long for the public page.")
    if len(str(briefing.get("why_it_matters") or "")) > 320:
        briefing["why_it_matters"] = _truncate_sentence(str(briefing.get("why_it_matters") or ""), 320)


def _repair_briefing(briefing: dict[str, Any], signals: list[dict]) -> None:
    available_slugs = {_normalize_slug(signal.get("slug")) for signal in signals if signal.get("slug")}
    signals_by_slug = {_normalize_slug(signal.get("slug")): signal for signal in signals if signal.get("slug")}
    for key, limit in [("title", 95), ("subtitle", 420), ("why_it_matters", 320)]:
        briefing[key] = _truncate_sentence(str(briefing.get(key) or ""), limit)

    for section in ["places_involved", "supporting_reads", "sources"]:
        items = briefing.get(section) or []
        repaired_items = []
        for item in items:
            slug = _normalize_slug(item.get("signal_slug"))
            if slug in available_slugs:
                item["signal_slug"] = slug
                if section == "places_involved":
                    item["name"] = _clean_briefing_place_name(item.get("name"), signals_by_slug.get(slug))
                repaired_items.append(item)
        briefing[section] = repaired_items

    if len(signals) >= 3:
        existing = {item.get("signal_slug") for item in briefing.get("places_involved") or []}
        for signal in signals:
            slug = _normalize_slug(signal.get("slug"))
            if not slug or slug in existing:
                continue
            briefing.setdefault("places_involved", []).append(
                {
                    "name": str((signal.get("place") or {}).get("name") or ""),
                    "area": _area_for_signal(signal),
                    "category": _briefing_topic(signal),
                    "signal_slug": slug,
                    "reason": _fallback_place_reason(signal),
                }
            )
            existing.add(slug)
            if len(existing) >= 3:
                break


def _clean_briefing_place_name(name: Any, signal: Optional[dict]) -> str:
    raw = re.sub(r"\s+", " ", str(name or "")).strip()
    if re.search(r"(?:\b[0-9a-fA-F]{2,4}\b\s*){2,}", raw) or re.search(r"\b[0-9a-fA-F]{6,}\b", raw):
        raw = str(((signal or {}).get("place") or {}).get("name") or raw)
    return re.sub(r"\s+", " ", raw).strip()


def _apply_report_briefing(conn, report_id: UUID, briefing: dict[str, Any]) -> None:
    conn.execute(
        """
        UPDATE reports
        SET briefing = %s::jsonb
        WHERE id = %s
        """,
        (Jsonb(_clean_json_value(briefing)), report_id),
    )


def _fallback_briefing(report: dict, signals: list[dict]) -> dict[str, Any]:
    main = signals[0]
    supporting = signals[1:4]
    title = _fallback_briefing_title(main, supporting)
    return {
        "title": title,
        "subtitle": _fallback_briefing_subtitle(main, supporting, report),
        "why_it_matters": _fallback_why_it_matters(main),
        "places_involved": [
            {
                "name": str((signal.get("place") or {}).get("name") or ""),
                "area": _area_for_signal(signal),
                "category": str((signal.get("place") or {}).get("category") or "food"),
                "signal_slug": str(signal.get("slug") or ""),
                "reason": _fallback_place_reason(signal),
            }
            for signal in signals[:3]
        ],
        "supporting_reads": [
            {
                "title": _fallback_supporting_title(signal),
                "summary": _fallback_supporting_summary(signal),
                "signal_slug": str(signal.get("slug") or ""),
            }
            for signal in supporting
        ],
        "sources": [
            {
                "label": str((signal.get("place") or {}).get("name") or ""),
                "detail": _source_detail(signal),
                "signal_slug": str(signal.get("slug") or ""),
            }
            for signal in signals[:6]
        ],
    }


def _area_for_signal(signal: dict) -> str:
    place = signal.get("place") or {}
    neighborhood = place.get("neighborhood")
    city = place.get("city")
    return f"{neighborhood}, {city}" if neighborhood and city and neighborhood != city else str(city or neighborhood or "Nearby")


def _fallback_briefing_title(main: dict, supporting: list[dict]) -> str:
    topics = {_briefing_topic(signal) for signal in [main, *supporting]}
    if len(topics) > 1:
        return "A few ordinary food routines are shifting across Fort Lee"
    area = _shared_area([main, *supporting]) or _area_for_signal(main)
    topic = _briefing_topic(main)
    if topic == "wait":
        return f"People seem more willing to wait around {area}"
    if topic == "late":
        return f"{area} is starting to feel more like an evening hangout"
    if topic == "dessert":
        return f"Dessert stops are getting harder to ignore around {area}"
    if topic == "cafe":
        return f"Cafe habits are becoming more visible around {area}"
    if topic == "dinner":
        return f"Dinner energy is picking up around {area}"
    return f"{area} has a few local food shifts worth watching"


def _fallback_briefing_subtitle(main: dict, supporting: list[dict], report: dict) -> str:
    places = [
        str((signal.get("place") or {}).get("name") or "")
        for signal in [main, *supporting]
        if (signal.get("place") or {}).get("name")
    ][:3]
    place_text = _natural_join(places)
    topic = _briefing_topic(main)
    if topic == "wait":
        summary = "Wait-time language is showing up alongside a few other small shifts in how people talk about nearby food stops."
    elif topic in {"cafe", "dessert"}:
        summary = "Cafe and casual-stop language is showing up alongside a few other small shifts in nearby food routines."
    else:
        summary = "This week's read is less about one standout place and more about several small changes in local food habits."
    return f"{summary} The places driving the read include {place_text}." if place_text else summary


def _fallback_why_it_matters(main: dict) -> str:
    area = _area_for_signal(main)
    topic = _briefing_topic(main)
    if topic == "wait":
        return f"If this keeps up, {area} may be becoming a place where people expect a slower dinner night instead of a quick stop."
    if topic == "late":
        return f"If this keeps up, {area} may be shifting from meal-only traffic toward more dinner-and-hangout behavior."
    if topic in {"dessert", "cafe"}:
        return f"If this keeps up, {area} may feel less dinner-only and more useful for casual stops after work or after dinner."
    return f"If this keeps up, {area} may be changing how locals decide where to spend an ordinary food night."


def _briefing_topic(signal: dict) -> str:
    evidence = signal.get("evidence") or {}
    text = " ".join(
        [
            str(signal.get("title") or ""),
            str(signal.get("summary") or ""),
            " ".join(str(keyword) for keyword in evidence.get("keywords", []) or []),
        ]
    ).lower()
    if any(term in text for term in ["wait", "line", "crowd", "crowded"]):
        return "wait"
    if any(term in text for term in ["late", "night", "music", "pocha"]):
        return "late"
    if any(term in text for term in ["dessert", "bakery", "cake", "pastry", "bingsu", "sweet"]):
        return "dessert"
    if any(term in text for term in ["coffee", "cafe", "latte", "matcha"]):
        return "cafe"
    if any(term in text for term in ["dinner", "bbq", "seafood", "wings", "pizza"]):
        return "dinner"
    return "food"


def _fallback_place_reason(signal: dict) -> str:
    topic = _briefing_topic(signal)
    place = (signal.get("place") or {}).get("name") or "This place"
    if topic == "wait":
        return f"Recent mentions point to a slower, more line-aware dinner pattern around {place}."
    if topic == "late":
        return f"Recent mentions make {place} feel more tied to evening routines than quick stops."
    if topic == "dessert":
        return f"Recent mentions make dessert or sweet-stop behavior more visible around {place}."
    if topic == "cafe":
        return f"Recent mentions describe {place} as quieter and more useful for weekday visits."
    if topic == "dinner":
        return f"Recent mentions make dinner traffic around {place} feel more active than usual."
    return f"Recent mentions around {place} are moving enough to make it worth watching this week."


def _fallback_supporting_title(signal: dict) -> str:
    area = _area_for_signal(signal)
    topic = _briefing_topic(signal)
    if topic == "wait":
        return f"Waits may be becoming part of the dinner plan near {area}"
    if topic == "late":
        return f"Evening visits are becoming easier to notice near {area}"
    if topic == "dessert":
        return f"Dessert stops are becoming more visible near {area}"
    if topic == "cafe":
        return f"Weekday cafe visits may be getting quieter near {area}"
    if topic == "dinner":
        return f"Dinner energy is becoming easier to notice near {area}"
    return f"A small local food habit is shifting near {area}"


def _fallback_supporting_summary(signal: dict) -> str:
    topic = _briefing_topic(signal)
    place = (signal.get("place") or {}).get("name") or "this place"
    if topic == "wait":
        return f"{place} is showing more language around lines and slower dinner pacing."
    if topic == "late":
        return f"{place} is showing more language tied to evening use and lingering visits."
    if topic == "dessert":
        return f"{place} is showing more language around sweet stops and casual visits."
    if topic == "cafe":
        return f"{place} is showing more language around quiet weekday cafe use."
    if topic == "dinner":
        return f"{place} is showing more language around dinner-time activity."
    return f"{place} is showing a small shift in how people describe nearby food routines."


def _shared_area(signals: list[dict]) -> str:
    areas = [_area_for_signal(signal) for signal in signals]
    neighborhoods = [area for area in areas if "," in area]
    if neighborhoods:
        first = neighborhoods[0]
        if sum(1 for area in neighborhoods if area == first) >= 2:
            return first.split(",", 1)[0]
    return ""


def _source_detail(signal: dict) -> str:
    evidence = signal.get("evidence") or {}
    mentions = evidence.get("current_mention_count") or evidence.get("mention_count")
    channels = evidence.get("source_count") or len(evidence.get("sources", []) or []) or 1
    return f"{mentions or 'Recent'} mention(s) across {channels} local channel(s), with claims limited to the retrieved evidence."
