import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional
from uuid import UUID

import psycopg
from localsignal_engine.db.connection import get_dict_conn

logger = logging.getLogger(__name__)
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
from localsignal_engine.llm_text import (
    BANNED_WORDS,
    LlmEnrichmentError,
    _clean_json_value,
    _clean_output,
    _dedupe,
    _sanitize_banned_words,
    openai_responses_call,
)
from localsignal_engine.llm_briefing import (
    _generate_report_briefing,
    _report_signals,
    generate_report_briefing,
)
from localsignal_engine.signal.prompt import _prompt, _safe_title
from localsignal_engine.signal.repair import (
    _food_pull_from_facts,
    _min_evidence_count,
    _min_source_diversity,
    _repair_food_signal,
    _repair_place_profile,
    _story_fields,
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
    skipped: list = []
    failed: list = []

    max_workers = int(os.getenv("LLM_ENRICH_MAX_WORKERS", "4"))

    with get_dict_conn() as conn:
        signals = _report_signals(conn, report_id)
        ensure_place_knowledge_schema(conn)

    # Each worker opens its own connection — psycopg connections are not thread-safe.
    outcomes: list[dict[str, str]] = _enrich_signals_concurrent(signals, max_workers)

    for outcome in outcomes:
        if outcome["status"] == "enriched":
            enriched += 1
        elif outcome["status"] == "skipped":
            skipped.append({"signal_id": outcome["signal_id"], "reason": outcome["reason"]})
        elif outcome["status"] == "failed":
            failed.append({"signal_id": outcome["signal_id"], "reason": outcome["reason"]})

    with get_dict_conn() as conn:
        briefing_metrics = _generate_report_briefing(conn, report_id)
        conn.commit()

    return {"enabled": True, "enriched": enriched, "skipped": skipped, "failed": failed, "briefing": briefing_metrics}


def _enrich_signals_concurrent(signals: list[dict], max_workers: int) -> list[dict[str, str]]:
    """Run _enrich_one_signal() for each signal in a thread pool.

    Each thread opens its own DB connection. Results are collected in
    submission order. Unexpected exceptions are caught per-signal.
    """
    if not signals:
        return []

    def _task(signal: dict) -> dict[str, str]:
        signal_id = signal["id"]
        place_name = (signal.get("place") or {}).get("name", signal_id)
        try:
            with get_dict_conn() as conn:
                outcome = _enrich_one_signal(conn, signal)
                conn.commit()
            return {**outcome, "signal_id": signal_id}
        except Exception as exc:
            logger.warning(
                "Unexpected error enriching signal %s (%s): %s",
                signal_id, place_name, exc, exc_info=True,
            )
            return {"status": "failed", "signal_id": signal_id, "reason": f"Unexpected: {exc}"}

    results: list[dict[str, str]] = [{}] * len(signals)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_idx = {pool.submit(_task, sig): i for i, sig in enumerate(signals)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                signal_id = signals[idx]["id"]
                logger.warning("Future for signal %s raised: %s", signal_id, exc)
                results[idx] = {"status": "failed", "signal_id": signal_id, "reason": str(exc)}
    return results


def _enrich_one_signal(conn, signal: dict) -> dict[str, str]:
    """Process a single signal. Returns {"status": "enriched"|"skipped"|"failed", "reason": str}.

    All exceptions propagate to the caller, which handles isolation.
    """
    signal_id = signal["id"]

    sync_existing_evidence_documents(conn, [signal["place"]["id"]], limit=200)

    reason = _gate_reason(signal)
    if reason:
        try:
            repaired = _apply_place_doc_profile_repair(conn, signal)
        except Exception as exc:
            logger.warning("place_doc repair failed for %s: %s", signal_id, exc)
            repaired = False
        if repaired:
            logger.info("Signal %s: thin evidence repaired via place_docs.", signal_id)
            return {"status": "enriched", "reason": ""}
        return {"status": "skipped", "reason": reason}

    evidence = _signal_evidence(conn, signal_id)
    if len(evidence) < _min_evidence_count():
        try:
            repaired = _apply_place_doc_profile_repair(conn, signal)
        except Exception as exc:
            logger.warning("place_doc repair failed for %s: %s", signal_id, exc)
            repaired = False
        if repaired:
            logger.info("Signal %s: low evidence repaired via place_docs.", signal_id)
            return {"status": "enriched", "reason": ""}
        return {"status": "skipped", "reason": f"Only {len(evidence)} evidence item(s)."}

    try:
        place_ctx = _place_context(conn, signal, evidence)
        result = _generate_signal_json(_prompt(signal, evidence, place_ctx))
        _validate_result(result, evidence)
        _apply_result(conn, signal, result, evidence, place_ctx)
        logger.info("Signal %s: LLM enrichment OK.", signal_id)
        return {"status": "enriched", "reason": ""}
    except LlmEnrichmentError as exc:
        logger.warning("Signal %s: LLM enrichment failed: %s", signal_id, exc)
        _apply_fallback(conn, signal)
        return {"status": "failed", "reason": str(exc)}


def _signal_evidence(conn, signal_id: str) -> list:
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


def _place_context(conn, signal: dict, evidence: list) -> dict[str, Any]:
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


def _generate_signal_json(prompt: dict[str, Any]) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": "You are LocalSignal's food intelligence analyst. Return JSON only."},
        {"role": "user", "content": json.dumps(prompt, default=str)},
    ]
    json_schema = {
        "name": "localsignal_weekly_signal_interpretation",
        "schema": prompt["json_schema"],
    }
    try:
        output = openai_responses_call(messages, json_schema=json_schema)
        return json.loads(output)
    except (json.JSONDecodeError, AttributeError) as exc:
        raise LlmEnrichmentError("OpenAI did not return valid JSON.") from exc


def _validate_result(result: dict[str, Any], evidence: list) -> None:
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


def _valid_evidence_ids(values: list, evidence: list) -> list:
    available = {row["id"] for row in evidence}
    valid = _dedupe([str(value) for value in values if str(value) in available])
    return valid or [row["id"] for row in evidence[:3]]


def _apply_result(conn, signal: dict, result: dict[str, Any], evidence: list, place_context: Optional[dict[str, Any]] = None) -> None:
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
