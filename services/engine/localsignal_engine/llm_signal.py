import json
import os
from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from localsignal_engine.place_knowledge import (
    ensure_place_knowledge_schema,
    place_profile,
    retrieve_place_documents,
    sync_existing_evidence_documents,
    upsert_place_profile,
)
from localsignal_engine.llm_text import (
    BANNED_WORDS,
    LlmEnrichmentError,
    _clean_json_value,
    _clean_output,
    _clean_place_name,
    _dedupe,
    _sanitize_banned_words,
)
from localsignal_engine.llm_briefing import (
    _generate_report_briefing,
    _report_signals,
    generate_report_briefing,
)


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

            ensure_place_knowledge_schema(conn)
            sync_existing_evidence_documents(conn, [signal["place"]["id"]], limit=200)
            evidence = _signal_evidence(conn, signal["id"])
            if len(evidence) < _min_evidence_count():
                repaired = _apply_place_doc_profile_repair(conn, signal)
                skipped.append({"signal_id": signal["id"], "reason": f"Only {len(evidence)} evidence item(s)."})
                if repaired:
                    enriched += 1
                continue

            try:
                result = _generate_signal_json(_prompt(signal, evidence, _place_context(conn, signal, evidence)))
                _validate_result(result, evidence)
                _apply_result(conn, signal, result, evidence)
                enriched += 1
            except LlmEnrichmentError as exc:
                _apply_fallback(conn, signal)
                failed.append({"signal_id": signal["id"], "reason": str(exc)})
        briefing_metrics = _generate_report_briefing(conn, report_id)
        conn.commit()

    return {"enabled": True, "enriched": enriched, "skipped": skipped, "failed": failed, "briefing": briefing_metrics}


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


def _place_context(conn, signal: dict, evidence: list[dict]) -> dict[str, Any]:
    place = signal["place"]
    evidence_terms = " ".join(
        [
            str(signal.get("title") or ""),
            str(signal.get("summary") or ""),
            str((signal.get("evidence") or {}).get("keywords") or ""),
            " ".join(str(row.get("chunk_text") or "")[:240] for row in evidence[:4]),
        ]
    )
    query = f"{place.get('name')} {place.get('category')} menu food signature items flavor occasion {evidence_terms}"
    docs = retrieve_place_documents(conn, place["id"], query, limit=8)
    return {
        "place_profile": place_profile(conn, place["id"]),
        "retrieved_place_documents": docs,
    }


