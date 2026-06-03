import logging
import os

import psycopg
from localsignal_engine.db.connection import get_conn, get_dict_conn
from psycopg.rows import dict_row

from localsignal_engine.baseline import compute_baseline_profiles
from localsignal_engine.db import (
    finish_ingestion_run,
    link_evidence_chunks_to_signals,
    load_places,
    load_recent_mentions,
    start_ingestion_run,
    write_mentions,
    write_raw_source_items_from_mentions,
    write_social_metadata_items,
    write_weekly_report,
)
from localsignal_engine.email.send import send_latest_digest
from localsignal_engine.ingestion.live import fetch_live_mentions, fetch_social_metadata_items
from localsignal_engine.signal.enrichment import enrich_report_signals_with_llm
from localsignal_engine.signal.scoring import generate_report_signals
from localsignal_engine.logging_config import configure_logging
from localsignal_engine.place import (
    build_place_profiles_from_briefs,
    build_restaurant_brief_documents,
    embed_place_documents,
    ingest_apify_google_reviews,
    ingest_google_place_documents,
    ingest_website_documents,
    sync_existing_evidence_documents,
)

logger = logging.getLogger(__name__)


def run_once() -> None:
    run_id = start_ingestion_run()
    source_counts: dict[str, int] = {}
    written_count = 0
    signals_generated = 0
    report_id = None

    places = load_places()
    try:
        social_items, social_source_counts = fetch_social_metadata_items(places)
        (
            social_raw_count,
            social_mentions_count,
            social_chunk_count,
            social_review_count,
            social_unresolved_count,
        ) = write_social_metadata_items(social_items)

        mentions, source_counts = fetch_live_mentions(places)
        source_counts = {**social_source_counts, **source_counts}
        written_count = write_mentions(mentions)
        raw_count, chunk_count = write_raw_source_items_from_mentions(mentions)

        if not mentions and _fallback_to_sample():
            raise RuntimeError("Sample fallback has been removed from the production weekly job.")

        model_mentions = load_recent_mentions(days=_current_window_days() + _baseline_window_days())
        signals = generate_report_signals(
            places=places,
            mentions=model_mentions,
            current_window_days=_current_window_days(),
            baseline_window_days=_baseline_window_days(),
        )
        signals_generated = len(signals)
        if not signals:
            raise RuntimeError("No signals generated from live ingestion.")

        report_id = write_weekly_report(signals)
        linked_count = link_evidence_chunks_to_signals()
        place_knowledge_metrics = (
            _refresh_place_knowledge(signals) if _place_knowledge_weekly_enabled() else {"enabled": False}
        )
        baseline_count = _compute_baselines(places)
        llm_metrics = enrich_report_signals_with_llm(report_id) if _llm_enrichment_enabled() else {"enabled": False}
        delivery_count = send_latest_digest() if _send_digest_enabled() else 0
        finish_ingestion_run(
            run_id=run_id,
            status="succeeded",
            source_counts=source_counts,
            live_mentions_written=written_count,
            signals_generated=signals_generated,
            report_id=report_id,
        )
        logger.info(
            "Wrote report %s: %d live mentions, %d raw items, %d chunks, "
            "%d social raw, %d social mentions, %d social chunks, "
            "%d review items, %d unresolved, %d evidence links, "
            "%d baselines updated; place_knowledge=%s llm=%s deliveries=%d",
            report_id, written_count, raw_count, chunk_count,
            social_raw_count, social_mentions_count, social_chunk_count,
            social_review_count, social_unresolved_count, linked_count,
            baseline_count, place_knowledge_metrics, llm_metrics, delivery_count,
        )
    except Exception as exc:
        finish_ingestion_run(
            run_id=run_id,
            status="failed",
            source_counts=source_counts,
            live_mentions_written=written_count,
            signals_generated=signals_generated,
            report_id=report_id,
            error=str(exc),
        )
        raise


def _fallback_to_sample() -> bool:
    return os.getenv("INGESTION_FALLBACK_TO_SAMPLE", "false").lower() == "true"


def _current_window_days() -> int:
    return int(os.getenv("ML_CURRENT_WINDOW_DAYS", "7"))


def _baseline_window_days() -> int:
    return int(os.getenv("ML_BASELINE_WINDOW_DAYS", "28"))


def _send_digest_enabled() -> bool:
    return os.getenv("SEND_DIGEST_ENABLED", "false").lower() == "true"


def _llm_enrichment_enabled() -> bool:
    return os.getenv("LLM_ENRICH_WEEKLY", "true").lower() == "true"


def _place_knowledge_weekly_enabled() -> bool:
    return os.getenv("PLACE_KNOWLEDGE_WEEKLY_ENABLED", "true").lower() == "true"


def _place_knowledge_apify_reviews_enabled() -> bool:
    return bool(os.getenv("APIFY_TOKEN")) and os.getenv("PLACE_KNOWLEDGE_APIFY_REVIEWS_ENABLED", "true").lower() == "true"


def _place_knowledge_google_enabled() -> bool:
    return os.getenv("PLACE_KNOWLEDGE_GOOGLE_ENABLED", "true").lower() == "true"


def _place_knowledge_website_enabled() -> bool:
    return os.getenv("PLACE_KNOWLEDGE_WEBSITE_ENABLED", "true").lower() == "true"


def _place_knowledge_embed_enabled() -> bool:
    return os.getenv("PLACE_KNOWLEDGE_EMBED_ENABLED", "true").lower() == "true"


def _refresh_place_knowledge(signals) -> dict:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return {"enabled": False, "reason": "missing_database_url"}
    place_ids = sorted({signal.place.id for signal in signals if signal.place and signal.place.id})
    if not place_ids:
        return {"enabled": True, "places": 0}

    metrics: dict[str, object] = {"enabled": True, "places": len(place_ids)}
    try:
        with get_dict_conn() as conn:
            metrics["evidence_documents"] = sync_existing_evidence_documents(conn, place_ids)
            if _place_knowledge_google_enabled():
                metrics["google_documents"] = ingest_google_place_documents(conn, place_ids)
            if _place_knowledge_apify_reviews_enabled():
                metrics["apify_review_documents"] = ingest_apify_google_reviews(conn, place_ids)
            if _place_knowledge_website_enabled():
                metrics["website_documents"] = ingest_website_documents(conn, place_ids)
            metrics["restaurant_brief_documents"] = build_restaurant_brief_documents(conn, place_ids)
            metrics["place_profiles_built"] = build_place_profiles_from_briefs(conn, place_ids)
            if _place_knowledge_embed_enabled():
                metrics["embedded_documents"] = embed_place_documents(conn, place_ids)
    except Exception as exc:
        metrics["error"] = str(exc)
    return metrics


def _compute_baselines(places) -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return 0
    with get_conn() as conn:
        return compute_baseline_profiles(conn, places)


def main() -> None:
    configure_logging()
    run_once()


if __name__ == "__main__":
    main()
