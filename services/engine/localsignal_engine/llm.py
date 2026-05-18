import json
import os
import re
from typing import Any
from typing import Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


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


def enrich_report_signals_with_llm(report_id: UUID) -> dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for LLM enrichment.")

    if not os.getenv("OPENAI_API_KEY"):
        briefing_metrics = generate_report_briefing(report_id, use_llm=False)
        return {
            "enabled": False,
            "enriched": 0,
            "skipped": [{"reason": "OPENAI_API_KEY is not configured."}],
            "briefing": briefing_metrics,
        }

    enriched = 0
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        signals = _report_signals(conn, report_id)
        for signal in signals:
            reason = _gate_reason(signal)
            if reason:
                skipped.append({"signal_id": signal["id"], "reason": reason})
                continue

            evidence = _signal_evidence(conn, signal["id"])
            if len(evidence) < _min_evidence_count():
                skipped.append({"signal_id": signal["id"], "reason": f"Only {len(evidence)} evidence item(s)."})
                continue

            try:
                result = _generate_signal_json(_prompt(signal, evidence))
                _validate_result(result, evidence)
                _apply_result(conn, signal, result, evidence)
                enriched += 1
            except LlmEnrichmentError as exc:
                _apply_fallback(conn, signal)
                failed.append({"signal_id": signal["id"], "reason": str(exc)})
        briefing_metrics = _generate_report_briefing(conn, report_id)
        conn.commit()

    return {"enabled": True, "enriched": enriched, "skipped": skipped, "failed": failed, "briefing": briefing_metrics}


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


def _signal_evidence(conn, signal_id: str) -> list[dict]:
    return conn.execute(
        """
        SELECT
          ec.id::text AS id,
          rsi.platform,
          rsi.url AS source_url,
          ec.occurred_at::text AS timestamp,
          ec.chunk_text,
          ec.extracted_keywords,
          rsi.engagement_metrics,
          rsi.geo_metadata,
          se.relevance_score::float
        FROM signal_evidence se
        JOIN evidence_chunks ec ON ec.id = se.evidence_chunk_id
        JOIN raw_source_items rsi ON rsi.id = ec.raw_source_item_id
        WHERE se.signal_id = %s
        ORDER BY se.rank ASC
        LIMIT 8
        """,
        (signal_id,),
    ).fetchall()


def _gate_reason(signal: dict) -> Optional[str]:
    evidence = signal.get("evidence") or {}
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    if source_count < _min_source_diversity():
        return f"Source diversity {source_count} is below {_min_source_diversity()}."
    if mention_count < _min_evidence_count():
        return f"Mention count {mention_count} is below {_min_evidence_count()}."
    return None


def _prompt(signal: dict, evidence: list[dict]) -> dict[str, Any]:
    return {
        "instructions": [
            "You generate calm analytical food signal interpretation for LocalSignal.",
            "Use only the provided metrics and evidence chunks.",
            "Do not invent sources, dates, ratings, engagement, popularity, or unsupported claims.",
            "Avoid Yelp-like wording such as best, top rated, must try, recommendation, or recommended.",
            "The product is a food signal, not a restaurant recommendation.",
            "Write for a local resident deciding what changed nearby, not for a business owner or market analyst.",
            "Avoid business strategy language such as market dynamics, business reputation, consumer perception, or decision making.",
            "The title must describe the food/local phenomenon first, not the restaurant first.",
            "Use the place as an anchor, not as the product. Avoid titles like '<place> has activity lift'.",
            "Keep the title specific, calm, and under 12 words. Do not use the word detected.",
            "Explain what changed in concrete terms: mention pace, repeated dishes/food terms, wait/crowd/lateness behavior, source diversity, or confidence.",
            "Also produce reader framing fields: reader_hook, what_to_notice, skeptic_note, good_for, watch_out, best_read_as, place_anchor_reason, food_or_cuisine_type, evidence_receipt.",
            "Make card-level fields distinct: reader_hook should name the concrete dish, behavior, scene, or uncertainty; what_to_notice should not repeat the title; skeptic_note should state the main limitation calmly.",
            "If sentiment moved, describe it as a directional signal, not a review verdict.",
            "Use simple local wording like: recent mentions, repeated language, more attention than baseline, evidence is still developing.",
            "Do not say dining choices, expectations, demand, promotional activity, patrons, consumers, or customer experience.",
            "Never tell the reader what to do. Give the signal and let the reader decide.",
            "Prefer one modest sentence for why_this_matters.",
            "Do not use percentages unless they are explicitly present in computed metrics.",
            "Output valid JSON only.",
        ],
        "place": signal["place"],
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
        "evidence_chunks": evidence,
        "json_schema": _json_schema(),
    }


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
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
    }


