"""
Signal presenter helpers and pipeline utilities.

All private helper functions extracted from main.py live here so that router
modules stay thin and focused on HTTP concerns.
"""
import re
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from app.config import settings
from app.openai_pipeline import OpenAIPipelineError, embed_texts, vector_literal
from app.pipeline import build_llm_prompt, confidence_from_metrics, slugify


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    return slugify(value)


def _platform_label(source: str) -> str:
    labels = {
        "google_reviews": "Google Reviews",
        "google_places": "Google Reviews",
        "reddit": "Reddit",
        "rss": "Local web",
        "google_news": "Google News",
        "yelp": "Local listing",
    }
    return labels.get(source, source.replace("_", " ").title())


def _label_for(signal_type: str) -> str:
    labels = {
        "keyword_spike": "Keyword spike",
        "behavior_shift": "Behavior shift",
        "sentiment_shift": "Sentiment shift",
        "new_place_detected": "New place",
        "review_velocity_spike": "Rising fast",
    }
    return labels.get(signal_type, "Food signal")


# ---------------------------------------------------------------------------
# Signal scoring / classification
# ---------------------------------------------------------------------------


def _is_specific_signal_term(term: str) -> bool:
    if len(term) < 4:
        return False
    generic = {
        "good", "great", "amazing", "awesome", "nice", "service", "food",
        "place", "restaurant", "staff", "experience", "table", "atmosphere",
    }
    if term in generic:
        return False
    behavior_terms = {
        "wait", "line", "packed", "reservation", "sold out", "viral",
        "opening", "late night", "wifi", "remote", "outlet",
    }
    food_terms = {
        "bread", "pizza", "coffee", "chicken", "wings", "salt", "salty",
        "noodle", "tofu", "bbq", "sauce", "dessert", "matcha", "bakery",
        "brunch", "pancake", "vegetables", "mala", "malatang",
    }
    return term in behavior_terms or term in food_terms or any(food in term for food in food_terms)


def _signal_strength(row: dict) -> tuple[str, str]:
    evidence = row.get("evidence") or {}
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mentions = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    evidence_count = len(row.get("evidence_ids") or evidence.get("evidence_ids") or [])
    score = float(row.get("score") or 0)
    signal_type = str(row.get("signal_type") or "")
    keywords = [str(keyword).lower() for keyword in evidence.get("keywords", [])]
    specific_terms = sum(1 for keyword in keywords if _is_specific_signal_term(keyword))

    if score >= 70 and source_count >= 2 and mentions >= 2 and evidence_count >= 2:
        return (
            "Strong signal",
            f"Multiple source types and {evidence_count} linked evidence item(s) support this as a strong weekly signal.",
        )
    if mentions >= 2 and evidence_count >= 2 and (specific_terms >= 1 or signal_type in {"behavior_shift", "keyword_spike"}):
        return (
            "Watching",
            "Evidence is repeating, but source diversity is still limited; treat this as early movement, not a confirmed cross-platform signal.",
        )
    if mentions >= 2 and evidence_count >= 2:
        return (
            "Watching",
            "There is enough repetition to monitor, but the evidence is mostly from one source or uses broad review language.",
        )
    return (
        "Quiet",
        "The evidence is too thin for a strong signal, so this should stay in monitoring mode.",
    )


def _confidence(row: dict) -> str:
    evidence = row.get("evidence") or {}
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mentions = int(evidence.get("current_mention_count") or 0)
    spread = int(evidence.get("outside_region_count") or 0)
    if source_count >= 2 and mentions >= 3:
        return "High"
    if source_count >= 2 or mentions >= 2 or spread >= 1:
        return "Medium"
    return "Low"


def _confidence_reason(row: dict) -> str:
    evidence = row.get("evidence") or {}
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mentions = int(evidence.get("current_mention_count") or 0)
    spread = int(evidence.get("outside_region_count") or 0)
    confidence = _confidence(row)
    if confidence == "High":
        return f"High confidence because the signal repeats across {source_count} sources with {mentions} recent mentions."
    if confidence == "Medium":
        return f"Medium confidence because the signal has {mentions} recent mentions and {spread} outside-area signal(s), but evidence depth is still developing."
    return "Low confidence because the signal is based on limited repetition or source diversity."


# ---------------------------------------------------------------------------
# Metrics / tags / narrative
# ---------------------------------------------------------------------------


