# LocalSignal MVP

AI-powered local change intelligence for Fort Lee, Edgewater, and Palisades Park.

LocalSignal is not a map or a review database. The MVP produces a weekly local intelligence feed that explains what changed nearby and why it matters.

## Repo Structure

```txt
apps/web/             Next.js frontend for the weekly intelligence feed
services/api/         FastAPI backend for places, signals, and weekly reports
services/engine/      Python signal engine for extraction, scoring, and report generation
infra/db/             PostgreSQL + pgvector schema and place seed data
docs/                 Product and architecture notes
docker-compose.yml    Local Postgres, API, engine, and web services
```

## Quick Start

The repo is scaffolded so each service can be developed independently. For normal local testing, Docker is the easiest path.

```bash
make up-detached
```

Then open:

- Web: http://localhost:3000
- API docs: http://localhost:8000/docs


## Local Test Checklist

Use these steps when you want to run the product yourself from a clean checkout.

### 1. Clone and enter the project

```bash
cd /Users/linyang1024/Documents/Codex/localsignal
```

### 2. Create local env files

```bash
cp .env.example .env
```

Then fill in the keys you want to use in `.env`:

- `GOOGLE_PLACES_API_KEY` for place discovery and Google review evidence
- `OPENAI_API_KEY` for weekly LLM enrichment
- `OPENAI_MODEL` — model for signal enrichment (default `gpt-4.1-mini`)
- `OPENAI_MODEL_RICH` — model for restaurant brief generation with web search (default `gpt-4o`; required for `web_search_preview`)
- `RESEND_API_KEY`, `EMAIL_FROM`, and at least one active subscriber if you want to send email

For real social metadata, put authorized export files in `data/social/` and point `.env` at the container paths:

```bash
INSTAGRAM_JSON_PATH=/data/social/instagram.json
TIKTOK_JSON_PATH=/data/social/tiktok.json
XHS_JSON_PATH=/data/social/xiaohongshu.json
```

Each variable also accepts comma-separated files, such as:

```bash
XHS_JSON_PATH=/data/social/xhs-week1.json,/data/social/xhs-week2.json
```

Use `docs/social_manual_seed.template.json` as the intake shape and follow `docs/social_metadata_compliance.md`. For automated vendor/API imports, configure `APIFY_TOKEN` and `APIFY_SOCIAL_DATASET_IDS`, or write exports into `data/social/inbox/`. Validate files before ingestion:

```bash
make validate-social SOCIAL_JSON_PATHS=data/social/instagram.json,data/social/tiktok.json,data/social/xiaohongshu.json
```

Keep `.env` private. Do not commit real API keys or real social metadata exports.

### 3. Start the app with Docker

```bash
make up-detached
```

Open:

- Web: http://localhost:3000
- API docs: http://localhost:8000/docs

Check containers:

```bash
make ps
```

Tail logs:

```bash
make logs
```

Stop everything:

```bash
make down
```



### Automated Instagram Search

To generate fresh Apify datasets for local Instagram discovery, run:

```bash
make apify-instagram-search
```

The search uses two modes by default: local `place` queries and food/location hashtags. Place queries are good at finding Fort Lee / Edgewater / Palisades Park businesses; hashtag queries are better for recent chatter when tags have enough activity. Ingestion applies `SOCIAL_MAX_AGE_DAYS` so old posts do not create current-week signals.

### 4. Build real local data

For a fresh Docker volume, run the pipeline in this order:

```bash
make docker-discover
make docker-evidence
make docker-report
```

What each step does:

- `docker-discover`: finds Fort Lee / Edgewater / Palisades Park food places from Google Places
- `docker-evidence`: ingests Google reviews, Google News/RSS, and optional Instagram/TikTok/Xiaohongshu metadata files
- `docker-report`: generates the weekly report, links evidence, runs LLM enrichment, and does not send email

After this, refresh http://localhost:3000.

If social metadata files are configured, `docker-evidence` imports them before live review/news ingestion. Resolved records become mentions and evidence chunks; ambiguous records stay in review/unresolved buckets instead of being forced into a place.

### 5. Send the latest digest

First make sure the subscriber exists. Example:

```bash
docker compose exec -T db psql -U localsignal -d localsignal -c "insert into subscribers (email, region, status, updated_at) values ('you@example.com', 'Fort Lee / Edgewater / Palisades Park', 'active', now()) on conflict (email) do update set status='active', updated_at=now();"
```

Then send:

```bash
make docker-send-digest
```

Check delivery records:

```bash
docker compose exec -T db psql -U localsignal -d localsignal -c "select recipient_email, subject, status, provider, error, created_at from email_deliveries order by created_at desc limit 5;"
```

