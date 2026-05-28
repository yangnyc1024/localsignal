CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS places (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  address TEXT,
  city TEXT NOT NULL,
  neighborhood TEXT,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  google_place_id TEXT,
  map_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mentions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  source_url TEXT,
  author_region TEXT,
  body TEXT NOT NULL,
  rating NUMERIC(2, 1),
  sentiment NUMERIC(4, 3),
  occurred_at TIMESTAMPTZ NOT NULL,
  embedding vector(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT,
  place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
  signal_type TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  short_summary TEXT,
  ai_summary TEXT,
  why_this_matters TEXT,
  confidence_level TEXT CHECK (confidence_level IN ('High', 'Medium', 'Low')),
  confidence_score NUMERIC(6, 3),
  confidence_reason TEXT,
  metrics JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  related_signal_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  status TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'published', 'hidden')),
  rank INTEGER,
  time_window TEXT,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  score NUMERIC(8, 4) NOT NULL DEFAULT 0,
  city TEXT NOT NULL,
  week_start DATE NOT NULL,
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE places ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE places ADD COLUMN IF NOT EXISTS google_place_id TEXT;
ALTER TABLE places ADD COLUMN IF NOT EXISTS map_url TEXT;

ALTER TABLE signals ADD COLUMN IF NOT EXISTS slug TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS short_summary TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS ai_summary TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS why_this_matters TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS confidence_level TEXT CHECK (confidence_level IN ('High', 'Medium', 'Low'));
ALTER TABLE signals ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(6, 3);
ALTER TABLE signals ADD COLUMN IF NOT EXISTS confidence_reason TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS metrics JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS evidence_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[];
ALTER TABLE signals ADD COLUMN IF NOT EXISTS related_signal_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[];
ALTER TABLE signals ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'published', 'hidden'));
ALTER TABLE signals ADD COLUMN IF NOT EXISTS rank INTEGER;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS time_window TEXT;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
-- food_signal promoted from evidence JSONB bag to its own queryable column
ALTER TABLE signals ADD COLUMN IF NOT EXISTS food_signal JSONB;

CREATE TABLE IF NOT EXISTS raw_source_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform TEXT NOT NULL,
  url TEXT,
  author_id TEXT,
  place_id UUID REFERENCES places(id) ON DELETE SET NULL,
  text TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  engagement_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  geo_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  place_resolution_confidence NUMERIC(5, 4),
  resolution_status TEXT NOT NULL DEFAULT 'unresolved' CHECK (resolution_status IN ('resolved', 'unresolved', 'review')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  raw_source_item_id UUID NOT NULL REFERENCES raw_source_items(id) ON DELETE CASCADE,
  place_id UUID REFERENCES places(id) ON DELETE SET NULL,
  chunk_text TEXT NOT NULL,
  extracted_keywords TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  sentiment NUMERIC(5, 4),
  occurred_at TIMESTAMPTZ NOT NULL,
  embedding vector(1536),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
  signal_type TEXT NOT NULL,
  time_window TEXT NOT NULL,
  detected_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  component_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
  candidate_score NUMERIC(8, 4) NOT NULL DEFAULT 0,
  trigger_reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'generated', 'published', 'hidden')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signal_evidence (
  signal_id UUID NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
  evidence_chunk_id UUID NOT NULL REFERENCES evidence_chunks(id) ON DELETE CASCADE,
  relevance_score NUMERIC(6, 3) NOT NULL DEFAULT 0,
  rank INTEGER NOT NULL,
  PRIMARY KEY (signal_id, evidence_chunk_id)
);

CREATE TABLE IF NOT EXISTS signal_candidate_evidence (
  signal_candidate_id UUID NOT NULL REFERENCES signal_candidates(id) ON DELETE CASCADE,
  evidence_chunk_id UUID NOT NULL REFERENCES evidence_chunks(id) ON DELETE CASCADE,
  relevance_score NUMERIC(6, 3) NOT NULL DEFAULT 0,
  rank INTEGER NOT NULL,
  PRIMARY KEY (signal_candidate_id, evidence_chunk_id)
);

CREATE TABLE IF NOT EXISTS signal_relations (
  signal_id UUID NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
  related_signal_id UUID NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
  reason TEXT,
  rank INTEGER NOT NULL,
  PRIMARY KEY (signal_id, related_signal_id)
);

CREATE TABLE IF NOT EXISTS baseline_profiles (
  place_id UUID PRIMARY KEY REFERENCES places(id) ON DELETE CASCADE,
  trailing_30d_mentions INTEGER NOT NULL DEFAULT 0,
  trailing_90d_mentions INTEGER NOT NULL DEFAULT 0,
  trailing_365d_mentions INTEGER NOT NULL DEFAULT 0,
  source_diversity INTEGER NOT NULL DEFAULT 0,
  recurring_keywords TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  baseline_heat_score NUMERIC(8, 4) NOT NULL DEFAULT 0,
  baseline_status TEXT NOT NULL DEFAULT 'Quiet baseline',
  baseline_summary TEXT NOT NULL DEFAULT '',
  last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
);

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
);