def _tags(row: dict) -> list[str]:
    evidence = row.get("evidence") or {}
    keywords = [str(keyword) for keyword in evidence.get("keywords", [])[:4]]
    llm_tags = [str(tag) for tag in evidence.get("llm_tags", [])[:4]]
    tags = [row["place"]["category"], _label_for(row["signal_type"]), *llm_tags, *keywords]
    seen: set[str] = set()
    return [tag for tag in tags if tag and not (tag.lower() in seen or seen.add(tag.lower()))]


def _metrics(row: dict) -> list[dict]:
    evidence = row.get("evidence") or {}
    keywords = evidence.get("keywords", [])
    velocity = evidence.get("velocity_ratio")
    source_count = evidence.get("source_count") or len(evidence.get("sources", []))
    spread = evidence.get("outside_region_count")
    current_mentions = evidence.get("current_mention_count")
    sentiment_delta = evidence.get("sentiment_delta")

    metrics = [
        {
            "label": "Keyword growth",
            "value": f"{len(keywords)} active terms" if keywords else "Emerging",
            "detail": ", ".join(keywords[:3]) if keywords else "New language is clustering around this signal.",
            "trend": "up",
        },
        {
            "label": "Mention velocity",
            "value": f"{float(velocity):.1f}x baseline" if velocity is not None else "Above baseline",
            "detail": "Compared with the recent baseline window.",
            "trend": "up",
        },
        {
            "label": "Source diversity",
            "value": f"{int(source_count)} source(s)" if source_count is not None else "Observed",
            "detail": "Signals are stronger when they appear across independent sources.",
            "trend": "steady",
        },
        {
            "label": "Location spread",
            "value": f"{int(spread)} outside area(s)" if spread is not None else row["city"],
            "detail": "Cross-neighborhood attention is treated as a momentum signal.",
            "trend": "up" if spread else "steady",
        },
    ]

    if current_mentions is not None:
        metrics.append(
            {
                "label": "Repeat mentions",
                "value": str(current_mentions),
                "detail": "Recent matched mentions in the current window.",
                "trend": "up" if int(current_mentions) > 1 else "steady",
            }
        )

    if sentiment_delta is not None:
        metrics.append(
            {
                "label": "Sentiment movement",
                "value": f"{float(sentiment_delta):+.2f}",
                "detail": "Directional change, not a star rating.",
                "trend": "down" if float(sentiment_delta) < 0 else "up",
            }
        )

    return metrics


def _momentum_driver(row: dict) -> str:
    evidence = row.get("evidence") or {}
    keywords = evidence.get("keywords", [])
    velocity = evidence.get("velocity_ratio")
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    spread = int(evidence.get("outside_region_count") or 0)
    place_name = row["place"]["name"]

    if row["signal_type"] == "behavior_shift":
        keyword_text = ", ".join(keywords[:2]) if keywords else "behavior-language"
        return f"Behavior shift around {keyword_text} across {source_count or 1} source(s)."
    if row["signal_type"] == "sentiment_shift":
        keyword_text = ", ".join(keywords[:2]) if keywords else "service language"
        return f"Sentiment movement tied to {keyword_text}."
    if spread:
        keyword_text = ", ".join(keywords[:2]) if keywords else "recent food-language"
        return f"Cross-neighborhood attention is forming around {keyword_text}."
    if source_count >= 3:
        keyword_text = ", ".join(keywords[:2]) if keywords else "recent food-language"
        return f"Evidence is appearing across {source_count} source types, led by {keyword_text}."
    if velocity is not None:
        if float(velocity) >= 5:
            return f"{place_name} is seeing an unusual lift across {mention_count or 'multiple'} recent mention(s)."
        return f"{place_name} is moving ahead of its recent baseline."
    keyword_text = ", ".join(keywords[:3]) if keywords else "new food-language"
    return f"New signal language is clustering around {keyword_text}."


def _evidence_assessment(row: dict) -> str:
    evidence = row.get("evidence") or {}
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    spread = int(evidence.get("outside_region_count") or 0)
    if source_count >= 2 and mention_count >= 3:
        return f"Strong support: {mention_count} recent mentions across {source_count} sources."
    if mention_count >= 2:
        return f"Developing support: {mention_count} recent mentions, with evidence still building."
    if spread:
        return "Early support: cross-area signal is present, but repetition is limited."
    return "Evidence coverage is still building for this signal."


