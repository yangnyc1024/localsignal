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


def main() -> None:
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
    print(
        "Fetched "
        f"{len(mentions)} mentions from {source_counts}; "
        f"stored {mention_count} new mentions, {raw_count} raw source items, "
        f"{chunk_count} evidence chunks, {linked_count} signal-evidence links, "
        f"imported {social_raw_count} social raw items, {social_mention_count} social mentions, "
        f"{social_chunk_count} social evidence chunks, {social_review_count} social review items, "
        f"{social_unresolved_count} unresolved social items, "
        f"and updated {baseline_count} baseline profiles."
    )


if __name__ == "__main__":
    main()
