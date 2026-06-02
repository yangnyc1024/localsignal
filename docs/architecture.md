# LocalSignal System Architecture

## Product Goal

LocalSignal turns local restaurant activity into evidence-backed intelligence:

- what changed nearby
- why the change is happening
- which food/place context makes the signal believable
- what evidence supports the read

The product surface is intentionally not a generic review browser. The moat is the signal detail page: retrieved place context plus fresh evidence compressed into a clear read.

## System Layers

```mermaid
flowchart TD
  A["Source ingestion"] --> B["Raw source items"]
  B --> C["Evidence chunks"]
  C --> D["Signal detector"]
  D --> E["Signals"]
  C --> F["Place documents"]
  F --> G["OpenAI embeddings + pgvector"]
  G --> H["LLM signal enrichment"]
  H --> E
  H --> I["Place profiles + Restaurant briefs"]
  I --> FF["place_food_facts"]
  FF --> H
  E --> J["Weekly reports"]
  I --> K["FastAPI product DTOs"]
  J --> K
  K --> L["Next.js web app"]
```

## Data Flow

1. Ingestion writes normalized source material into `raw_source_items`, `mentions`, and `evidence_chunks`.
2. The signal engine ranks candidate changes and writes published rows into `signals`.
3. `run_place_knowledge` converts existing evidence, Google/place details, and website text into `place_documents`.
4. `build_restaurant_brief_documents` uses GPT-4o with `web_search_preview` to generate a structured restaurant brief per place, stored in `place_documents` with `content_type='restaurant_brief'`. The structured JSON is stored in `place_documents.metadata`; a text version is stored in `place_documents.content` for RAG retrieval. Briefs are regenerated only when stale (default: older than 7 days, configurable via `PLACE_KNOWLEDGE_BRIEF_STALENESS_DAYS`).
5. After each brief is written, two additional steps run immediately — no extra LLM calls:
   - `extract_place_food_facts_from_brief()` extracts `signature_menu_items` (as `dish` facts) and `highlight_items` (as `behavior` facts) into `place_food_facts` with per-fact confidence scores and hash-based dedup.
   - `_upsert_profile_from_brief()` maps `what_it_is` → `known_for`, `signature_menu_items` → `signature_items`, `vibe_tags`+`highlight_items` → `flavor_cues`, `occasions` → `occasions` into `place_profiles`. Every place that gets a brief immediately gets a profile — no signal required.
6. `place_documents.embedding` stores OpenAI `text-embedding-3-small` vectors in pgvector.
7. LLM enrichment retrieves the most relevant `place_documents` for a place/signal **plus** any verified `place_food_facts` for that place, and passes both to the LLM as context. Food facts serve as high-confidence anchors for `food_signal.signal_dish` and `place_profile.signature_items`. Signal writes use `merge_place_profile()` to accumulate profile data across weeks rather than overwriting. The API merges `evidence.food_signal` in responses for backward compatibility.
7. Report generation writes `reports`, `report_signals`, and `reports.briefing`.
8. FastAPI returns product-shaped DTOs. The web app should not need to know database internals.

## Two Knowledge Domains

The system maintains two distinct knowledge domains, both stored in the same PostgreSQL instance:

### Place Knowledge (static)

Describes **what a place is** — independent of time, updated periodically.

| Table | Purpose |
|---|---|
| `places` | Canonical identity, location, map metadata |
| `place_documents` | Retrieval corpus: crawled docs, menus, official descriptions, and LLM-generated briefs |
| `place_profiles` | Durable summary: known_for, food_types, signature_items, flavor_cues, occasions. Updated via `merge_place_profile()` so data accumulates across weekly signal runs. |
| `place_food_facts` | Verified dish and behavior facts extracted from restaurant briefs. Each row has a `fact_type` (`dish` / `behavior`), `confidence`, and `evidence_hash` for dedup. Used as high-confidence anchors in signal enrichment. |
| `baseline_profiles` | Historical heat scores and trailing mention counts |

