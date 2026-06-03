import logging
from localsignal_engine.logging_config import configure_logging
from localsignal_engine.db import (
    link_evidence_chunks_to_signals,
    load_places,
    write_mentions,
    write_raw_source_items_from_mentions,
    write_social_metadata_items,
)
from localsignal_engine.baseline import compute_baseline_profiles
import os
import psycopg
from localsignal_engine.db.connection import get_conn
from localsignal_engine.ingestion.live import fetch_live_mentions, fetch_social_metadata_items

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    places = load_places()
    social_items, social_source_counts = fetch_social_metadata_items(places)
    social_raw_count, social_mention_count, social_chunk_count, social_review_count, social_unresolved_count = (
        write_social_metadata_items(social_items)
    )
    mentions, source_counts = fetch_live_mentions(places)
    source_counts = {**social_source_counts, **source_counts}
    mention_count = write_mentions(mentions)
    raw_count, chunk_count = write_raw_source_items_from_mentions(mentions)
    linked_count = link_evidence_chunks_to_signals()
    database_url = os.getenv("DATABASE_URL")
    baseline_count = 0
    if database_url:
        with get_conn() as conn:
            baseline_count = compute_baseline_profiles(conn, places)
    logger.info(
        "Fetched %d mentions from %s; stored %d new mentions, %d raw source items, "
        "%d evidence chunks, %d signal-evidence links, "
        "imported %d social raw items, %d social mentions, "
        "%d social evidence chunks, %d social review items, "
        "%d unresolved social items, and updated %d baseline profiles.",
        len(mentions), source_counts, mention_count, raw_count,
        chunk_count, linked_count,
        social_raw_count, social_mention_count,
        social_chunk_count, social_review_count,
        social_unresolved_count, baseline_count,
    )


if __name__ == "__main__":
    main()
