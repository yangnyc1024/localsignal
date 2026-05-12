# LocalSignal MVP

AI-powered local change intelligence for Fort Lee, Edgewater, and Palisades Park.

LocalSignal is not a map or a review database. The MVP produces a weekly local intelligence feed that explains what changed nearby and why it matters.

## Repo Structure

```txt
apps/web/             Next.js frontend for the weekly intelligence feed
services/api/         FastAPI backend for places, signals, and weekly reports
services/engine/      Python signal engine for extraction, scoring, and report generation
infra/db/             PostgreSQL + pgvector schema and seed data
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

Signal engine:

```bash
make setup-python
cd services/engine
../../.venv/bin/python -m localsignal_engine.run_demo
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

The current implementation includes deterministic sample data and scoring logic so the product can be reviewed before live data ingestion is wired in.