`place_documents` with `content_type='restaurant_brief'` is the primary source for the "About this place" section. The `metadata` column carries the structured brief (JSON) and `content` carries a text version for embedding/RAG.

`place_food_facts` is the cross-signal dish knowledge base. It is written when a restaurant brief is produced and queried at signal enrichment time to improve `food_signal.signal_dish` accuracy without relying on per-run text pattern matching.

### Signal Knowledge (temporal)

Describes **what happened this week** at a place — time-windowed, generated weekly.

| Table | Purpose |
|---|---|
| `signals` | Weekly signal record with score, confidence, and evidence JSON |
| `evidence_chunks` | Source-backed review/mention snippets, vectorized |
| `signal_evidence` | Ranked links from signals to evidence chunks |

`signals.food_signal` (dedicated JSONB column) is the primary source for the "What's moving this week" section.

`evidence_chunks` is shared: Place Knowledge queries the full history; Signal queries the current week window only.

## Source Of Truth

`places`

Canonical identity, location, map metadata, Google place id, and category.

`place_documents`

Retrieval corpus. Holds review snippets, evidence chunks, Google context, official descriptions, website/menu text, and LLM-generated restaurant briefs. Restaurant briefs (`content_type='restaurant_brief'`) are produced by `build_restaurant_brief_documents()` and stored with full structured JSON in `metadata`.

`place_food_facts`

Verified dish and behavior facts extracted from restaurant briefs. Rows accumulate over time via hash-based dedup (`evidence_hash`). Confidence values: `0.7` for dishes from `signature_menu_items`, `0.6` for behaviors from `highlight_items`. Signal enrichment queries this table first before falling back to text pattern matching.

`place_profiles`

Durable profile summary for a place. Updated by `merge_place_profile()` which accumulates list fields (`signature_items`, `food_types`, `flavor_cues`, `occasions`) across weekly runs rather than overwriting them. API responses should prefer this table over old snapshots inside `signals.evidence.place_profile`.

`signals`

The signal record: title, score, confidence, metrics, status, evidence JSON, and `food_signal` (dedicated JSONB column). `food_signal` is signal-local because it changes with the particular trend being explained. The `evidence` bag retains the signal metrics and LLM narrative fields; `food_signal` lives in its own column so it is queryable and indexable independently.

`signal_evidence`

Ranked links from signals to the evidence chunks that justify the signal.

`reports`

Weekly narrative packaging. `reports.briefing` is report-level copy, not the canonical place profile.

## Restaurant Brief

Generated by `localsignal_engine.place_knowledge.build_restaurant_brief_documents()`.

**Model:** `gpt-4o` (configured via `OPENAI_MODEL_RICH`, default `gpt-4o`)

**Staleness:** Briefs are skipped when the most recent `place_documents` row with `content_type='restaurant_brief'` was updated within `PLACE_KNOWLEDGE_BRIEF_STALENESS_DAYS` days (default: `7`). This avoids unnecessary gpt-4o calls on unchanged places.

**Post-write extraction:** After each brief is written, `extract_place_food_facts_from_brief()` automatically extracts structured facts into `place_food_facts`:
- `signature_menu_items` → `fact_type='dish'`, confidence `0.7`
- `highlight_items` → `fact_type='behavior'`, confidence `0.6`
- Rows are hash-deduped; existing rows with lower confidence are upgraded.

**Retrieval:** Uses `web_search_preview` tool to search `"{place_name} {city} restaurant"` in addition to official documents and menu facts from `place_documents`.

**Output shape:**

```python
{
  "what_it_is": str,              # 2-3 sentence description → place_profiles.known_for
  "cuisine_types": [str],         # 1-3 specific cuisine labels → place_profiles.food_types
                                  # e.g. "Korean BBQ", "Cajun / Seafood Boil", "Bakery / Café"
  "flavor_cues": [str],           # 2-4 taste/ingredient descriptors → place_profiles.flavor_cues
                                  # e.g. "grilled meat", "crispy cutlet", "fresh seafood"
                                  # Must describe taste/texture/ingredients — not atmosphere/format
  "official_context_note": str,   # stable official context
  "signature_menu_items": [str],  # up to 8 items, "Name - description" format → place_profiles.signature_items
  "highlight_items": [            # up to 4 distinctive aspects (food OR atmosphere)
    {"aspect": str, "detail": str}
  ],
  "location_format": str,         # "Neighborhood · category"
  "vibe_tags": [str],             # up to 5 atmosphere/format tags (Sit-down, BYOB, etc.)
  "occasions": [str],             # up to 4 use cases → place_profiles.occasions
  "source_chips": [str],          # provenance labels
  "trust_note": str,              # context-only disclaimer
}
```

