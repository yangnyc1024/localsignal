from datetime import datetime, timedelta, timezone

from localsignal_engine.models import Mention, Place

NOW = datetime.now(timezone.utc)

PLACES = [
    Place(
        id="11111111-1111-1111-1111-111111111111",
        name="BCD Tofu House",
        category="restaurant",
        city="Fort Lee",
        neighborhood="Schlosser Street",
    ),
    Place(
        id="22222222-2222-2222-2222-222222222222",
        name="Kuppi Coffee Company",
        category="cafe",
        city="Edgewater",
        neighborhood="River Road",
    ),
    Place(
        id="33333333-3333-3333-3333-333333333333",
        name="So Gong Dong Tofu & BBQ",
        category="restaurant",
        city="Palisades Park",
        neighborhood="Broad Avenue",
    ),
]

MENTIONS = [
    Mention(
        place_id=PLACES[0].id,
        source="google_reviews",
        body="The soon tofu is worth the line. Saw people coming from Manhattan for bubbling bowls.",
        author_region="Manhattan",
        rating=5,
        sentiment=0.91,
        occurred_at=NOW - timedelta(days=1),
    ),
    Mention(
        place_id=PLACES[0].id,
        source="reddit",
        body="BCD Tofu House in Fort Lee is suddenly everywhere in my group chats for late tofu soup.",
        author_region="Jersey City",
        sentiment=0.88,
        occurred_at=NOW - timedelta(days=2),
    ),
    Mention(
        place_id=PLACES[0].id,
        source="google_reviews",
        body="Long line but the banchan, seafood pancake, and soon dubu are excellent.",
        author_region="Fort Lee",
        rating=5,
        sentiment=0.86,
        occurred_at=NOW - timedelta(days=3),
    ),
    Mention(
        place_id=PLACES[1].id,
        source="yelp",
        body="Quiet weekday cafe with reliable wifi, river views, and plenty of outlets.",
        author_region="Edgewater",
        rating=5,
        sentiment=0.83,
        occurred_at=NOW - timedelta(days=1),
    ),
    Mention(
        place_id=PLACES[1].id,
        source="google_reviews",
        body="Kuppi is a good place to work remotely in the afternoon. Quiet, clean, outlet near most seats.",
        author_region="Hoboken",
        rating=5,
        sentiment=0.84,
        occurred_at=NOW - timedelta(days=2),
    ),
    Mention(
        place_id=PLACES[2].id,
        source="google_reviews",
        body="Soft tofu is still good but service felt slower and the wait was rough.",
        author_region="Palisades Park",
        rating=3,
        sentiment=-0.22,
        occurred_at=NOW - timedelta(days=1),
    ),
    Mention(
        place_id=PLACES[2].id,
        source="google_reviews",
        body="Crowded dinner at So Gong Dong, waited a long time, service was overwhelmed.",
        author_region="Fort Lee",
        rating=3,
        sentiment=-0.28,
        occurred_at=NOW - timedelta(days=4),
    ),
]