### 6. Optional non-Docker development

Install Python dependencies:

```bash
make setup-python
```

Run API locally against Docker Postgres:

```bash
make api
```

Run web locally:

```bash
cd apps/web
npm install
npm run dev
```

Run local engine commands directly:

```bash
make discover-places
make evidence-ingestion
make report
```

For non-Docker commands, `.env` should include:

```bash
DATABASE_URL=postgresql://localsignal:localsignal@localhost:5432/localsignal
```

## Local Development

Frontend:

```bash
cd apps/web
npm install
npm run dev
```

Backend:

```bash
make setup-python
cd services/api
../../.venv/bin/uvicorn app.main:app --reload --port 8000
```

Signal engine demo:

```bash
make setup-python
cd services/engine
../../.venv/bin/python -m localsignal_engine.run_demo
```

Demo data is isolated to explicit demo commands. The production scheduler does not use sample mentions.

Generate the real weekly report into Postgres:

```bash
make report
```

Run the local weekly scheduler:

```bash
make scheduler
```

In Docker Compose, the `scheduler` service can run the same weekly cycle. In `.env.example`, weekly scheduling is disabled by default (`WEEKLY_REPORT_ENABLED=false`) so local testing stays manual and repeatable.

## Email Subscriptions

The MVP includes a weekly email subscription capture flow:

- frontend form on the main feed
- `POST /subscribers`
- `subscribers` table with active/unsubscribed status

The current implementation supports Resend when `RESEND_API_KEY` and `EMAIL_FROM` are configured. Without an API key, deliveries are stored as `dry_run` rows in `email_deliveries`.

To send real email with Resend:

```bash
RESEND_API_KEY=re_xxx
EMAIL_FROM=LocalSignal <onboarding@resend.dev>
```

Then run:

```bash
make send-digest
```

To send a Resend smoke-test email:

```bash
TEST_EMAIL_TO=linyangnyc@gmail.com make send-test-email
```

In Docker Compose, set the same environment variables in `.env` before starting `scheduler`.

## Ingestion Status

The repo now has an ingestion adapter boundary at `services/engine/localsignal_engine/ingestion`.

Current support:

- local JSON mention imports
- Reddit public JSON search via `REDDIT_ENABLED=true` and `REDDIT_SUBREDDITS`, with weekly cadence by default
- RSS/Atom local blog ingestion via `RSS_FEED_URLS`
- Google News RSS search via `GOOGLE_NEWS_ENABLED`
- Yelp Fusion API via `YELP_API_KEY`
- Google Places Text Search API via `GOOGLE_PLACES_API_KEY`
- Instagram/TikTok/Xiaohongshu metadata JSON imports via `INSTAGRAM_JSON_PATH`, `TIKTOK_JSON_PATH`, and `XHS_JSON_PATH`

Not included yet:

- direct TikTok/Instagram/Xiaohongshu scraping
- direct Google/Yelp scraping

Those should be added as source-specific adapters rather than hidden inside the scoring code.

Example live ingestion config:

```bash
# Reddit is disabled by default for local development to avoid 429 rate limits.
# Enable it explicitly, keep the query cap low, and let it run weekly by default.
REDDIT_ENABLED=true
REDDIT_SUBREDDITS=newjersey,bergencounty
REDDIT_MAX_QUERIES=10
REDDIT_SLEEP_SECONDS=3
REDDIT_INTERVAL_SECONDS=604800

RSS_FEED_URLS=https://example-local-blog.com/feed.xml,https://another-site.com/rss
GOOGLE_NEWS_ENABLED=true
YELP_API_KEY=yelp_xxx
GOOGLE_PLACES_API_KEY=google_xxx
```

For a one-off Reddit run during testing, set `REDDIT_FORCE_RUN=true` temporarily. Remove it afterward so the scheduler returns to the weekly cadence.

## ML Engine

Weekly report generation now uses `localsignal_engine.ml_engine` instead of only static rules.

It compares a current window against a baseline window:

- mention velocity
- keyword novelty
- source diversity
- simple sentiment estimation
- outside-region pull

Configure the analysis windows with:

```bash
ML_CURRENT_WINDOW_DAYS=7
ML_BASELINE_WINDOW_DAYS=28
```

## MVP Flow

```txt
Mentions
-> entity resolution
-> signal extraction
-> scoring
-> evidence retrieval
-> LLM structured interpretation
-> weekly report
-> user feedback
```

The current implementation keeps deterministic sample data only for explicit demo commands. The weekly scheduler uses live/imported mentions and fails clearly if no real signals can be generated.
