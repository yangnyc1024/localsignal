import argparse
import os

import psycopg
from psycopg.rows import dict_row

from localsignal_engine.place_knowledge import (
    build_restaurant_brief_documents,
    embed_place_documents,
    ensure_place_knowledge_schema,
    ingest_google_place_documents,
    ingest_website_documents,
    sync_existing_evidence_documents,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build LocalSignal place knowledge documents.")
    parser.add_argument("--place-id", action="append", dest="place_ids", help="Limit work to one place id. Can be repeated.")
    parser.add_argument("--sync-evidence", action="store_true", help="Copy existing evidence chunks into place_documents.")
    parser.add_argument("--google", action="store_true", help="Fetch Google Places details and reviews into place_documents.")
    parser.add_argument("--website", action="store_true", help="Fetch website/menu pages discovered from Google Places metadata.")
    parser.add_argument("--restaurant-brief", action="store_true", help="Generate LLM restaurant brief documents using web search and official context.")
    parser.add_argument("--embed", action="store_true", help="Embed missing place_documents.")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required.")

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        ensure_place_knowledge_schema(conn)
        metrics = {"schema": "ok"}
        if args.sync_evidence:
            metrics["evidence_documents"] = sync_existing_evidence_documents(conn, args.place_ids)
        if args.google:
            metrics["google_documents"] = ingest_google_place_documents(conn, args.place_ids)
        if args.website:
            metrics["website_documents"] = ingest_website_documents(conn, args.place_ids)
        if args.restaurant_brief:
            metrics["restaurant_brief_documents"] = build_restaurant_brief_documents(conn, args.place_ids)
        if args.embed:
            metrics["embedded_documents"] = embed_place_documents(conn, args.place_ids)
        conn.commit()

    print(metrics, flush=True)


if __name__ == "__main__":
    main()
