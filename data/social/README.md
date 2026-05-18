# Social Metadata Imports

Put authorized Instagram, TikTok, and Xiaohongshu metadata JSON files here for Docker runs.

Suggested paths inside `.env`:

```bash
INSTAGRAM_JSON_PATH=/data/social/instagram.json
TIKTOK_JSON_PATH=/data/social/tiktok.json
XHS_JSON_PATH=/data/social/xiaohongshu.json
```

You can also provide comma-separated files, for example:

```bash
XHS_JSON_PATH=/data/social/xhs-week1.json,/data/social/xhs-week2.json
```

Real JSON data files in this folder are gitignored. Keep only this README and small schema examples in the repo.

## Automatic Inbox

Put authorized social metadata exports in `data/social/inbox/`. Docker maps this directory to `/data/social/inbox`, and the evidence ingestion job scans every `.json` and `.jsonl` file when `SOCIAL_JSON_DIR=/data/social/inbox` is set.

Recommended flow:

1. A compliant export job writes files into `data/social/inbox/`.
2. Run `make validate-social SOCIAL_JSON_PATHS=data/social/inbox`.
3. Run `make docker-evidence` or let the daily scheduler pick it up.
4. Run `make docker-report` for a refreshed feed/report.

Do not commit real exports. This directory is intentionally ignored by git for JSON/JSONL/CSV files.
