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
