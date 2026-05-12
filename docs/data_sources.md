# Data Sources

## Configured Public Sources

### Reddit

Configured:

```bash
REDDIT_SUBREDDITS=newjersey,bergencounty,fortlee
```

Notes:

- `bergencounty` is directly relevant to the MVP geography.
- `newjersey` is broader but useful for regional spillover.
- `fortlee` is included as a candidate; if it produces no data, remove or replace it.

### RSS

Configured:

```bash
RSS_FEED_URLS=https://www.boozyburbs.com/feed/,https://www.fortleenj.org/RSSFeed.aspx?CID=All-newsflash.xml&ModID=1,https://www.edgewaternj.org/RSSFeed.aspx?CID=Edgewater-News-8&ModID=1
```

Sources:

- Boozy Burbs: Bergen County dining and nightlife coverage.
- Fort Lee official CivicEngage RSS: borough news flash.
- Edgewater official CivicEngage RSS: borough news flash.

### Google News RSS

Configured:

```bash
GOOGLE_NEWS_ENABLED=true
```

The engine generates Google News RSS searches for each tracked place.

## API Sources To Add

### Yelp Places API

Create a Yelp app and get a private API key:

https://docs.developer.yelp.com/docs/fusion-authentication

Then configure:

```bash
YELP_API_KEY=...
```

### Google Places API

Create a Google Cloud project, enable Places API, attach billing, and restrict the API key:

https://developers.google.com/maps/documentation/places/web-service/get-api-key

Then configure:

```bash
GOOGLE_PLACES_API_KEY=...
```

## Email

Resend API keys should remain local environment secrets and must not be committed:

https://resend.com/docs/dashboard/api-keys/introduction