def _what_changed(row: dict) -> list[str]:
    evidence = row.get("evidence") or {}
    if evidence.get("what_changed"):
        return [str(change) for change in evidence["what_changed"]]
    changes = [
        _momentum_driver(row),
        _evidence_assessment(row),
    ]
    keywords = evidence.get("keywords", [])
    if keywords:
        changes.append(f"Active language: {', '.join(keywords[:4])}.")
    if evidence.get("outside_region_count"):
        changes.append(f"Detected {int(evidence['outside_region_count'])} outside-area signal(s).")
    return changes


def _why_this_matters(row: dict) -> str:
    place_name = row["place"]["name"]
    signal_type = row["signal_type"]
    if signal_type == "behavior_shift":
        return (
            f"{place_name} is showing behavior change, which can indicate a place is becoming useful for a new occasion "
            "rather than simply receiving normal attention."
        )
    if signal_type == "sentiment_shift":
        return (
            f"{place_name} has a directional quality or service signal worth watching because momentum can change quickly "
            "when wait-time or service language repeats."
        )
    if signal_type == "review_velocity_spike":
        return (
            f"{place_name} is gaining attention faster than its recent baseline, suggesting the place may be moving from "
            "local familiarity toward broader food discovery."
        )
    return (
        f"{place_name} has new language clustering around it, which can be an early indicator of emerging demand or a "
        "specific item driving discovery."
    )


def _baseline_context(row: dict) -> dict:
    baseline = row.get("baseline_context") or {}
    evidence = row.get("evidence") or {}
    current_mentions = int(evidence.get("current_mention_count") or 0)
    trailing_30 = int(baseline.get("trailing_30d_mentions") or 0)
    delta = None
    if trailing_30:
        delta = f"{current_mentions} recent signal mention(s) vs {trailing_30} baseline item(s) in the last 30 days"
    elif current_mentions:
        delta = f"{current_mentions} recent signal mention(s) from a quiet baseline"
    return {
        "status": baseline.get("status") or "Quiet baseline",
        "heat_score": float(baseline.get("heat_score") or 0),
        "summary": baseline.get("summary") or "Baseline coverage is still building for this place.",
        "trailing_30d_mentions": trailing_30,
        "trailing_90d_mentions": int(baseline.get("trailing_90d_mentions") or 0),
        "trailing_365d_mentions": int(baseline.get("trailing_365d_mentions") or 0),
        "source_diversity": int(baseline.get("source_diversity") or 0),
        "recurring_keywords": baseline.get("recurring_keywords") or [],
        "delta_vs_baseline": delta,
    }


# ---------------------------------------------------------------------------
# Evidence item presentation
# ---------------------------------------------------------------------------


def _relevance_label(text: str, signal: dict) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ["line", "wait", "crowded"]):
        return "wait-time signal"
    if any(term in lowered for term in ["manhattan", "jersey city", "hoboken", "nyc"]):
        return "cross-neighborhood signal"
    if any(term in lowered for term in ["wifi", "remote", "outlet", "quiet"]):
        return "behavior shift signal"
    keywords = (signal.get("evidence") or {}).get("keywords", [])
    if keywords:
        return "keyword momentum signal"
    return "supporting mention"


def _evidence_item(row: dict, signal: dict) -> dict:
    geo_metadata = row.get("geo_metadata") or {}
    metadata = row.get("metadata") or {}
    if geo_metadata.get("region"):
        metadata = {**metadata, "region": geo_metadata["region"]}
    return {
        "platform": _platform_label(row["platform"]),
        "timestamp": row["timestamp"],
        "excerpt": row["excerpt"],
        "relevance": _relevance_label(row["excerpt"], signal),
        "metadata": metadata,
        "source_url": row.get("source_url"),
    }


# ---------------------------------------------------------------------------
# Profile / brief presentation
# ---------------------------------------------------------------------------


