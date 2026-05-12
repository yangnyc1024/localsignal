# LocalSignal MVP Architecture

## Goal

Generate a weekly intelligence report that answers: what changed nearby that a local person should know about?

## Services

### Frontend

Next.js app focused on one product surface:

- weekly report
- ranked signals
- place context
- feedback actions: save, share, dismiss

### Backend

FastAPI service exposing:

- `GET /health`
- `GET /reports/latest`
- `GET /signals`
- `POST /feedback`

The API reads from Postgres and returns product-shaped DTOs rather than database rows.

### Signal Engine

Batch-oriented Python service:

1. loads mentions
2. groups by place
3. computes velocity, keyword, sentiment, and source diversity signals
4. ranks signals
5. writes a weekly report

### Database

PostgreSQL with pgvector enabled for future embedding retrieval.

Core tables:

- `places`
- `mentions`
- `signals`
- `reports`
- `report_signals`
- `feedback_events`

## MVP Boundary

Live crawling is intentionally outside the first repo skeleton. The first milestone is a believable end-to-end weekly report loop using deterministic sample data and replaceable ingestion boundaries.
