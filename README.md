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

The repo is scaffolded so each service can be developed independently.

```bash
docker compose up --build
```

Then open:

- Web: http://localhost:3000
- API docs: http://localhost:8000/docs

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

In Docker Compose, the `scheduler` service runs the same weekly cycle. By default it runs once on start and then every 604800 seconds.

## Email Subscriptions

The MVP includes a weekly email subscription capture flow:

- frontend form on the main feed
- `POST /subscribers`
- `subscribers` table with active/unsubscribed status

It stores subscribers but does not send email yet. A production sender such as Resend, Postmark, or SES should be added behind a weekly digest job.
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
- Reddit public JSON search via `REDDIT_SUBREDDITS`
- RSS/Atom local blog ingestion via `RSS_FEED_URLS`
- Google News RSS search via `GOOGLE_NEWS_ENABLED`
- Yelp Fusion API via `YELP_API_KEY`
- Google Places Text Search API via `GOOGLE_PLACES_API_KEY`

Not included yet:

- TikTok/Instagram/Xiaohongshu ingestion
- direct Google/Yelp scraping

Those should be added as source-specific adapters rather than hidden inside the scoring code.

Example live ingestion config:

```bash
REDDIT_SUBREDDITS=newjersey,bergencounty
RSS_FEED_URLS=https://example-local-blog.com/feed.xml,https://another-site.com/rss
GOOGLE_NEWS_ENABLED=true
YELP_API_KEY=yelp_xxx
GOOGLE_PLACES_API_KEY=google_xxx
```

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
-> AI-style explanation
-> weekly report
-> user feedback
```

The current implementation keeps deterministic sample data only for explicit demo commands. The weekly scheduler uses live/imported mentions and fails clearly if no real signals can be generated.