The brief is stored in `place_documents.metadata` (structured JSON for API) and `place_documents.content` (text for RAG embedding). `place_documents.source` is `localsignal_restaurant_brief`.

**Direct mapping to `place_profiles` (no post-processing):**

| Brief field | → | `place_profiles` column |
|---|---|---|
| `what_it_is` | → | `known_for` |
| `cuisine_types` | → | `food_types` |
| `flavor_cues` | → | `flavor_cues` |
| `signature_menu_items` (dish name only) | → | `signature_items` |
| `occasions` | → | `occasions` |

No keyword extraction or blocklist filtering — the LLM is responsible for producing correct values in each field.

## Food Signal

Generated per signal by `localsignal_engine.llm_signal` from `evidence_chunks` in the current week window, enriched with `place_food_facts` as stable dish anchors.

**Output shape (stored in `signals.food_signal` column; API response also includes it as `evidence.food_signal` for backward compatibility):**

```python
{
  "summary": str,          # 1-2 sentence signal narrative
  "primary_pull": str,     # what's driving attention
  "signal_dish": str,      # most-mentioned specific dish name this week
  "flavor_cue": str,       # taste/texture descriptor
  "occasion": str,         # when/why people come
  "confidence": str,       # "High" | "Medium" | "Low"
  "evidence_basis": str,   # source summary
  "image_query": str,      # image search hint
  "image_alt": str,        # accessibility text
}
```

`signal_dish` names the single most-mentioned specific dish or menu item for the signal. When the LLM returns a generic label ("food", "restaurant"), enrichment falls back to `place_food_facts` (confidence ≥ 0.6, LLM-extracted from restaurant briefs) — no keyword/regex pattern matching.

## Detail Page Contract

The signal detail page is split into two sections:

### Section 1 — About this place
Source: `restaurant_brief` (from `place_documents.metadata`)

- Place name, cuisine label, `what_it_is` description
- `highlight_items` grid — what makes this place distinctive
- `signature_menu_items` — stable menu anchors
- Experience card: `location_format`, `vibe_tags`, `occasions`
- `source_chips` — provenance labels

Falls back to `signals.evidence.place_profile` data when `restaurant_brief` is null.

### Section 2 — What's moving this week
Source: `food_signal` (from `signals.food_signal` column, surfaced via `evidence.food_signal` in API responses) + `evidence_chunks`

- Featured dish card: `signal_dish` or `primary_pull`
- Occasion context if available
- Top evidence quotes (Recent voices) with platform, timestamp, source link

Old concepts such as SignalRead, FoodSignal panel, and Food Intelligence panel have been removed. The UI reads directly from `restaurant_brief` and `food_signal` without client-side reshaping.

## Retrieval And LLM Design

The current RAG path is intentionally lightweight:

- no LangChain dependency
- no PyTorch runtime
- OpenAI embeddings through `text-embedding-3-small`
- pgvector storage and cosine search
- direct Python orchestration in `localsignal_engine.place_knowledge`
- `web_search_preview` tool for restaurant brief enrichment (requires `gpt-4o`)

This is the right shape for the current product stage because the corpus is small and the retrieval contract is simple.

## Operational Commands

Local:

```bash
make evidence-ingestion
make place-knowledge
make report
```

Docker:

```bash
make docker-evidence
make docker-place-knowledge
make docker-report
```

The intended refresh loop is:

