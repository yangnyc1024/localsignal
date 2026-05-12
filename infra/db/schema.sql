CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS places (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  city TEXT NOT NULL,
  neighborhood TEXT,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
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
  place_id UUID NOT NULL REFERENCES places(id) ON DELETE CASCADE,
  signal_type TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  score NUMERIC(8, 4) NOT NULL DEFAULT 0,
  city TEXT NOT NULL,
  week_start DATE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  region TEXT NOT NULL,
  week_start DATE NOT NULL,
  intro TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
CREATE UNIQUE INDEX IF NOT EXISTS idx_mentions_place_source_url ON mentions(place_id, source_url) WHERE source_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_signals_week_score ON signals(week_start DESC, score DESC);
CREATE INDEX IF NOT EXISTS idx_reports_week ON reports(week_start DESC);
CREATE INDEX IF NOT EXISTS idx_subscribers_status ON subscribers(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_place_type_week ON signals(place_id, signal_type, week_start);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_region_week ON reports(region, week_start);
CREATE INDEX IF NOT EXISTS idx_email_deliveries_report ON email_deliveries(report_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_started ON ingestion_runs(started_at DESC);