CREATE TABLE IF NOT EXISTS place_food_facts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
  source_document_id UUID REFERENCES place_documents(id) ON DELETE SET NULL,
  fact_type TEXT NOT NULL CHECK (fact_type IN ('dish', 'occasion', 'behavior')),
  fact_value TEXT NOT NULL,
  normalized_value TEXT NOT NULL,
  evidence_text TEXT NOT NULL,
  source TEXT NOT NULL,
  source_url TEXT,
  occurred_at TIMESTAMPTZ,
  confidence NUMERIC(5, 4) NOT NULL DEFAULT 0.5,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  evidence_hash TEXT NOT NULL,
  embedding vector(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  step TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('started', 'succeeded', 'failed')),
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  region TEXT NOT NULL,
  week_start DATE NOT NULL,
  intro TEXT NOT NULL,
  briefing JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE reports ADD COLUMN IF NOT EXISTS briefing JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS subscribers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  region TEXT NOT NULL DEFAULT 'Fort Lee / Edgewater / Palisades Park',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'unsubscribed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_deliveries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscriber_id UUID NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
  report_id UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  recipient_email TEXT NOT NULL,
  subject TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('dry_run', 'sent', 'failed')),
  provider TEXT NOT NULL DEFAULT 'local',
  provider_message_id TEXT,
  error TEXT,
  body_preview TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status TEXT NOT NULL CHECK (status IN ('started', 'succeeded', 'failed')),
  source_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
  live_mentions_written INTEGER NOT NULL DEFAULT 0,
  signals_generated INTEGER NOT NULL DEFAULT 0,
  report_id UUID REFERENCES reports(id) ON DELETE SET NULL,
  error TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS social_source_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'social_metadata',
  dataset_id TEXT,
  query TEXT,
  status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
  total_records INTEGER NOT NULL DEFAULT 0,
  normalized_records INTEGER NOT NULL DEFAULT 0,
  fresh_records INTEGER NOT NULL DEFAULT 0,
  old_records_dropped INTEGER NOT NULL DEFAULT 0,
  parsed_items INTEGER NOT NULL DEFAULT 0,
  resolved_items INTEGER NOT NULL DEFAULT 0,
  review_items INTEGER NOT NULL DEFAULT 0,
  unresolved_items INTEGER NOT NULL DEFAULT 0,
  source_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS report_signals (
  report_id UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  signal_id UUID NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
  rank INTEGER NOT NULL,
  PRIMARY KEY (report_id, signal_id)
);

CREATE TABLE IF NOT EXISTS feedback_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL CHECK (event_type IN ('click', 'save', 'share', 'dismiss')),
  session_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mentions_place_time ON mentions(place_id, occurred_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_places_google_place_id ON places(google_place_id) WHERE google_place_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_mentions_place_source_url ON mentions(place_id, source_url) WHERE source_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_signals_week_score ON signals(week_start DESC, score DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_slug ON signals(slug) WHERE slug IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_signals_status_score ON signals(status, week_start DESC, score DESC);
CREATE INDEX IF NOT EXISTS idx_reports_week ON reports(week_start DESC);
CREATE INDEX IF NOT EXISTS idx_subscribers_status ON subscribers(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_place_type_week ON signals(place_id, signal_type, week_start);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_region_week ON reports(region, week_start);
CREATE INDEX IF NOT EXISTS idx_email_deliveries_report ON email_deliveries(report_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_started ON ingestion_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_source_runs_finished ON social_source_runs(finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_source_runs_provider_dataset ON social_source_runs(provider, dataset_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_source_items_platform_url ON raw_source_items(platform, url) WHERE url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_raw_source_items_place_time ON raw_source_items(place_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_chunks_place_time ON evidence_chunks(place_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_candidates_status_score ON signal_candidates(status, candidate_score DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_step_started ON pipeline_runs(step, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_baseline_profiles_heat ON baseline_profiles(baseline_heat_score DESC);
CREATE INDEX IF NOT EXISTS idx_place_documents_place_type ON place_documents(place_id, content_type);
CREATE INDEX IF NOT EXISTS idx_place_documents_place_fetched ON place_documents(place_id, fetched_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_place_documents_unique_source
  ON place_documents(place_id, source, source_url, content_type)
  WHERE source_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_place_documents_embedding_hnsw
  ON place_documents USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_place_food_facts_place_type ON place_food_facts(place_id, fact_type, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_place_food_facts_value ON place_food_facts(normalized_value);
CREATE UNIQUE INDEX IF NOT EXISTS idx_place_food_facts_unique_evidence
  ON place_food_facts(place_id, fact_type, normalized_value, evidence_hash);
