import os
import re
from html import unescape
from typing import Any, Optional

from psycopg.types.json import Jsonb

from .schema import ensure_place_knowledge_schema

DOCUMENT_MIN_CHARS = 80
EMBEDDING_MODEL = "text-embedding-3-small"
RESTAURANT_BRIEF_SOURCE = "localsignal_restaurant_brief"


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(str(value)).replace("\x00", "")).strip()


def _text_hash(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def _vector_literal(values: list) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def _document_prompt_row(row: dict) -> dict:
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


def _dedupe_document_rows(rows: list) -> list:
    deduped: list = []
    seen: set = set()
    for row in rows:
        key = str(row.get("id") or row.get("source_url") or row.get("title") or row.get("content", "")[:80])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _embed_texts(texts: list) -> list:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.embeddings.create(model=os.getenv("OPENAI_EMBEDDING_MODEL", EMBEDDING_MODEL), input=texts)
    return [item.embedding for item in response.data]


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
    metadata: Optional[dict] = None,
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


def sync_existing_evidence_documents(conn, place_ids: Optional[list] = None, limit: int = 1000) -> int:
    ensure_place_knowledge_schema(conn)
    params: list = []
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


def embed_place_documents(conn, place_ids: Optional[list] = None, limit: int = 200) -> int:
    ensure_place_knowledge_schema(conn)
    if not os.getenv("OPENAI_API_KEY"):
        return 0
    params: list = []
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


def retrieve_place_documents(conn, place_id: str, query: str, limit: int = 8) -> list:
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
