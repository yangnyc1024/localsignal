# Ingestion Adapters

This directory is the boundary for crawlers and source integrations.

Current MVP-safe sources:

1. `local_json`: manually exported or curated mentions.
2. `reddit`: public JSON search for configured subreddits.
3. `rss`: RSS/Atom local blog feeds.
4. Review platform API/import adapter.

Direct scraping of Google, Yelp, TikTok, Instagram, or Xiaohongshu should not be added here without a source-specific legal and product review.