def _prompt(signal: dict, evidence: list[dict], place_context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
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
            "The title must describe the food/local phenomenon first, not the restaurant first.",
            "Use the place as an anchor, not as the product. Avoid titles like '<place> has activity lift'.",
            "Keep the title specific, calm, and under 12 words. Do not use the word detected.",
            "Explain what changed in concrete terms: mention pace, repeated dishes/food terms, wait/crowd/lateness behavior, source diversity, or confidence.",
            "Also produce reader framing fields: reader_hook, what_to_notice, skeptic_note, good_for, watch_out, best_read_as, place_anchor_reason, food_or_cuisine_type, evidence_receipt.",
            "Also produce place_profile and food_signal.",
            "place_profile describes the durable place identity from official_description, menu, place profile, and other stable context.",
            "food_signal describes what food, flavor, or occasion is pulling the current signal.",
            "Separate durable place identity from recent signal movement: if the place is known for crab but recent evidence is about service, say that clearly.",
            "If food-level evidence is thin, say so in food_signal.summary and lower food_signal.confidence.",
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
        "place_context": place_context or {"place_profile": None, "retrieved_place_documents": []},
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


def _validate_result(result: dict[str, Any], evidence: list[dict]) -> None:
    _sanitize_banned_words(result)
    text = " ".join(
        str(result.get(key, ""))
        for key in ["title", "short_summary", "ai_summary", "why_this_matters", "confidence_reason"]
    ).lower()
    banned_hits = sorted(word for word in BANNED_WORDS if word in text)
    if banned_hits:
        _sanitize_banned_words(result, banned_hits)

    evidence_ids = [str(evidence_id) for evidence_id in result.get("evidence_ids") or []]
    available = {row["id"] for row in evidence}
    if evidence_ids and not any(evidence_id in available for evidence_id in evidence_ids):
        result["evidence_ids"] = [row["id"] for row in evidence[:3]]
    elif evidence_ids:
        result["evidence_ids"] = [evidence_id for evidence_id in evidence_ids if evidence_id in available]
    else:
        result["evidence_ids"] = [row["id"] for row in evidence[:3]]


def _apply_result(conn, signal: dict, result: dict[str, Any], evidence: list[dict]) -> None:
    evidence_ids = _valid_evidence_ids(result.get("evidence_ids") or [], evidence)
    food_signal = _repair_food_signal(signal, result.get("food_signal") or {}, evidence)
    place_profile_data = _repair_place_profile(signal, result.get("place_profile") or {}, food_signal, evidence)
    evidence_json = {
        **(signal.get("evidence") or {}),
        "llm_enriched": True,
        "llm_model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "llm_tags": result.get("tags") or [],
        "what_changed": result.get("what_changed") or [],
        "phenomenon_title": result.get("phenomenon_title") or result.get("title"),
        "food_or_cuisine_type": result.get("food_or_cuisine_type"),
        "reader_hook": result.get("reader_hook"),
        "what_to_notice": result.get("what_to_notice"),
        "place_profile": place_profile_data,
        "food_signal": food_signal,
        "evidence_ids": evidence_ids,
    }
    if place_profile_data:
        upsert_place_profile(conn, signal["place"]["id"], place_profile_data)
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


def _apply_place_doc_profile_repair(conn, signal: dict) -> bool:
    evidence_json = dict(signal.get("evidence") or {})
    query = f"{signal['place'].get('name')} menu food signature items flavor occasion"
    docs = retrieve_place_documents(conn, signal["place"]["id"], query, limit=8)
    if not docs:
        return False
    pseudo_evidence = [
        {
            "id": row.get("id"),
            "chunk_text": row.get("content") or "",
            "platform": row.get("source") or row.get("content_type") or "place_document",
        }
        for row in docs
    ]
    food_signal = _repair_food_signal(signal, evidence_json.get("food_signal") or {}, pseudo_evidence)
    place_profile_data = _repair_place_profile(signal, evidence_json.get("place_profile") or {}, food_signal, pseudo_evidence)
    cleaned_evidence = {
        key: value
        for key, value in evidence_json.items()
        if key not in {"place_anchor_reason", "skeptic_note", "good_for", "watch_out", "best_read_as", "evidence_receipt"}
    }
    cleaned_evidence.update({"food_signal": food_signal, "place_profile": place_profile_data})
    upsert_place_profile(conn, signal["place"]["id"], place_profile_data)
    conn.execute(
        """
        UPDATE signals
        SET evidence = %s::jsonb
        WHERE id = %s
        """,
        (Jsonb(_clean_json_value(cleaned_evidence)), signal["id"]),
    )
    return True


def _story_fields(signal: dict, keywords: list[str], evidence: dict) -> dict[str, Any]:
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


def _valid_evidence_ids(values: list[str], evidence: list[dict]) -> list[str]:
    available = {row["id"] for row in evidence}
    valid = _dedupe([str(value) for value in values if str(value) in available])
    return valid or [row["id"] for row in evidence[:3]]


def _repair_food_signal(signal: dict, food_signal: dict[str, Any], evidence: list[dict]) -> dict[str, Any]:
    repaired = dict(food_signal or {})
    primary = str(repaired.get("primary_pull") or "").strip()
    if primary and primary.lower() not in {"restaurant", "food", "local food", "place", "general food"}:
        return repaired

    text = " ".join(
        [
            signal.get("place", {}).get("name") or "",
            signal.get("place", {}).get("category") or "",
            signal.get("title") or "",
            signal.get("summary") or "",
            " ".join(str(row.get("chunk_text") or "") for row in evidence[:8]),
        ]
    ).lower()
    pull = _food_pull_from_text(text)
    if not pull:
        return repaired

    repaired["primary_pull"] = pull["primary_pull"]
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


def _repair_place_profile(signal: dict, profile: dict[str, Any], food_signal: dict[str, Any], evidence: list[dict]) -> dict[str, Any]:
    repaired = dict(profile or {})
    place_name = str((signal.get("place") or {}).get("name") or "This place").strip()
    place_short = _clean_place_name(place_name)
    category = str((signal.get("place") or {}).get("category") or "local food").replace("_", " ").strip()
    evidence_text = " ".join(str(row.get("chunk_text") or "") for row in evidence[:8])
    text = " ".join(
        [
            place_name,
            category,
            signal.get("title") or "",
            signal.get("summary") or "",
            evidence_text,
            " ".join(str(item) for item in (signal.get("evidence") or {}).get("keywords", []) or []),
        ]
    ).lower()
    pull = _food_pull_from_text(text)
    primary_pull = str(food_signal.get("primary_pull") or (pull or {}).get("primary_pull") or "").strip()
    flavor = str(food_signal.get("flavor_cue") or (pull or {}).get("flavor_cue") or "").strip()
    occasion = str(food_signal.get("occasion") or (pull or {}).get("occasion") or "").strip()

    known_for = str(repaired.get("known_for") or "").strip()
    if _weak_profile_text(known_for):
        known_for = _known_for_from_context(place_short, primary_pull, flavor, text, category)
    repaired["known_for"] = known_for

    food_types = _profile_string_list(repaired.get("food_types"))
    if _weak_profile_list(food_types):
        food_types = [primary_pull or category.title()]
    repaired["food_types"] = _dedupe(food_types)

    signature_items = _profile_string_list(repaired.get("signature_items"))
    signature_items = _dedupe(signature_items + _signature_items_from_context(text, primary_pull))
    repaired["signature_items"] = signature_items[:5]

    flavor_cues = _profile_string_list(repaired.get("flavor_cues"))
    if flavor:
        flavor_cues.append(flavor)
    flavor_cues.extend(_flavor_cues_from_context(text))
    repaired["flavor_cues"] = _dedupe(flavor_cues)[:4]

    occasions = _profile_string_list(repaired.get("occasions"))
    if occasion:
        occasions.append(occasion)
    occasions.extend(_occasions_from_context(text))
    repaired["occasions"] = _dedupe(occasions)[:4]

    source_count = int(repaired.get("source_count") or 0)
    repaired["source_count"] = max(source_count, len([row for row in evidence if row.get("chunk_text")]) or 1)
    repaired["caveats"] = str(repaired.get("caveats") or "").strip()
    if _weak_profile_text(repaired["caveats"]):
        repaired["caveats"] = "Profile is based on retrieved place context and current evidence; keep claims limited to those sources."
    return repaired


def _weak_profile_text(value: str) -> bool:
    text = _clean_place_name(str(value or "")).lower()
    return (
        not text
        or "tracked as restaurant" in text
        or "limited signal evidence" in text
        or text in {"restaurant", "food", "local food"}
    )


def _weak_profile_list(values: list[str]) -> bool:
    cleaned = [str(value).strip().lower() for value in values if str(value).strip()]
    return not cleaned or all(value in {"restaurant", "food", "local food"} for value in cleaned)


def _profile_string_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _known_for_from_context(place: str, primary_pull: str, flavor: str, text: str, category: str) -> str:
    if "samhap" in text or "삼합" in text or "jumulleok" in text or "주물럭" in text or primary_pull.lower() == "korean bbq":
        return f"{place} reads as a Korean grill spot with BBQ-style meats, shared table cooking, and Korean side dishes."
    if primary_pull:
        detail = f" with {flavor}" if flavor else ""
        return f"{place} reads as a {primary_pull} place{detail}."
    return f"{place} reads as a {category.lower()} place."


def _signature_items_from_context(text: str, primary_pull: str) -> list[str]:
    items: list[str] = []
    if primary_pull:
        items.append(primary_pull)
    patterns = [
        ("samhap", ["samhap", "sam hop", "samhop", "삼합"]),
        ("jumulleok", ["jumulleok", "주물럭"]),
        ("gopchang jjigae", ["gopchang", "곱창"]),
        ("ojingeo-samgyeopsal", ["오삼", "ojingeo"]),
        ("tteokbokki", ["떡볶이", "tteokbokki"]),
        ("corn cheese", ["콘치즈", "corn cheese"]),
        ("mussels", ["홍합", "mussel"]),
    ]
    for label, terms in patterns:
        if any(term in text for term in terms):
            items.append(label)
    return items


def _flavor_cues_from_context(text: str) -> list[str]:
    cues: list[str] = []
    if any(term in text for term in ["grill", "bbq", "고기", "구워", "삼겹"]):
        cues.append("grilled meat")
    if any(term in text for term in ["김치", "kimchi", "반찬", "banchan"]):
        cues.append("kimchi / banchan")
    if any(term in text for term in ["찌개", "jjigae", "stew"]):
        cues.append("stew / jjigae")
    return cues


def _occasions_from_context(text: str) -> list[str]:
    occasions: list[str] = []
    if any(term in text for term in ["group", "회식", "모임", "friends", "family", "parents"]):
        occasions.append("group dinner")
    if any(term in text for term in ["alcohol", "soju", "drink", "술"]):
        occasions.append("dinner with drinks")
    return occasions


def _food_pull_from_text(text: str) -> Optional[dict[str, str]]:
    if any(term in text for term in ["seafood boil", "cajun", "crab", "shrimp", "clams"]):
        return {
            "primary_pull": "seafood boil",
            "flavor_cue": "fresh seafood / sauce",
            "occasion": "group dinner",
            "image_query": "cajun seafood boil crab shrimp",
            "image_alt": "Cajun seafood boil with crab and shrimp",
            "basis": "Evidence mentions crab, shrimp, clams, fresh seafood, sauce, and shared trays.",
        }
    if any(term in text for term in ["doner", "döner", "kebab", "gyro", "shawarma"]):
        return {
            "primary_pull": "doner / kebab",
            "flavor_cue": "grilled meat / street-food format",
            "occasion": "quick meal",
            "image_query": "doner kebab wrap",
            "image_alt": "Doner kebab wrap",
            "basis": "Place context points to doner and kebab-style food.",
        }
    if any(term in text for term in ["korean bbq", "bbq", "grill", "ayce", "삼합", "주물럭", "고기", "구워", "samhap", "samhop"]):
        return {
            "primary_pull": "Korean BBQ",
            "flavor_cue": "grilled meat",
            "occasion": "group dinner",
            "image_query": "korean bbq grill",
            "image_alt": "Korean BBQ grill",
            "basis": "Place context points to Korean BBQ and grill language.",
        }
    if any(term in text for term in ["donkatsu", "tonkatsu", "pork cutlet"]):
        return {
            "primary_pull": "donkatsu",
            "flavor_cue": "crispy cutlet",
            "occasion": "casual meal",
            "image_query": "donkatsu pork cutlet",
            "image_alt": "Donkatsu pork cutlet",
            "basis": "Place context points to donkatsu and cutlet language.",
        }
    return None


def _min_evidence_count() -> int:
    return int(os.getenv("LLM_ENRICH_MIN_EVIDENCE_COUNT", os.getenv("SIGNAL_GENERATE_MIN_EVIDENCE_COUNT", "2")))


def _min_source_diversity() -> int:
    return int(os.getenv("LLM_ENRICH_MIN_SOURCE_DIVERSITY", os.getenv("SIGNAL_GENERATE_MIN_SOURCE_DIVERSITY", "1")))
