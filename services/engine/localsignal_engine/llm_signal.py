import json
import os
from typing import Any, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from localsignal_engine.place_knowledge import (
    ensure_place_knowledge_schema,
    get_place_food_facts,
    merge_place_profile,
    place_profile,
    retrieve_place_documents,
    sync_existing_evidence_documents,
    upsert_place_profile,
)
import re

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
                if repaired:
                    enriched += 1
                else:
                    skipped.append({"signal_id": signal["id"], "reason": f"Only {len(evidence)} evidence item(s)."})
                continue

            try:
                place_ctx = _place_context(conn, signal, evidence)
                result = _generate_signal_json(_prompt(signal, evidence, place_ctx))
                _validate_result(result, evidence)
                _apply_result(conn, signal, result, evidence, place_ctx)
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
    food_facts = get_place_food_facts(conn, place["id"])
    return {
        "place_profile": place_profile(conn, place["id"]),
        "retrieved_place_documents": docs,
        "food_facts": food_facts,
    }


def _latin_place_name(name: str) -> str:
    """Return the Latin/ASCII portion of a place name, stripping CJK characters."""
    # Strip CJK (Korean, Chinese, Japanese) characters
    latin = re.sub(r"[ᄀ-ᇿ㄰-㆏가-힯一-鿿぀-ヿ＀-￯]+", "", name)
    # If result is wrapped in parens (e.g. "(Chungchoon Sikdang)"), unwrap
    latin = re.sub(r"^\s*\(\s*(.*?)\s*\)\s*$", r"\1", latin.strip())
    latin = re.sub(r"\s+", " ", latin).strip()
    return latin or name


def _safe_title(value: str, fallback: str) -> str:
    """Clean LLM title output and reject garbled hex/encoding artifacts."""
    cleaned = _clean_output(value, fallback)
    # Reject if contains hex-like garbage (e.g. '0a8c0b0b3c8ae4cc2a4')
    if re.search(r"\b[0-9a-fA-F]{8,}\b", cleaned):
        return fallback
    return cleaned


def _prompt(signal: dict, evidence: list[dict], place_context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
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


def _apply_result(conn, signal: dict, result: dict[str, Any], evidence: list[dict], place_context: Optional[dict[str, Any]] = None) -> None:
    evidence_ids = _valid_evidence_ids(result.get("evidence_ids") or [], evidence)
    food_signal = _repair_food_signal(signal, result.get("food_signal") or {}, evidence, place_context)
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
        merge_place_profile(conn, signal["place"]["id"], place_profile_data)
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
            _safe_title(result.get("phenomenon_title") or result["title"], fallback=signal["title"]),
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
    food_facts = get_place_food_facts(conn, signal["place"]["id"])
    place_ctx = {"food_facts": food_facts, "retrieved_place_documents": docs}
    if not docs and not food_facts:
        return False
    pseudo_evidence = [
        {
            "id": row.get("id"),
            "chunk_text": row.get("content") or "",
            "platform": row.get("source") or row.get("content_type") or "place_document",
        }
        for row in docs
    ]
    food_signal = _repair_food_signal(signal, evidence_json.get("food_signal") or {}, pseudo_evidence, place_ctx)
    place_profile_data = _repair_place_profile(signal, evidence_json.get("place_profile") or {}, food_signal, pseudo_evidence)
    cleaned_evidence = {
        key: value
        for key, value in evidence_json.items()
        if key not in {"place_anchor_reason", "skeptic_note", "good_for", "watch_out", "best_read_as", "evidence_receipt"}
    }
    cleaned_evidence.update({"food_signal": food_signal, "place_profile": place_profile_data})
    merge_place_profile(conn, signal["place"]["id"], place_profile_data)
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


def _repair_food_signal(signal: dict, food_signal: dict[str, Any], evidence: list[dict], place_context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    repaired = dict(food_signal or {})
    primary = str(repaired.get("primary_pull") or "").strip()
    if primary and primary.lower() not in {"restaurant", "food", "local food", "place", "general food"}:
        return repaired

    # Use persisted food facts as the repair source — LLM-extracted, no keyword matching
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


def _repair_place_profile(signal: dict, profile: dict[str, Any], food_signal: dict[str, Any], evidence: list[dict]) -> dict[str, Any]:
    """Sanitise the LLM-generated place_profile dict.

    No rule-based keyword extraction — trust the LLM output and only fill in
    missing fields from food_signal (which is itself LLM-generated).
    """
    repaired = dict(profile or {})

    # Carry food_signal fields into profile where missing
    primary_pull = str(food_signal.get("primary_pull") or "").strip()
    flavor = str(food_signal.get("flavor_cue") or "").strip()
    occasion = str(food_signal.get("occasion") or "").strip()

    if not str(repaired.get("known_for") or "").strip():
        place_name = _clean_place_name(str((signal.get("place") or {}).get("name") or "This place"))
        repaired["known_for"] = f"{place_name} — profile pending next brief refresh." if not primary_pull else f"{place_name} is a {primary_pull} place."

    # Only keep food_types that look like short cuisine labels, not sentences
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


def _profile_string_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _food_pull_from_facts(facts: list[dict]) -> Optional[dict[str, str]]:
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


def _min_evidence_count() -> int:
    return int(os.getenv("LLM_ENRICH_MIN_EVIDENCE_COUNT", os.getenv("SIGNAL_GENERATE_MIN_EVIDENCE_COUNT", "2")))


def _min_source_diversity() -> int:
    return int(os.getenv("LLM_ENRICH_MIN_SOURCE_DIVERSITY", os.getenv("SIGNAL_GENERATE_MIN_SOURCE_DIVERSITY", "1")))