def _generate_signal_json(prompt: dict[str, Any]) -> dict[str, Any]:
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
                    "content": "You are LocalSignal's food intelligence analyst. Return JSON only.",
                },
                {"role": "user", "content": json.dumps(prompt, default=str)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "localsignal_weekly_signal_interpretation",
                    "schema": prompt["json_schema"],
                    "strict": True,
                }
            },
        )
    except OpenAIError as exc:
        raise LlmEnrichmentError(f"OpenAI generation failed: {exc}") from exc

    try:
        return json.loads(response.output_text)
    except (AttributeError, json.JSONDecodeError) as exc:
        raise LlmEnrichmentError("OpenAI did not return valid JSON.") from exc


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
    available_slugs = {signal.get("slug") for signal in signals if signal.get("slug")}
    if not briefing.get("title") or not briefing.get("subtitle") or not briefing.get("why_it_matters"):
        raise LlmEnrichmentError("Briefing is missing required narrative fields.")
    _validate_public_language(briefing)
    for section in ["places_involved", "supporting_reads", "sources"]:
        items = briefing.get(section) or []
        if not isinstance(items, list):
            raise LlmEnrichmentError(f"Briefing section {section} is not a list.")
        for item in items:
            if item.get("signal_slug") not in available_slugs:
                raise LlmEnrichmentError(f"Briefing section {section} referenced an unknown signal slug.")
    if len(signals) >= 3:
        place_slugs = {item.get("signal_slug") for item in briefing.get("places_involved") or []}
        if len(place_slugs) < 3:
            raise LlmEnrichmentError("Briefing did not include three distinct places.")

    for read in briefing.get("supporting_reads") or []:
        title = str(read.get("title") or "").lower()
        if any(pattern in title for pattern in BRIEFING_SIGNALISH_PATTERNS):
            raise LlmEnrichmentError("Briefing supporting reads reused signal-object wording.")


def _validate_public_language(briefing: dict[str, Any]) -> None:
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
        raise LlmEnrichmentError(f"Briefing used internal dashboard wording: {', '.join(hits[:3])}.")

    title = str(briefing.get("title") or "")
    if len(title) > 95:
        raise LlmEnrichmentError("Briefing title is too long for the public page.")
    if len(str(briefing.get("subtitle") or "")) > 420:
        raise LlmEnrichmentError("Briefing subtitle is too long for the public page.")
    if len(str(briefing.get("why_it_matters") or "")) > 320:
        raise LlmEnrichmentError("Briefing why_it_matters is too long for the public page.")


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


def _natural_join(values: list[str]) -> str:
    cleaned = [value for value in values if value]
    if len(cleaned) <= 1:
        return cleaned[0] if cleaned else ""
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _source_detail(signal: dict) -> str:
    evidence = signal.get("evidence") or {}
    mentions = evidence.get("current_mention_count") or evidence.get("mention_count")
    channels = evidence.get("source_count") or len(evidence.get("sources", []) or []) or 1
    return f"{mentions or 'Recent'} mention(s) across {channels} local channel(s), with claims limited to the retrieved evidence."


