import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any, Optional

from psycopg.types.json import Jsonb


DOCUMENT_MIN_CHARS = 80
EMBEDDING_MODEL = "text-embedding-3-small"
RESTAURANT_BRIEF_SOURCE = "localsignal_restaurant_brief"


def ensure_place_knowledge_schema(conn) -> None:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS place_documents (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
          source TEXT NOT NULL,
          source_url TEXT,
          title TEXT NOT NULL DEFAULT '',
          content TEXT NOT NULL,
          content_type TEXT NOT NULL,
          occurred_at TIMESTAMPTZ,
          fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          embedding vector(1536),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS place_profiles (
          place_id UUID PRIMARY KEY REFERENCES places(id) ON DELETE CASCADE,
          known_for TEXT NOT NULL DEFAULT '',
          food_types TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          signature_items TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          flavor_cues TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          occasions TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
          caveats TEXT NOT NULL DEFAULT '',
          source_count INTEGER NOT NULL DEFAULT 0,
          profile JSONB NOT NULL DEFAULT '{}'::jsonb,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_place_documents_place_type ON place_documents(place_id, content_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_place_documents_place_fetched ON place_documents(place_id, fetched_at DESC)")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_place_documents_embedding_hnsw
        ON place_documents USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_place_documents_unique_source
        ON place_documents(place_id, source, source_url, content_type)
        WHERE source_url IS NOT NULL
        """
    )


def sync_existing_evidence_documents(conn, place_ids: Optional[list[str]] = None, limit: int = 1000) -> int:
    ensure_place_knowledge_schema(conn)
    params: list[Any] = []
    place_filter = ""
    if place_ids:
        place_filter = "AND ec.place_id = ANY(%s)"
        params.append(place_ids)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
          ec.id::text AS id,
          ec.place_id::text AS place_id,
          ec.chunk_text,
          ec.extracted_keywords,
          ec.occurred_at,
          ec.metadata,
          rsi.platform,
          rsi.url AS source_url,
          rsi.engagement_metrics,
          rsi.geo_metadata
        FROM evidence_chunks ec
        JOIN raw_source_items rsi ON rsi.id = ec.raw_source_item_id
        WHERE ec.place_id IS NOT NULL
          {place_filter}
        ORDER BY ec.occurred_at DESC
        LIMIT %s
        """,
        tuple(params),
    ).fetchall()
    written = 0
    for row in rows:
        if upsert_place_document(
            conn,
            place_id=row["place_id"],
            source=row["platform"] or "evidence",
            source_url=row.get("source_url"),
            title=f"{row['platform']} evidence",
            content=row["chunk_text"],
            content_type="signal_evidence",
            occurred_at=row.get("occurred_at"),
            metadata={
                "evidence_chunk_id": row["id"],
                "keywords": row.get("extracted_keywords") or [],
                "engagement_metrics": row.get("engagement_metrics") or {},
                "geo_metadata": row.get("geo_metadata") or {},
                **(row.get("metadata") or {}),
            },
        ):
            written += 1
    return written


def ingest_google_place_documents(conn, place_ids: Optional[list[str]] = None) -> int:
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        return 0
    ensure_place_knowledge_schema(conn)
    rows = _places(conn, place_ids)
    written = 0
    for place in rows:
        result = _google_place_details(place, api_key)
        if not result:
            continue
        profile_content = _google_profile_content(result)
        if profile_content:
            if upsert_place_document(
                conn,
                place_id=place["id"],
                source="google_places",
                source_url=result.get("url") or _maps_url(result.get("place_id")),
                title=f"Official context for {result.get('name') or place['name']}",
                content=profile_content,
                content_type="official_description",
                metadata={
                    "source_type": "official_context",
                    "claim_type": "self_or_platform_description",
                    "trust_level": "context_only",
                    "types": result.get("types") or [],
                    "website": result.get("website"),
                    "opening_hours": result.get("opening_hours") or {},
                },
            ):
                written += 1
            if upsert_place_document(
                conn,
                place_id=place["id"],
                source="google_places",
                source_url=result.get("url") or _maps_url(result.get("place_id")),
                title=f"Google profile for {result.get('name') or place['name']}",
                content=profile_content,
                content_type="place_profile",
                metadata={
                    "types": result.get("types") or [],
                    "rating": result.get("rating"),
                    "user_ratings_total": result.get("user_ratings_total"),
                    "price_level": result.get("price_level"),
                    "website": result.get("website"),
                    "opening_hours": result.get("opening_hours") or {},
                },
            ):
                written += 1
        for review in result.get("reviews") or []:
            text = _clean_text(review.get("text") or "")
            if len(text) < 30:
                continue
            if upsert_place_document(
                conn,
                place_id=place["id"],
                source="google_reviews",
                source_url=result.get("url") or _maps_url(result.get("place_id")),
                title=f"Google review for {result.get('name') or place['name']}",
                content=text,
                content_type="review",
                occurred_at=_review_time(review),
                metadata={"rating": review.get("rating"), "author_name": review.get("author_name")},
            ):
                written += 1
    return written


def ingest_website_documents(conn, place_ids: Optional[list[str]] = None) -> int:
    ensure_place_knowledge_schema(conn)
    rows = conn.execute(
        """
        SELECT DISTINCT ON (pd.place_id)
          pd.place_id::text AS place_id,
          p.name,
          pd.metadata->>'website' AS website
        FROM place_documents pd
        JOIN places p ON p.id = pd.place_id
        WHERE pd.source = 'google_places'
          AND pd.metadata ? 'website'
          AND pd.metadata->>'website' <> ''
          AND (%s::uuid[] IS NULL OR pd.place_id = ANY(%s::uuid[]))
        ORDER BY pd.place_id, pd.fetched_at DESC
        """,
        (place_ids, place_ids),
    ).fetchall()
    written = 0
    for row in rows:
        for url in _website_candidate_urls(row["website"]):
            page = _fetch_webpage(url)
            if not page:
                continue
            title, text = page
            content_type = _website_content_type(url)
            metadata = {"website_root": row["website"]}
            if content_type == "official_description":
                metadata.update(
                    {
                        "source_type": "official",
                        "claim_type": "self_description",
                        "trust_level": "context_only",
                    }
                )
            if upsert_place_document(
                conn,
                place_id=row["place_id"],
                source="website",
                source_url=url,
                title=title or f"{row['name']} website",
                content=text,
                content_type=content_type,
                metadata=metadata,
            ):
                written += 1
    return written



BRIEF_STALENESS_DAYS = int(os.getenv("PLACE_KNOWLEDGE_BRIEF_STALENESS_DAYS", "7"))


def build_restaurant_brief_documents(conn, place_ids: Optional[list[str]] = None) -> int:
    ensure_place_knowledge_schema(conn)
    if not os.getenv("OPENAI_API_KEY"):
        return 0
    written = 0
    for place in _places(conn, place_ids):
        if _brief_is_fresh(conn, place["id"]):
            continue
        context = _restaurant_brief_context(conn, place["id"])
        brief = _generate_restaurant_brief(place, context)
        if not brief:
            continue
        content = _restaurant_brief_content(place, brief)
        full_metadata = {
            **brief,
            "source_type": "llm_generated_context",
            "trust_level": "context_only",
            "source_documents": {
                "official": len(context["official_documents"]),
                "menu": len(context["menu_documents"]),
            },
        }
        if upsert_place_document(
            conn,
            place_id=place["id"],
            source=RESTAURANT_BRIEF_SOURCE,
            source_url=f"localsignal://restaurant-brief/{place['id']}",
            title=f"Restaurant brief for {place['name']}",
            content=content,
            content_type="restaurant_brief",
            metadata=full_metadata,
        ):
            written += 1
            extract_place_food_facts_from_brief(conn, place["id"], brief)
            # Build/merge place_profile immediately from the new brief
            _upsert_profile_from_brief(conn, place, full_metadata)
    return written


def _upsert_profile_from_brief(conn, place: dict[str, Any], brief_metadata: dict[str, Any]) -> None:
    """Map a restaurant_brief metadata dict to place_profiles columns and upsert.

    Uses LLM-generated fields directly — no keyword extraction or post-processing:
      what_it_is        → known_for
      cuisine_types     → food_types   (LLM-generated cuisine labels)
      flavor_cues       → flavor_cues  (LLM-generated taste/ingredient descriptors)
      signature_menu_items → signature_items
      occasions         → occasions

    Brief is the authoritative source — always replaces, not merges.
    merge_place_profile() is for signal-derived incremental updates.
    """
    what_it_is = _clean_text(brief_metadata.get("what_it_is") or "")
    if not what_it_is:
        return

    raw_items: list[str] = brief_metadata.get("signature_menu_items") or []
    signature_items = _dedupe_display_values([item.split(" - ")[0].strip() for item in raw_items])[:8]
    food_types = _dedupe_display_values(brief_metadata.get("cuisine_types") or [])[:3]
    flavor_cues = _dedupe_display_values(brief_metadata.get("flavor_cues") or [])[:4]
    occasions = [_clean_text(o) for o in (brief_metadata.get("occasions") or []) if _clean_text(o)]

    source_docs = brief_metadata.get("source_documents") or {}
    profile = {
        "known_for": what_it_is,
        "food_types": food_types,
        "signature_items": signature_items,
        "flavor_cues": flavor_cues,
        "occasions": occasions,
        "caveats": _clean_text(brief_metadata.get("trust_note") or "Profile is derived from restaurant brief; keep claims limited to context only."),
        "source_count": int(source_docs.get("official") or 0) + int(source_docs.get("menu") or 0) + len(signature_items),
    }
    upsert_place_profile(conn, place["id"], profile)


def build_place_profiles_from_briefs(conn, place_ids: Optional[list[str]] = None) -> int:
    """Offline-build place_profiles for all places that have a restaurant_brief.

    Maps LLM-generated brief fields directly — no keyword extraction:
      what_it_is        → known_for
      cuisine_types     → food_types   (LLM-generated cuisine labels)
      flavor_cues       → flavor_cues  (LLM-generated taste/ingredient descriptors)
      signature_menu_items → signature_items
      occasions         → occasions
    """
    ensure_place_knowledge_schema(conn)
    place_filter = "AND pd.place_id = ANY(%s::uuid[])" if place_ids else ""
    params = (place_ids,) if place_ids else ()
    rows = conn.execute(
        f"""
        SELECT
          pd.place_id::text AS place_id,
          p.name,
          p.category,
          pd.metadata,
          pd.fetched_at
        FROM place_documents pd
        JOIN places p ON p.id = pd.place_id
        WHERE pd.content_type = 'restaurant_brief'
          AND pd.metadata ? 'what_it_is'
          {place_filter}
        ORDER BY pd.fetched_at DESC
        """,
        params,
    ).fetchall()

    seen: set[str] = set()
    written = 0
    for row in rows:
        place_id = row["place_id"]
        if place_id in seen:
            continue
        seen.add(place_id)
        brief_metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
        if not _clean_text(brief_metadata.get("what_it_is") or ""):
            continue
        place = {"id": place_id, "category": row.get("category") or ""}
        _upsert_profile_from_brief(conn, place, brief_metadata)
        written += 1
    return written


def extract_place_food_facts_from_brief(conn, place_id: str, brief: dict[str, Any]) -> int:
    """Persist dish facts from a restaurant_brief into place_food_facts for cross-signal reuse."""
    items: list[str] = brief.get("signature_menu_items") or []
    highlight_items: list[dict] = brief.get("highlight_items") or []
    written = 0
    for raw in items:
        text = _clean_text(str(raw or ""))
        if not text:
            continue
        dish_name = text.split(" - ")[0].strip()
        normalized = dish_name.lower()
        evidence_hash = _text_hash(f"{place_id}:dish:{normalized}")
        conn.execute(
            """
            INSERT INTO place_food_facts (
              place_id, fact_type, fact_value, normalized_value,
              evidence_text, source, confidence, evidence_hash
            )
            VALUES (%s, 'dish', %s, %s, %s, 'restaurant_brief', 0.7, %s)
            ON CONFLICT (place_id, fact_type, normalized_value, evidence_hash) DO UPDATE SET
              fact_value = EXCLUDED.fact_value,
              evidence_text = EXCLUDED.evidence_text,
              confidence = GREATEST(place_food_facts.confidence, EXCLUDED.confidence),
              updated_at = now()
            """,
            (place_id, dish_name, normalized, text, evidence_hash),
        )
        written += 1
    for h in highlight_items:
        aspect = _clean_text(str(h.get("aspect") or ""))
        detail = _clean_text(str(h.get("detail") or ""))
        if not aspect or not detail:
            continue
        normalized = aspect.lower()
        evidence_hash = _text_hash(f"{place_id}:behavior:{normalized}")
        conn.execute(
            """
            INSERT INTO place_food_facts (
              place_id, fact_type, fact_value, normalized_value,
              evidence_text, source, confidence, evidence_hash
            )
            VALUES (%s, 'behavior', %s, %s, %s, 'restaurant_brief', 0.6, %s)
            ON CONFLICT (place_id, fact_type, normalized_value, evidence_hash) DO UPDATE SET
              evidence_text = EXCLUDED.evidence_text,
              updated_at = now()
            """,
            (place_id, aspect, normalized, detail, evidence_hash),
        )
        written += 1
    return written


def get_place_food_facts(conn, place_id: str, fact_type: Optional[str] = None, min_confidence: float = 0.5) -> list[dict[str, Any]]:
    """Retrieve persisted food facts for a place, ordered by confidence."""
    if fact_type:
        rows = conn.execute(
            """
            SELECT fact_type, fact_value, normalized_value, evidence_text, source, confidence
            FROM place_food_facts
            WHERE place_id = %s AND fact_type = %s AND confidence >= %s
            ORDER BY confidence DESC, updated_at DESC
            LIMIT 20
            """,
            (place_id, fact_type, min_confidence),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT fact_type, fact_value, normalized_value, evidence_text, source, confidence
            FROM place_food_facts
            WHERE place_id = %s AND confidence >= %s
            ORDER BY confidence DESC, updated_at DESC
            LIMIT 30
            """,
            (place_id, min_confidence),
        ).fetchall()
    return [dict(row) for row in rows]


def merge_place_profile(conn, place_id: str, new_profile: dict[str, Any]) -> None:
    """Merge new signal-derived profile data into existing place_profiles, accumulating lists across weeks."""
    existing = place_profile(conn, place_id)
    if not existing:
        upsert_place_profile(conn, place_id, new_profile)
        return

    def _merge_list(old: list, new: list) -> list:
        seen: set[str] = set()
        merged: list[str] = []
        for item in list(old) + list(new):
            key = str(item).strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(str(item).strip())
        return merged[:8]

    merged = dict(existing)
    # Always take the newer known_for if it's richer
    new_known = str(new_profile.get("known_for") or "").strip()
    old_known = str(merged.get("known_for") or "").strip()
    if new_known and len(new_known) > len(old_known):
        merged["known_for"] = new_known

    merged["food_types"] = _merge_list(merged.get("food_types") or [], new_profile.get("food_types") or [])
    merged["signature_items"] = _merge_list(merged.get("signature_items") or [], new_profile.get("signature_items") or [])
    merged["flavor_cues"] = _merge_list(merged.get("flavor_cues") or [], new_profile.get("flavor_cues") or [])
    merged["occasions"] = _merge_list(merged.get("occasions") or [], new_profile.get("occasions") or [])
    merged["source_count"] = max(int(merged.get("source_count") or 0), int(new_profile.get("source_count") or 0))
    if new_profile.get("caveats"):
        merged["caveats"] = new_profile["caveats"]

    upsert_place_profile(conn, place_id, merged)


def _brief_is_fresh(conn, place_id: str) -> bool:
    row = conn.execute(
        """
        SELECT updated_at FROM place_documents
        WHERE place_id = %s AND content_type = 'restaurant_brief'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (place_id,),
    ).fetchone()
    if not row:
        return False
    from datetime import timezone
    age = datetime.now(timezone.utc) - row["updated_at"].replace(tzinfo=timezone.utc)
    return age.days < BRIEF_STALENESS_DAYS


def _text_hash(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def embed_place_documents(conn, place_ids: Optional[list[str]] = None, limit: int = 200) -> int:
    ensure_place_knowledge_schema(conn)
    if not os.getenv("OPENAI_API_KEY"):
        return 0
    params: list[Any] = []
    place_filter = ""
    if place_ids:
        place_filter = "AND place_id = ANY(%s)"
        params.append(place_ids)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT id::text AS id, content
        FROM place_documents
        WHERE embedding IS NULL
          AND length(content) >= {DOCUMENT_MIN_CHARS}
          {place_filter}
        ORDER BY fetched_at DESC
        LIMIT %s
        """,
        tuple(params),
    ).fetchall()
    if not rows:
        return 0
    embeddings = _embed_texts([row["content"][:6000] for row in rows])
    for row, embedding in zip(rows, embeddings):
        conn.execute(
            "UPDATE place_documents SET embedding = %s::vector, updated_at = now() WHERE id = %s",
            (_vector_literal(embedding), row["id"]),
        )
    return len(rows)


def retrieve_place_documents(conn, place_id: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
    ensure_place_knowledge_schema(conn)
    brief_rows = conn.execute(
        """
        SELECT id::text, source, source_url, title, content, content_type, metadata, 1::float AS semantic_score
        FROM place_documents
        WHERE place_id = %s
          AND content_type = 'restaurant_brief'
        ORDER BY fetched_at DESC
        LIMIT 1
        """,
        (place_id,),
    ).fetchall()
    official_rows = conn.execute(
        """
        SELECT id::text, source, source_url, title, content, content_type, metadata, 1::float AS semantic_score
        FROM place_documents
        WHERE place_id = %s
          AND content_type = 'official_description'
        ORDER BY fetched_at DESC
        LIMIT 2
        """,
        (place_id,),
    ).fetchall()
    food_rows = conn.execute(
        """
        SELECT id::text, source, source_url, title, content, content_type, metadata, 1::float AS semantic_score
        FROM place_documents
        WHERE place_id = %s
          AND content_type = 'food_intelligence'
        ORDER BY fetched_at DESC
        LIMIT 2
        """,
        (place_id,),
    ).fetchall()
    if os.getenv("OPENAI_API_KEY"):
        embed_place_documents(conn, [place_id], limit=80)
        query_embedding = _embed_texts([query[:6000]])[0]
        rows = conn.execute(
            """
            SELECT
              id::text,
              source,
              source_url,
              title,
              content,
              content_type,
              metadata,
              1 - (embedding <=> %s::vector) AS semantic_score
            FROM place_documents
            WHERE place_id = %s
              AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (_vector_literal(query_embedding), place_id, _vector_literal(query_embedding), limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id::text, source, source_url, title, content, content_type, metadata, 0::float AS semantic_score
            FROM place_documents
            WHERE place_id = %s
            ORDER BY fetched_at DESC
            LIMIT %s
            """,
            (place_id, limit),
        ).fetchall()
    return [_document_prompt_row(row) for row in _dedupe_document_rows([*brief_rows, *official_rows, *food_rows, *rows])[:limit]]


def place_profile(conn, place_id: str) -> Optional[dict[str, Any]]:
    ensure_place_knowledge_schema(conn)
    row = conn.execute(
        """
        SELECT known_for, food_types, signature_items, flavor_cues, occasions, caveats, source_count, profile, updated_at::text
        FROM place_profiles
        WHERE place_id = %s
        """,
        (place_id,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def upsert_place_profile(conn, place_id: str, profile: dict[str, Any]) -> None:
    ensure_place_knowledge_schema(conn)
    conn.execute(
        """
        INSERT INTO place_profiles (
          place_id,
          known_for,
          food_types,
          signature_items,
          flavor_cues,
          occasions,
          caveats,
          source_count,
          profile,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
        ON CONFLICT (place_id)
        DO UPDATE SET
          known_for = EXCLUDED.known_for,
          food_types = EXCLUDED.food_types,
          signature_items = EXCLUDED.signature_items,
          flavor_cues = EXCLUDED.flavor_cues,
          occasions = EXCLUDED.occasions,
          caveats = EXCLUDED.caveats,
          source_count = EXCLUDED.source_count,
          profile = EXCLUDED.profile,
          updated_at = now()
        """,
        (
            place_id,
            _clean_text(profile.get("known_for") or ""),
            _string_list(profile.get("food_types")),
            _string_list(profile.get("signature_items")),
            _string_list(profile.get("flavor_cues")),
            _string_list(profile.get("occasions")),
            _clean_text(profile.get("caveats") or ""),
            int(profile.get("source_count") or 0),
            Jsonb(_clean_json_value(profile)),
        ),
    )


def upsert_place_document(
    conn,
    *,
    place_id: str,
    source: str,
    source_url: Optional[str],
    title: str,
    content: str,
    content_type: str,
    occurred_at: Any = None,
    metadata: Optional[dict[str, Any]] = None,
) -> bool:
    cleaned = _clean_text(content)
    if len(cleaned) < 20:
        return False
    row = conn.execute(
        """
        INSERT INTO place_documents (
          place_id,
          source,
          source_url,
          title,
          content,
          content_type,
          occurred_at,
          metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (place_id, source, source_url, content_type) WHERE source_url IS NOT NULL
        DO UPDATE SET
          title = EXCLUDED.title,
          content = EXCLUDED.content,
          occurred_at = EXCLUDED.occurred_at,
          metadata = EXCLUDED.metadata,
          fetched_at = now(),
          updated_at = now(),
          embedding = NULL
        RETURNING id
        """,
        (
            place_id,
            source,
            source_url,
            title[:240],
            cleaned,
            content_type,
            occurred_at,
            Jsonb(metadata or {}),
        ),
    ).fetchone()
    return bool(row)



def _places(conn, place_ids: Optional[list[str]]) -> list[dict[str, Any]]:
    if place_ids:
        return conn.execute(
            """
            SELECT id::text, name, category, address, city, neighborhood, google_place_id, map_url
            FROM places
            WHERE id = ANY(%s)
            ORDER BY name
            """,
            (place_ids,),
        ).fetchall()
    return conn.execute(
        """
        SELECT id::text, name, category, address, city, neighborhood, google_place_id, map_url
        FROM places
        ORDER BY name
        LIMIT 200
        """
    ).fetchall()




def _restaurant_brief_context(conn, place_id: str) -> dict[str, Any]:
    official_documents = conn.execute(
        """
        SELECT title, content, source, source_url, metadata
        FROM place_documents
        WHERE place_id = %s
          AND content_type = 'official_description'
        ORDER BY fetched_at DESC
        LIMIT 4
        """,
        (place_id,),
    ).fetchall()
    menu_documents = conn.execute(
        """
        SELECT title, content, source, source_url, metadata
        FROM place_documents
        WHERE place_id = %s
          AND content_type = 'menu'
        ORDER BY fetched_at DESC
        LIMIT 3
        """,
        (place_id,),
    ).fetchall()
    return {
        "official_documents": [_brief_doc(row) for row in official_documents],
        "menu_documents": [_brief_doc(row) for row in menu_documents],
    }


def _generate_restaurant_brief(place: dict[str, Any], context: dict[str, Any]) -> Optional[dict[str, Any]]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    place_name = place.get("name") or ""
    city = place.get("city") or place.get("neighborhood") or ""
    search_hint = f"{place_name} {city}".strip()
    instructions = [
        f"You are researching a local restaurant called '{place_name}' in {city} for a food discovery product.",
        f"Use the web_search tool to search for '{search_hint} restaurant' to find food reviews, articles, food blogs, or any content that describes what makes this place distinctive.",
        "Also use the provided official documents and food facts.",
        "Produce a Restaurant Brief with these structured fields. Be specific and concrete — name actual dishes, flavors, and characteristics. Write 3-4 sentences for what_it_is.",
        "For cuisine_types: 1-3 specific cuisine or food-category labels (e.g. 'Korean BBQ', 'Cajun Seafood', 'Japanese Ramen', 'Bakery / Café'). Be specific — not just 'Restaurant' or 'Food'. Only what is supported by evidence.",
        "For flavor_cues: 2-4 short food or taste descriptors that capture what the food is like (e.g. 'grilled meat', 'spicy broth', 'crispy cutlet', 'fresh seafood', 'house-made pastry'). These must describe taste, texture, or ingredients — not atmosphere, format, or service. Do not include words like 'cozy', 'sit-down', 'generous portions', or 'work-friendly'.",
        "For highlight_items: extract 3-4 things that make this place distinctive. Each item needs a short aspect label (e.g. 'The Sauce', 'The Portion', 'The Atmosphere') and a 1-2 sentence detail. Only include what is supported by evidence.",
        "For signature_menu_items: list each dish as 'Dish Name - brief description of what it is'. Include up to 6 items.",
        "For vibe_tags: 3-5 short descriptors about dining format or atmosphere (e.g. 'Sit-down', 'BYOB', 'Counter seating', 'Group-friendly'). Only what is supported.",
        "For occasions: 2-4 typical visit occasions (e.g. 'Date night', 'Family dinner', 'Late-night stop'). Do not invent.",
        "Avoid recommendation language: no 'must try', 'best', 'top rated', 'you should'.",
        "Output valid JSON only.",
    ]
    prompt = {
        "instructions": instructions,
        "place": place,
        "context": context,
        "json_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["what_it_is", "cuisine_types", "flavor_cues", "official_context_note", "signature_menu_items", "highlight_items", "location_format", "vibe_tags", "occasions", "source_chips", "trust_note"],
            "properties": {
                "what_it_is": {"type": "string"},
                "cuisine_types": {"type": "array", "items": {"type": "string"}},
                "flavor_cues": {"type": "array", "items": {"type": "string"}},
                "official_context_note": {"type": "string"},
                "signature_menu_items": {"type": "array", "items": {"type": "string"}},
                "highlight_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["aspect", "detail"],
                        "properties": {
                            "aspect": {"type": "string"},
                            "detail": {"type": "string"},
                        },
                    },
                },
                "location_format": {"type": "string"},
                "vibe_tags": {"type": "array", "items": {"type": "string"}},
                "occasions": {"type": "array", "items": {"type": "string"}},
                "source_chips": {"type": "array", "items": {"type": "string"}},
                "trust_note": {"type": "string"},
            },
        },
    }
    model = os.getenv("OPENAI_MODEL_RICH", "gpt-4o")
    response = client.responses.create(
        model=model,
        tools=[{"type": "web_search_preview"}],
        input=[
            {"role": "system", "content": "You research local restaurants using web search and provided documents. Return JSON only."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    )
    try:
        data = _parse_llm_json(response.output_text)
    except json.JSONDecodeError:
        return None
    return _repair_restaurant_brief(place, data, context)


def _repair_restaurant_brief(place: dict[str, Any], data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    source_chips: list[str] = []
    if any(doc.get("source") == "website" for doc in context.get("official_documents") or []):
        source_chips.append("Official website")
    if any(doc.get("source") == "google_places" for doc in context.get("official_documents") or []):
        source_chips.append("Google profile")
    if context.get("menu_documents"):
        source_chips.append("Menu")
    if not source_chips:
        source_chips.append("Web search")
    what_it_is = _clean_text(data.get("what_it_is") or "")
    if not what_it_is:
        what_it_is = f"{place['name']} is a local restaurant in {place.get('neighborhood') or place.get('city') or 'the area'}."
    raw_highlights = data.get("highlight_items") or []
    highlight_items = [
        {"aspect": _clean_text(h.get("aspect") or ""), "detail": _clean_text(h.get("detail") or "")}
        for h in raw_highlights
        if isinstance(h, dict) and _clean_text(h.get("aspect") or "") and _clean_text(h.get("detail") or "")
    ][:4]
    cuisine_types = _dedupe_display_values(data.get("cuisine_types") or [])[:3]
    flavor_cues = _dedupe_display_values(data.get("flavor_cues") or [])[:4]
    return {
        "what_it_is": what_it_is,
        "cuisine_types": cuisine_types,
        "flavor_cues": flavor_cues,
        "official_context_note": _clean_text(data.get("official_context_note") or "Official context, not signal evidence."),
        "signature_menu_items": _dedupe_display_values(data.get("signature_menu_items") or [])[:8],
        "highlight_items": highlight_items,
        "location_format": _clean_text(data.get("location_format") or _brief_location_format(place)),
        "vibe_tags": [_clean_text(t) for t in (data.get("vibe_tags") or []) if _clean_text(t)][:5],
        "occasions": [_clean_text(o) for o in (data.get("occasions") or []) if _clean_text(o)][:4],
        "source_chips": source_chips[:5],
        "trust_note": _clean_text(data.get("trust_note") or "Restaurant brief is context only; recent movement is handled in the signal sections below."),
    }


def _parse_llm_json(value: str) -> dict[str, Any]:
    cleaned = _clean_text(value)
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    return data if isinstance(data, dict) else {}


def _restaurant_brief_content(place: dict[str, Any], brief: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Restaurant Brief for {place['name']}",
            f"What it is: {brief['what_it_is']}",
            f"Official / stable context: {brief['official_context_note']}",
            f"Signature menu items: {', '.join(brief['signature_menu_items']) if brief['signature_menu_items'] else 'Not enough menu facts yet.'}",
            f"Location / format: {brief['location_format']}",
            f"Sources: {', '.join(brief['source_chips'])}",
            f"Trust note: {brief['trust_note']}",
        ]
    )


def _brief_doc(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": row.get("title") or "",
        "source": row.get("source") or "",
        "source_url": row.get("source_url"),
        "content": _clean_text(row.get("content") or "")[:2500],
        "metadata": row.get("metadata") or {},
    }


def _brief_location_format(place: dict[str, Any]) -> str:
    area = place.get("neighborhood") or place.get("city") or "the local area"
    return f"{area} · {place.get('category') or 'restaurant'}"


def _dedupe_display_values(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value or "")
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned



def _dedupe_document_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("id") or row.get("source_url") or row.get("title") or row.get("content", "")[:80])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _google_place_details(place: dict[str, Any], api_key: str) -> dict[str, Any]:
    if place.get("google_place_id"):
        params = urllib.parse.urlencode(
            {
                "place_id": place["google_place_id"],
                "fields": "name,place_id,formatted_address,types,rating,user_ratings_total,price_level,opening_hours,editorial_summary,reviews,website,url",
                "reviews_sort": "newest",
                "reviews_no_translations": "true",
                "key": api_key,
            }
        )
        url = f"https://maps.googleapis.com/maps/api/place/details/json?{params}"
    else:
        params = urllib.parse.urlencode({"query": f"{place['name']} {place.get('address') or ''} {place['city']}", "key": api_key})
        try:
            payload = _fetch_json(f"https://maps.googleapis.com/maps/api/place/textsearch/json?{params}")
        except OSError:
            return {}
        candidate = next(iter(payload.get("results") or []), {})
        if not candidate.get("place_id"):
            return candidate or {}
        return _google_place_details({**place, "google_place_id": candidate["place_id"]}, api_key)
    try:
        payload = _fetch_json(url)
    except OSError:
        return {}
    return payload.get("result") or {}


def _google_profile_content(result: dict[str, Any]) -> str:
    parts = [
        result.get("name"),
        result.get("formatted_address"),
        "Categories: " + ", ".join(result.get("types") or []) if result.get("types") else "",
        f"Rating: {result.get('rating')} from {result.get('user_ratings_total')} reviews"
        if result.get("rating") and result.get("user_ratings_total")
        else "",
        "Hours: " + "; ".join((result.get("opening_hours") or {}).get("weekday_text") or []),
        ((result.get("editorial_summary") or {}).get("overview") or ""),
        f"Website: {result.get('website')}" if result.get("website") else "",
    ]
    return _clean_text(" | ".join(part for part in parts if part))


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _website_candidate_urls(url: str) -> list[str]:
    root = url.rstrip("/")
    candidates = [root]
    parsed = urllib.parse.urlparse(root)
    for path in ["/about", "/about-us", "/menu", "/menus", "/order", "/order-online"]:
        candidates.append(urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")))
    return candidates


def _website_content_type(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower().strip("/")
    if not path or path in {"about", "about-us", "our-story", "story"}:
        return "official_description"
    if "menu" in path or "order" in path:
        return "menu"
    return "website"


def _fetch_webpage(url: str) -> Optional[tuple[str, str]]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "LocalSignalBot/0.1"})
        with urllib.request.urlopen(request, timeout=12) as response:
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                return None
            html = response.read(1_000_000).decode("utf-8", errors="ignore")
    except OSError:
        return None
    parser = _TextExtractor()
    parser.feed(html)
    text = _clean_text(parser.text)
    if len(text) < DOCUMENT_MIN_CHARS:
        return None
    return parser.title, text[:8000]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._in_title = False
        self.title = ""
        self.parts: list[str] = []

    @property
    def text(self) -> str:
        return " ".join(self.parts)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        cleaned = _clean_text(data)
        if not cleaned:
            return
        if self._in_title:
            self.title = cleaned[:240]
        elif len(cleaned) > 2:
            self.parts.append(cleaned)


def _embed_texts(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.embeddings.create(model=os.getenv("OPENAI_EMBEDDING_MODEL", EMBEDDING_MODEL), input=texts)
    return [item.embedding for item in response.data]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def _document_prompt_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source": row["source"],
        "source_url": row.get("source_url"),
        "title": row.get("title") or "",
        "content_type": row.get("content_type") or "",
        "content": _clean_text(row.get("content") or "")[:1400],
        "metadata": row.get("metadata") or {},
        "semantic_score": float(row.get("semantic_score") or 0),
    }


def _review_time(review: dict[str, Any]):
    value = review.get("time")
    return datetime.fromtimestamp(value, tz=timezone.utc) if value else None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(str(value)).replace("\x00", "")).strip()


def _maps_url(google_place_id: Optional[str]) -> Optional[str]:
    return f"https://www.google.com/maps/place/?q=place_id:{google_place_id}" if google_place_id else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)][:12]


def _clean_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        return [_clean_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_clean_json_value(item) for item in value]
    if isinstance(value, dict):
        return {_clean_text(key): _clean_json_value(item) for key, item in value.items()}
    return value
