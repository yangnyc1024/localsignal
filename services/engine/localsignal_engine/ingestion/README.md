# Ingestion Adapters

This directory is the boundary for crawlers and source integrations.

MVP-safe order:

1. `local_json`: manually exported or curated mentions.
2. Reddit API adapter.
3. Local blog RSS/sitemap adapter.
4. Review platform API/import adapter.

Direct scraping of Google, Yelp, TikTok, Instagram, or Xiaohongshu should not be added here without a source-specific legal and product review.