1. ingest source evidence
2. generate candidate weekly signals from the current/baseline windows
3. refresh place knowledge for only the places that appear in the report
4. build/update restaurant briefs and embeddings for those places
5. generate signal enrichments and digest output
6. verify homepage and signal detail pages

The weekly job calls the place-knowledge layer after `write_weekly_report()` and `link_evidence_chunks_to_signals()`. `Restaurant Brief` data is produced during scheduled report generation, not lazily from the signal detail page. The refresh is scoped to the places in that week's report.

The scheduler container must carry the same LLM-related environment as ad-hoc engine jobs:

- `OPENAI_API_KEY`
- `OPENAI_MODEL` — standard model for signal enrichment (default `gpt-4.1-mini`)
- `OPENAI_MODEL_RICH` — rich model for restaurant briefs (default `gpt-4o`, required for `web_search_preview`)
- `OPENAI_EMBEDDING_MODEL`
- `PLACE_KNOWLEDGE_WEEKLY_ENABLED`
- `PLACE_KNOWLEDGE_GOOGLE_ENABLED`
- `PLACE_KNOWLEDGE_WEBSITE_ENABLED`
- `PLACE_KNOWLEDGE_EMBED_ENABLED`
- `PLACE_KNOWLEDGE_BRIEF_STALENESS_DAYS` — skip restaurant brief regeneration if updated within this many days (default: `7`)

## Place Knowledge Design Notes

Place Knowledge is an **offline reference database** — it describes what a place *is*, independent of any weekly signal. It is built and refreshed independently of the signal pipeline. When a signal fires for a place, the enrichment step looks up Place Knowledge to provide stable identity context to the LLM (restaurant brief, menu, cuisine type, occasions, vibe).

The intended refresh loop is:
1. `discover_places` — populate/update the `places` table (run periodically or on-demand)
2. `place_knowledge` — build restaurant briefs (skipped if fresh), crawl websites, embed documents (run after discovery or after a report)
3. Brief generation automatically:
   - writes structured dish/behavior facts into `place_food_facts` via `extract_place_food_facts_from_brief()`
   - builds/merges `place_profiles` from the brief immediately via `_upsert_profile_from_brief()` — no LLM call, no signal required
4. Signal pipeline queries `place_food_facts` at enrichment time for high-confidence dish anchors, then retrieves `place_documents` via embedding similarity

**`place_profiles.known_for` is derived directly from `restaurant_brief.what_it_is`** — the gpt-4o web-search call that produces the brief also produces `known_for`. No separate LLM call is needed for profile generation.

To backfill all profiles and food_facts from existing restaurant briefs (e.g. after a schema change or first deploy):

```bash
python -m localsignal_engine.run_place_knowledge --build-profiles --extract-food-facts
```

To regenerate briefs (respects staleness window) and immediately rebuild profiles:

```bash
python -m localsignal_engine.run_place_knowledge --restaurant-brief --build-profiles
```

**Known gaps in Place Knowledge coverage (as of May 2026):**

- **Place discovery undercount**: `discover_places` finds ~150 places across Fort Lee, Edgewater, and Palisades Park. The actual number of food establishments is estimated 300–500+. Two root causes:
  1. **No pagination**: Google Places Text Search returns max 20 results per query; the current code does not follow `next_page_token` (up to 3 pages / 60 results available per query).
  2. **Sparse query set**: Only 7 query terms × 4 neighborhood targets = 28 queries. Missing: Chinese, Japanese, ramen, sushi, seafood boil, BBQ, bubble tea, pizza, brunch, and other common cuisines in the area.

- **Category granularity too coarse**: 82 of 150 places are classified as `restaurant` with no sub-category. This degrades category-based filtering. However, `place_profiles.food_types` now carries LLM-generated cuisine labels (e.g. "Korean BBQ", "Cajun / Seafood Boil") derived from the restaurant brief — these are more granular and should be used in preference to `places.category` for display and filtering.

- **Menu data thin**: Only 12 places have menu documents. Menus are the highest-signal source for dish names and price range context. Should be a priority data source (Yelp API, Google menu data, or website scraping).

