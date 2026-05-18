# Ingestion Adapters

This directory is the boundary for crawlers and source integrations.

Current MVP-safe sources:

1. `local_json`: manually exported or curated mentions.
2. `reddit`: public JSON search for configured subreddits.
3. `rss`: RSS/Atom local blog feeds.
4. `google_news`: Google News RSS search.
5. `yelp_fusion`: Yelp Fusion API when `YELP_API_KEY` is configured.
6. `google_places`: Google Places Text Search API when `GOOGLE_PLACES_API_KEY` is configured.

Direct scraping of Google, Yelp, TikTok, Instagram, or Xiaohongshu should not be added here without a source-specific legal and product review.
## TikTok / Instagram / Xiaohongshu metadata imports

LocalSignal does not scrape TikTok, Instagram, or Xiaohongshu. To ingest social video/photo data,
export or collect authorized metadata and load it through the social metadata
adapter.

Set:

```bash
INSTAGRAM_JSON_PATH=/absolute/path/to/instagram_mentions.json
TIKTOK_JSON_PATH=/absolute/path/to/tiktok_mentions.json
XHS_JSON_PATH=/absolute/path/to/xiaohongshu_mentions.json
```

Expected record shape:

```json
[
  {
    "place_id": "11111111-1111-1111-1111-111111111111",
    "place_name": "Kuppi Coffee Company",
    "source": "instagram",
    "source_url": "https://www.instagram.com/p/...",
    "caption": "Caption text or manually normalized media metadata.",
    "ocr_text": "Optional image OCR text, useful for Xiaohongshu screenshots.",
    "possible_place_names": ["Optional alternate names, Chinese names, or OCR-derived candidates"],
    "likes": 120,
    "comments": 8,
    "views": 2400,
    "author_region": "Fort Lee",
    "occurred_at": "2026-05-12T12:00:00+00:00"
  }
]
```

`place_id` is preferred. If it is missing, the adapter tries to match
`place_name`, `venue`, `location_name`, `business_name`, or caption text against
known places. Engagement metrics are preserved in `raw_source_items`. Platform aliases such as `xhs`, `小红书`, and `rednote` are normalized to `xiaohongshu`.


Before importing a new social metadata file, run the compliance validator from the repo root:

```bash
make validate-social SOCIAL_JSON_PATHS=data/social/instagram.json,data/social/tiktok.json,data/social/xiaohongshu.json
```

The validator blocks missing source URLs, missing timestamps, missing text, invalid JSON, and obvious private/sensitive fields. Warnings are allowed for weak place hints, but those items will usually remain in review/unresolved until they are manually resolved.

For automated imports, set `APIFY_TOKEN` and `APIFY_SOCIAL_DATASET_IDS`. Evidence ingestion will fetch dataset items from Apify, normalize common export fields, and route them through the same social metadata parser. This is similar to the Google Places adapter pattern: configured source, fetch structured data, normalize, then write raw/evidence records.