def _validate_result(result: dict[str, Any], evidence: list[dict]) -> None:
    text = " ".join(
        str(result.get(key, ""))
        for key in ["title", "short_summary", "ai_summary", "why_this_matters", "confidence_reason"]
    ).lower()
    banned_hits = sorted(word for word in BANNED_WORDS if word in text)
    if banned_hits:
        raise LlmEnrichmentError(f"LLM output used disallowed wording: {', '.join(banned_hits[:3])}.")

    evidence_ids = [str(evidence_id) for evidence_id in result.get("evidence_ids") or []]
    available = {row["id"] for row in evidence}
    if not evidence_ids:
        raise LlmEnrichmentError("LLM output did not cite evidence IDs.")
    if any(evidence_id not in available for evidence_id in evidence_ids):
        raise LlmEnrichmentError("LLM output cited evidence outside the retrieved set.")


def _apply_result(conn, signal: dict, result: dict[str, Any], evidence: list[dict]) -> None:
    evidence_ids = _dedupe([str(evidence_id) for evidence_id in result.get("evidence_ids") or []])
    evidence_json = {
        **(signal.get("evidence") or {}),
        "llm_enriched": True,
        "llm_model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "llm_tags": result.get("tags") or [],
        "what_changed": result.get("what_changed") or [],
        "phenomenon_title": result.get("phenomenon_title") or result.get("title"),
        "food_or_cuisine_type": result.get("food_or_cuisine_type"),
        "place_anchor_reason": result.get("place_anchor_reason"),
        "reader_hook": result.get("reader_hook"),
        "what_to_notice": result.get("what_to_notice"),
        "skeptic_note": result.get("skeptic_note"),
        "good_for": result.get("good_for"),
        "watch_out": result.get("watch_out"),
        "best_read_as": result.get("best_read_as"),
        "evidence_receipt": result.get("evidence_receipt") or {},
        "evidence_ids": evidence_ids,
    }
    conn.execute(
        """
        UPDATE signals
        SET
          title = %s,
          summary = %s,
          short_summary = %s,
          ai_summary = %s,
          why_this_matters = %s,
          confidence_reason = %s,
          evidence_ids = %s,
          evidence = %s::jsonb
        WHERE id = %s
        """,
        (
            _clean_output(result.get("phenomenon_title") or result["title"], fallback=signal["title"]),
            _clean_output(result["short_summary"], fallback=signal["summary"]),
            _clean_output(result["short_summary"], fallback=signal["summary"]),
            _clean_output(result["ai_summary"], fallback=signal["summary"]),
            _clean_output(result["why_this_matters"], fallback=signal.get("confidence_reason") or signal["summary"]),
            _clean_output(result["confidence_reason"], fallback=signal.get("confidence_reason") or ""),
            [UUID(evidence_id) for evidence_id in evidence_ids],
            Jsonb(_clean_json_value(evidence_json)),
            signal["id"],
        ),
    )



def _story_fields(signal: dict, keywords: list[str], evidence: dict) -> dict[str, Any]:
    place = signal["place"]
    place_name = place.get("name") or "This place"
    category = str(place.get("category") or "food").replace("_", " ").title()
    area = place.get("neighborhood") or place.get("city") or "nearby"
    title_topic, keyword_text = _story_topic(keywords, category)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    freshness = f"Last {evidence.get('current_window_days', 7)} days"
    if signal["signal_type"] == "sentiment_shift":
        phenomenon = f"Wait-time talk is shifting at {place_name}" if title_topic == "Wait-time" else f"{title_topic} tone is shifting at {place_name}"
    elif signal["signal_type"] == "review_velocity_spike":
        phenomenon = f"{title_topic} activity is picking up at {place_name}" if title_topic == category else f"{title_topic} keeps coming up at {place_name}"
    elif signal["signal_type"] == "behavior_shift":
        phenomenon = f"{title_topic} use is changing at {place_name}"
    else:
        phenomenon = f"{title_topic} is becoming the repeated clue at {place_name}"
    return {
        "phenomenon_title": phenomenon,
        "food_or_cuisine_type": category,
        "place_anchor_reason": f"{place_name} is the place where this signal is anchored; it is not a blanket recommendation.",
        "reader_hook": phenomenon,
        "what_to_notice": f"The useful read is the repeated language around {keyword_text}, not a best-of claim.",
        "skeptic_note": "Evidence is still narrow until it repeats across more independent sources.",
        "good_for": f"People tracking {keyword_text} movement near {area}.",
        "watch_out": "Evidence is movement-oriented and should not be read as a taste ranking.",
        "best_read_as": "A local food signal to notice, with judgment left to the reader.",
        "evidence_receipt": {
            "recent_mentions": str(mention_count or "Building"),
            "source_types": str(source_count or 1),
            "repeated_terms": keyword_text,
            "freshness": freshness,
            "evidence_read": signal.get("confidence_level") or "Medium",
        },
    }