def _place_profile_from_row(row: dict) -> Optional[dict]:
    profile = row.get("place_profile")
    if not isinstance(profile, dict):
        return None

    known_for = str(profile.get("known_for") or "").strip()
    food_types = [item for item in profile.get("food_types", []) if item]
    signature_items = [item for item in profile.get("signature_items", []) if item]
    flavor_cues = [item for item in profile.get("flavor_cues", []) if item]
    occasions = [item for item in profile.get("occasions", []) if item]
    caveats = str(profile.get("caveats") or "").strip()
    source_count = int(profile.get("source_count") or 0)
    if not (known_for or food_types or signature_items or flavor_cues or occasions or caveats or source_count):
        return None

    return {
        "known_for": known_for,
        "food_types": food_types,
        "signature_items": signature_items,
        "flavor_cues": flavor_cues,
        "occasions": occasions,
        "caveats": caveats,
        "source_count": source_count,
        "profile": profile.get("profile") or {},
        "updated_at": profile.get("updated_at"),
    }


def _restaurant_brief(conn, place_id: str) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT metadata
        FROM place_documents
        WHERE place_id = %s
          AND content_type = 'restaurant_brief'
        ORDER BY fetched_at DESC
        LIMIT 1
        """,
        (place_id,),
    ).fetchone()
    metadata = row["metadata"] if row else None
    if not isinstance(metadata, dict) or not metadata.get("what_it_is"):
        return None
    return {
        "what_it_is": metadata.get("what_it_is") or "",
        "official_context_note": metadata.get("official_context_note") or "Official context, not signal evidence.",
        "signature_menu_items": metadata.get("signature_menu_items") or [],
        "highlight_items": metadata.get("highlight_items") or [],
        "location_format": metadata.get("location_format") or "",
        "vibe_tags": metadata.get("vibe_tags") or [],
        "occasions": metadata.get("occasions") or [],
        "source_chips": metadata.get("source_chips") or [],
        "trust_note": metadata.get("trust_note") or "Context only; recent movement is handled in the signal sections below.",
    }


# ---------------------------------------------------------------------------
# Signal row normalization
# ---------------------------------------------------------------------------


def _signal_row(row: dict) -> dict:
    """Normalize a raw DB row into the shape expected by SignalDTO / SignalDetailDTO.

    food_signal lives in its own DB column but is merged back into the evidence
    bag here so the frontend API contract stays unchanged.
    """
    normalized = {**row}
    evidence = {**(row.get("evidence") or {})}
    # Merge food_signal from its dedicated column back into evidence for API compat
    food_signal = row.get("food_signal")
    if food_signal and isinstance(food_signal, dict):
        evidence["food_signal"] = food_signal
    place_profile = _place_profile_from_row(row)
    if place_profile:
        evidence["place_profile"] = place_profile
    normalized["evidence"] = evidence
    normalized.pop("place_profile", None)
    normalized.pop("food_signal", None)
    return {
        **normalized,
        "slug": row.get("slug") or slugify(row["title"]),
        "momentum_driver": _momentum_driver(row),
        "evidence_assessment": _evidence_assessment(row),
        "confidence": row.get("confidence_level") or _confidence(row),
        "signal_strength": _signal_strength(row)[0],
        "signal_strength_reason": _signal_strength(row)[1],
    }


def _related_signal_row(row: dict) -> dict:
    place = row.get("place") or {}
    return {
        "slug": row.get("slug") or slugify(row["title"]),
        "title": row["title"],
        "place_name": row.get("place_name") or place.get("name"),
        "neighborhood": row.get("neighborhood") or place.get("neighborhood"),
        "signal_type": row["signal_type"],
        "score": row["score"],
    }


# ---------------------------------------------------------------------------
# Evidence retrieval (used by admin pipeline routes)
# ---------------------------------------------------------------------------


def _specific_signal_terms() -> set[str]:
    return {
        "line", "wait", "packed", "sold out", "worth the drive",
        "came from manhattan", "viral", "new menu", "opening", "soft opening",
        "reservation", "late night", "wifi", "remote", "outlet",
        "bread", "pizza", "coffee", "chicken", "wings", "salt", "salty",
        "noodle", "tofu", "bbq", "sauce", "dessert", "matcha", "bakery",
        "brunch", "pancake", "vegetables", "mala", "malatang",
    }


def _generic_review_terms() -> set[str]:
    return {"good", "great", "amazing", "awesome", "nice", "service", "food", "staff", "experience", "atmosphere"}


def _prompt_evidence_chunk(row: dict) -> dict:
    return {
        "id": row["id"],
        "platform": row["platform"],
        "source_url": row.get("source_url"),
        "timestamp": row["occurred_at"].isoformat(),
        "chunk_text": row["chunk_text"],
        "extracted_keywords": row.get("extracted_keywords") or [],
        "engagement_metrics": row.get("engagement_metrics") or {},
        "geo_metadata": row.get("geo_metadata") or {},
        "relevance_score": row["relevance_score"],
    }


def _rank_evidence_rows(rows: list[dict], keywords: list[str], limit: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    ranked = []
    for row in rows:
        text = (row.get("chunk_text") or "").lower()
        extracted = {str(keyword).lower() for keyword in row.get("extracted_keywords") or []}
        keyword_hits = sum(1 for keyword in keywords if keyword in text or keyword in extracted)
        specificity_hits = sum(1 for term in _specific_signal_terms() if term in text or term in extracted)
        generic_hits = sum(1 for term in _generic_review_terms() if term in text or term in extracted)
        occurred_at = row["occurred_at"]
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        age_days = max((now - occurred_at).days, 0)
        recency_boost = max(0, 1 - (age_days / 30)) * 0.1
        quality_boost = min(specificity_hits * 0.12, 0.36) + min(keyword_hits * 0.06, 0.24)
        generic_penalty = 0.08 if generic_hits and not specificity_hits else 0
        length_boost = 0.04 if len(text) >= 80 else 0
        score = float(row.get("semantic_score") or 0) + quality_boost + recency_boost + length_boost - generic_penalty
        ranked.append({**row, "relevance_score": round(max(score, 0), 4)})

    selected = []
    platform_counts: dict[str, int] = {}
    for row in sorted(ranked, key=lambda item: item["relevance_score"], reverse=True):
        platform = row.get("platform") or "unknown"
        if platform_counts.get(platform, 0) >= 3 and len(selected) < limit - 2:
            continue
        selected.append(row)
        platform_counts[platform] = platform_counts.get(platform, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def _ensure_chunk_embeddings(conn, chunks: list[dict]) -> None:
    missing = [chunk for chunk in chunks if not chunk.get("has_embedding")]
    if not missing:
        return
    embeddings = embed_texts([chunk["chunk_text"] for chunk in missing])
    for chunk, embedding in zip(missing, embeddings):
        conn.execute(
            "UPDATE evidence_chunks SET embedding = %s::vector WHERE id = %s",
            (vector_literal(embedding), chunk["id"]),
        )
    conn.commit()


def _candidate_time_window_days(candidate: dict) -> int:
    metrics = candidate.get("detected_metrics") or {}
    if metrics.get("current_window_days"):
        return int(metrics["current_window_days"])
    match = re.search(r"(\d+)", str(candidate.get("time_window") or ""))
    return int(match.group(1)) if match else 30


def _candidate_keywords(candidate: dict) -> list[str]:
    metrics = candidate.get("detected_metrics") or {}
    keywords = metrics.get("keywords") or []
    return [str(keyword).lower() for keyword in keywords if keyword][:10]


def _candidate_gate_reason(candidate: dict) -> Optional[str]:
    metrics = candidate.get("detected_metrics") or {}
    candidate_score = float(candidate.get("candidate_score") or 0)
    source_diversity = int(metrics.get("source_count") or len(metrics.get("sources", [])) or 0)

    if candidate_score < settings.signal_generate_min_candidate_score:
        return (
            f"Candidate score {candidate_score:.1f} is below "
            f"{settings.signal_generate_min_candidate_score:.1f}."
        )
    if source_diversity < settings.signal_generate_min_source_diversity:
        return (
            f"Source diversity {source_diversity} is below "
            f"{settings.signal_generate_min_source_diversity}."
        )
    return None


def _retrieve_candidate_evidence(conn, candidate: dict, limit: int = 10) -> list[dict]:
    metrics = candidate.get("detected_metrics") or {}
    days = _candidate_time_window_days(candidate)
    keywords = _candidate_keywords(candidate)
    candidate_id = candidate["id"]
    place_id = candidate["place_id"]

    chunks = conn.execute(
        """
        SELECT
          ec.id::text AS id,
          ec.chunk_text,
          ec.extracted_keywords,
          ec.occurred_at,
          ec.embedding IS NOT NULL AS has_embedding,
          rsi.platform,
          rsi.url AS source_url,
          rsi.engagement_metrics,
          rsi.geo_metadata
        FROM evidence_chunks ec
        JOIN raw_source_items rsi ON rsi.id = ec.raw_source_item_id
        WHERE ec.place_id = %s
          AND ec.occurred_at >= now() - (%s || ' days')::interval
        ORDER BY ec.occurred_at DESC
        LIMIT 80
        """,
        (place_id, days),
    ).fetchall()
    _ensure_chunk_embeddings(conn, chunks)

    query_text = " ".join(
        [
            str(candidate["place"].get("name") or ""),
            str(candidate["signal_type"]),
            str(candidate.get("trigger_reason") or ""),
            " ".join(keywords),
        ]
    ).strip()
    query_embedding = embed_texts([query_text])[0]
    semantic_rows = conn.execute(
        """
        SELECT
          ec.id::text AS id,
          ec.chunk_text,
          ec.extracted_keywords,
          ec.occurred_at,
          rsi.platform,
          rsi.url AS source_url,
          rsi.engagement_metrics,
          rsi.geo_metadata,
          1 - (ec.embedding <=> %s::vector) AS semantic_score
        FROM evidence_chunks ec
        JOIN raw_source_items rsi ON rsi.id = ec.raw_source_item_id
        WHERE ec.place_id = %s
          AND ec.embedding IS NOT NULL
          AND ec.occurred_at >= now() - (%s || ' days')::interval
        ORDER BY ec.embedding <=> %s::vector
        LIMIT 40
        """,
        (vector_literal(query_embedding), place_id, days, vector_literal(query_embedding)),
    ).fetchall()

    ranked = _rank_evidence_rows(semantic_rows, keywords, limit)
    if len(ranked) < 2:
        raise OpenAIPipelineError("Candidate has fewer than 2 retrievable evidence chunks.")
    conn.execute("DELETE FROM signal_candidate_evidence WHERE signal_candidate_id = %s", (candidate_id,))
    for rank, row in enumerate(ranked, start=1):
        conn.execute(
            """
            INSERT INTO signal_candidate_evidence (signal_candidate_id, evidence_chunk_id, relevance_score, rank)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (signal_candidate_id, evidence_chunk_id)
            DO UPDATE SET relevance_score = EXCLUDED.relevance_score, rank = EXCLUDED.rank
            """,
            (candidate_id, row["id"], row["relevance_score"], rank),
        )
    conn.commit()
    return [_prompt_evidence_chunk(row) for row in ranked]


def _current_signal_rows(conn) -> list[dict]:
    return conn.execute(
        """
        SELECT
          s.id,
          s.signal_type,
          s.title,
          s.summary,
          s.evidence,
          s.score::float AS score,
          s.time_window,
          json_build_object(
            'id', p.id,
            'name', p.name,
            'category', p.category,
            'city', p.city,
            'neighborhood', p.neighborhood
          ) AS place
        FROM signals s
        JOIN places p ON p.id = s.place_id
        WHERE s.status IN ('published', 'draft')
        ORDER BY s.week_start DESC, s.score DESC
        LIMIT 100
        """
    ).fetchall()


# ---------------------------------------------------------------------------
# Pipeline write helpers
# ---------------------------------------------------------------------------


def _supported_evidence_ids(ids: list[str], evidence_chunks: list[dict]) -> list[str]:
    available = {chunk["id"] for chunk in evidence_chunks}
    seen: set[str] = set()
    return [evidence_id for evidence_id in ids if evidence_id in available and not (evidence_id in seen or seen.add(evidence_id))]


def _record_pipeline_run(conn, step: str, status_value: str, metrics: dict, error: Optional[str] = None) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_runs (step, status, metrics, error, finished_at)
        VALUES (%s, %s, %s::jsonb, %s, now())
        """,
        (step, status_value, Jsonb(metrics), error),
    )
    conn.commit()