- **Duplicate places**: At least one confirmed duplicate (`Kuppi Coffee Company` appears twice in Edgewater). Discovery deduplication relies on `google_place_id` uniqueness but the same business can appear under different query terms with slightly different metadata.

- **Partial staleness detection**: Restaurant briefs now have a staleness window (`PLACE_KNOWLEDGE_BRIEF_STALENESS_DAYS`, default 7 days) — stale briefs are regenerated weekly. However, there is still no mechanism to detect closed or relocated places, or to force re-generation after significant changes (new ownership, menu overhaul). A `last_verified_at` or manual invalidation flag would address this.

## Current Debt

- `signals.evidence` bag still carries several LLM narrative fields (`reader_hook`, `skeptic_note`, `good_for`, `watch_out`, `best_read_as`, etc.). These are currently only read by the API presenter layer. Avoid adding more durable place facts to it.
- `place_knowledge.py` owns prompts, validation, repair, brief generation, and food signal logic. Split it once the product contract stabilizes.
- `place_documents` has the vector index; `evidence_chunks.embedding` and `mentions.embedding` are available but not yet part of the active retrieval path.
- API still performs some fallback shaping for older rows. New code should move durable intelligence into tables first, then have API expose it cleanly.
- `place_food_facts` is now active: written by `extract_place_food_facts_from_brief()` after each restaurant brief generation, and queried by signal enrichment as high-confidence dish anchors. Any old `DISH_TERMS` regex extraction code predating this pipeline should be removed if found.
- `place_documents` conflates input documents (crawled content) and output documents (LLM-generated briefs). Consider a dedicated `place_briefs` table when the schema stabilizes.
- Existing restaurant briefs (generated before `cuisine_types`/`flavor_cues` were added to the schema) will have empty `food_types` and `flavor_cues` in `place_profiles` until briefs are regenerated. Force a refresh with `--restaurant-brief --build-profiles` or wait for the 7-day staleness window.

## API Structure

The FastAPI service (`services/api/app/`) is organized as follows:

```
app/
├── main.py                  # App init, middleware, router registration
├── routers/
│   ├── signals.py           # GET /signals, GET /signals/{slug}
│   ├── reports.py           # GET /reports/latest
│   ├── admin.py             # /api/* pipeline triggers + admin reads
│   └── engagement.py        # POST /feedback, POST /subscribers
├── presenters/
│   └── signals.py           # All helper functions: _signal_row, _metrics,
│                            #   _retrieve_candidate_evidence, _write_generated_signal, etc.
├── models.py                # Pydantic DTOs
├── pipeline.py              # Scoring and prompt utilities
├── openai_pipeline.py       # OpenAI embed + generate
├── db.py                    # Connection pool
└── config.py                # Settings
```

Router modules stay thin (HTTP concerns only). All shaping logic lives in `presenters/signals.py`.

## Near-Term Architecture Direction

1. Keep `place_profiles` as the canonical place profile source for durable computed fields. Profile updates use `merge_place_profile()` — accumulating list fields across weekly runs, never replacing them wholesale. The brief is the authoritative source and always does a full replace via `_upsert_profile_from_brief()`.
2. Keep restaurant briefs in `place_documents` (metadata + content) until volume warrants a dedicated table.
3. `signals.food_signal` is now a dedicated column — extend signal-specific fields there, not into the evidence bag.
4. Keep `place_documents` as the active RAG corpus; `place_food_facts` is the structured dish/behavior index layered on top.
5. `place_food_facts` is the right place for cross-signal, cross-week dish knowledge. It accumulates from briefs and is queried by signal enrichment as high-confidence anchors. Do not duplicate this into the evidence bag.
6. No rule-based keyword extraction for cuisine or flavor classification. The LLM is responsible for producing correct values in `cuisine_types` and `flavor_cues` as part of the restaurant brief. The system maps those fields directly with no post-processing.
6. Prefer explicit SQL/Python orchestration over a framework until retrieval becomes multi-hop or multi-agent.
7. Treat the web app as a rendering layer. Product intelligence should arrive through API DTOs, not be invented in React.
