# Social Metadata Compliance Intake

LocalSignal can ingest TikTok, Instagram, and Xiaohongshu metadata, but the product should not directly scrape those platforms in the MVP.

Use this intake path for real social data:

1. Collect only public or authorized metadata.
2. Keep the original source URL.
3. Store a short caption/summary, OCR text, place hints, timestamp, and engagement counts.
4. Do not store private messages, contact info, cookies, account tokens, or full media files.
5. Keep enough audit context to explain where the item came from.
6. Let entity resolution decide whether an item is resolved, review, or unresolved.

## Accepted Collection Methods

- Manual public observation: a human records public post metadata and URL.
- Creator/business authorization: the post owner or business provides the metadata.
- Platform-approved API/export: official APIs or account-owned exports.
- Third-party export vendor: only if the vendor and usage terms allow this data collection.

## Required Fields

- `source`: `instagram`, `tiktok`, `tiktok_metadata`, `xhs`, or `xiaohongshu`
- `source_url`: canonical post/note/video URL
- one text field: `caption`, `text`, `body`, `description`, `title`, `note_title`, or `ocr_text`
- one timestamp field: `occurred_at`, `timestamp`, `created_at`, `published_at`, or `taken_at`

## Strongly Recommended Fields

- `place_id`: best option when the place is known
- `place_name`, `venue`, `location_name`, or `business_name`
- `possible_place_names`: alternate names from OCR, Chinese/Korean names, or hashtags
- `likes`, `comments`, `views`, `shares`, `saves`
- `collection_method`: example `manual_public_observation`, `creator_authorized_export`
- `collector`: person or internal process that collected the metadata

## Do Not Import

- private messages, follower lists, cookies, access tokens, or session data
- phone numbers, emails, or personal contact info
- full videos/images unless a later review approves media storage
- claims that are not visible in the source metadata

Run validation before ingestion:

```bash
make validate-social SOCIAL_JSON_PATHS=data/social/instagram.json,data/social/tiktok.json,data/social/xiaohongshu.json
```

Then ingest:

```bash
make docker-evidence
make docker-report
```

## Automatic Import Pattern

The compliant automation path is acquisition outside LocalSignal, ingestion inside LocalSignal:

1. Use a platform-approved API, account-owned export, creator/business authorized export, or a third-party vendor whose terms allow metadata collection.
2. Configure that job to write JSON or JSONL files into `data/social/inbox/`.
3. Keep one record per public post/note/video with source URL, timestamp, visible text/OCR, place hints, engagement metrics, and collection audit fields.
4. LocalSignal automatically scans `/data/social/inbox` during `pipeline.evidence` when `SOCIAL_JSON_DIR=/data/social/inbox`.
5. Ambiguous place matches remain review/unresolved and do not become published signals until supported by evidence.

This keeps platform-specific collection separate from the signal engine, so we can swap manual exports, Apify/Bright Data-style exports, Make/Zapier jobs, or official APIs without changing signal detection.

## Apify Dataset Connector

LocalSignal can read Apify dataset items directly during evidence ingestion. Use this only with actors/datasets whose collection terms are acceptable for the product. The adapter reads structured metadata from Apify; it does not automate platform login or scrape pages itself.

Set these values in `.env`:

```bash
APIFY_TOKEN=your_apify_api_token
APIFY_SOCIAL_DATASET_IDS=dataset_id_1,dataset_id_2
APIFY_SOCIAL_MAX_ITEMS=200
```

Then run:

```bash
make docker-evidence
make docker-report
```

Each dataset item should include at least a post URL, timestamp, visible text/caption/OCR, and place hint. The connector normalizes common export fields such as `postUrl`, `webVideoUrl`, `description`, `createTimeISO`, `locationName`, and `poiName`.

## Recency Gate

Social metadata is filtered by `SOCIAL_MAX_AGE_DAYS` before it becomes evidence. The default is 45 days. This prevents old Instagram/TikTok/Xiaohongshu posts from being treated as current local signals. Set the value to `0` only for backfills or baseline experiments.