def _story_topic(keywords: list[str], category: str) -> tuple[str, str]:
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


def _apply_fallback(conn, signal: dict) -> None:
    evidence = signal.get("evidence") or {}
    keywords = [str(keyword) for keyword in evidence.get("keywords", [])]
    keyword_text = ", ".join(keywords[:3]) if keywords else "recent food-language"
    place = signal["place"]
    place_name = place.get("name") or "This place"
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    velocity = evidence.get("velocity_ratio")

    story = _story_fields(signal, keywords, evidence)
    title = story["phenomenon_title"]
    if signal["signal_type"] == "sentiment_shift":
        summary = f"Recent language around {keyword_text} is moving differently from the short-term baseline."
        why = f"{place_name} is showing a directional shift in local food conversation, which is worth watching when it repeats across sources."
    elif signal["signal_type"] == "review_velocity_spike":
        velocity_text = f" at {float(velocity):.1f}x baseline" if velocity is not None else ""
        summary = f"Recent mentions are up{velocity_text}, led by language around {keyword_text}."
        why = f"{place_name} is receiving more recent attention than its baseline, suggesting a local food signal rather than a static listing."
    else:
        summary = f"New language is clustering around {keyword_text}."
        why = f"{place_name} has repeated local food language that may indicate emerging demand or a behavior shift."

    confidence_reason = (
        f"Confidence is based on {mention_count} recent mention(s) across {source_count} source type(s), "
        "with claims limited to the retrieved evidence."
    )
    evidence_json = {**evidence, **story, "llm_enriched": False, "llm_fallback_reason": "LLM output failed validation."}
    conn.execute(
        """
        UPDATE signals
        SET
          title = %s,
          summary = %s,
          short_summary = %s,
          ai_summary = %s,
          why_this_matters = %s,
          confidence_reason = %s,
          evidence = %s::jsonb
        WHERE id = %s
        """,
        (
            _clean_output(title, fallback=signal["title"]),
            _clean_output(summary, fallback=signal["summary"]),
            _clean_output(summary, fallback=signal["summary"]),
            _clean_output(summary, fallback=signal["summary"]),
            _clean_output(why, fallback=signal.get("confidence_reason") or signal["summary"]),
            _clean_output(confidence_reason, fallback=signal.get("confidence_reason") or ""),
            Jsonb(_clean_json_value(evidence_json)),
            signal["id"],
        ),
    )


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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    return [value for value in values if not (value in seen or seen.add(value))]


def _min_evidence_count() -> int:
    return int(os.getenv("LLM_ENRICH_MIN_EVIDENCE_COUNT", os.getenv("SIGNAL_GENERATE_MIN_EVIDENCE_COUNT", "2")))


def _min_source_diversity() -> int:
    return int(os.getenv("LLM_ENRICH_MIN_SOURCE_DIVERSITY", os.getenv("SIGNAL_GENERATE_MIN_SOURCE_DIVERSITY", "1")))