def _require_admin(token: Optional[str]) -> None:
    expected = settings.admin_token
    if expected and token != expected:
        raise HTTPException(status_code=403, detail="Admin token is required.")


def _passes_publish_checks(row: dict) -> bool:
    evidence = row.get("evidence") or {}
    metrics = row.get("metrics") or []
    source_count = int(evidence.get("source_count") or len(evidence.get("sources", [])) or 0)
    mention_count = int(evidence.get("current_mention_count") or evidence.get("mention_count") or 0)
    return bool(row.get("confidence_reason")) and bool(metrics) and source_count >= 1 and mention_count >= 2


def _write_generated_signal(conn, candidate: dict, llm_result: dict, evidence_chunks: list[dict]) -> UUID:
    """Insert a newly LLM-generated signal into the DB.

    food_signal is stored in its own dedicated column (split from the evidence
    bag) so it can be queried and indexed independently.
    """
    metrics = candidate.get("detected_metrics") or {}
    confidence_level, confidence_score, confidence_reason = confidence_from_metrics(metrics)
    confidence_reason = llm_result.get("confidence_reason") or confidence_reason
    evidence_ids = _supported_evidence_ids(llm_result.get("evidence_ids") or [], evidence_chunks)
    if not evidence_ids:
        evidence_ids = [chunk["id"] for chunk in evidence_chunks[:5]]
    evidence_uuid_ids = [UUID(evidence_id) for evidence_id in evidence_ids]
    place = candidate["place"]
    title = llm_result.get("phenomenon_title") or llm_result["title"]

    # food_signal lives in its own column — keep evidence bag clean
    food_signal = llm_result.get("food_signal") or {}
    evidence = {
        **metrics,
        "component_scores": candidate.get("component_scores") or {},
        "candidate_id": candidate["id"],
        "evidence_ids": evidence_ids,
        "llm_tags": llm_result.get("tags") or [],
        "what_changed": llm_result.get("what_changed") or [],
        "sources": sorted({chunk["platform"] for chunk in evidence_chunks}),
        "phenomenon_title": title,
        "food_or_cuisine_type": llm_result.get("food_or_cuisine_type"),
        "place_anchor_reason": llm_result.get("place_anchor_reason"),
        "reader_hook": llm_result.get("reader_hook"),
        "what_to_notice": llm_result.get("what_to_notice"),
        "skeptic_note": llm_result.get("skeptic_note"),
        "good_for": llm_result.get("good_for"),
        "watch_out": llm_result.get("watch_out"),
        "best_read_as": llm_result.get("best_read_as"),
        "evidence_receipt": llm_result.get("evidence_receipt") or {},
        "place_profile": llm_result.get("place_profile") or {},
    }
    row = conn.execute(
        """
        INSERT INTO signals (
          slug,
          place_id,
          signal_type,
          title,
          summary,
          short_summary,
          ai_summary,
          why_this_matters,
          confidence_level,
          confidence_score,
          confidence_reason,
          metrics,
          evidence_ids,
          status,
          time_window,
          evidence,
          food_signal,
          score,
          city,
          week_start
        )
        VALUES (
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s,
          %s::jsonb,
          %s,
          'draft',
          %s,
          %s::jsonb,
          %s::jsonb,
          %s,
          %s,
          date_trunc('week', now())::date
        )
        RETURNING id
        """,
        (
            slugify(f"{place.get('name', '')}-{title}"),
            candidate["place_id"],
            candidate["signal_type"],
            title,
            llm_result["short_summary"],
            llm_result["short_summary"],
            llm_result["ai_summary"],
            llm_result["why_this_matters"],
            confidence_level,
            confidence_score,
            confidence_reason,
            Jsonb(_metrics({"evidence": metrics, "city": place.get("city"), "place": place})),
            evidence_uuid_ids,
            candidate["time_window"],
            Jsonb(evidence),
            Jsonb(food_signal) if food_signal else None,
            candidate["candidate_score"],
            place.get("city") or "",
        ),
    ).fetchone()
    signal_id = row["id"]
    for rank, evidence_id in enumerate(evidence_ids, start=1):
        relevance = next((chunk["relevance_score"] for chunk in evidence_chunks if chunk["id"] == evidence_id), 0)
        conn.execute(
            """
            INSERT INTO signal_evidence (signal_id, evidence_chunk_id, relevance_score, rank)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (signal_id, evidence_chunk_id)
            DO UPDATE SET relevance_score = EXCLUDED.relevance_score, rank = EXCLUDED.rank
            """,
            (signal_id, evidence_id, relevance, rank),
        )
    conn.execute("UPDATE signal_candidates SET status = 'generated' WHERE id = %s", (candidate["id"],))
    conn.commit()
    return signal_id
