import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from localsignal_engine.models import Place


def compute_baseline_profiles(conn, places: list[Place]) -> int:
    updated = 0
    now = datetime.now(timezone.utc)
    for place in places:
        rows = conn.execute(
            """
            SELECT platform, text, occurred_at
            FROM raw_source_items
            WHERE place_id = %s
              AND occurred_at >= %s
            UNION ALL
            SELECT source AS platform, body AS text, occurred_at
            FROM mentions
            WHERE place_id = %s
              AND occurred_at >= %s
            """,
            (place.id, now - timedelta(days=365), place.id, now - timedelta(days=365)),
        ).fetchall()
        profile = _profile_for(place, rows, now)
        conn.execute(
            """
            INSERT INTO baseline_profiles (
              place_id,
              trailing_30d_mentions,
              trailing_90d_mentions,
              trailing_365d_mentions,
              source_diversity,
              recurring_keywords,
              baseline_heat_score,
              baseline_status,
              baseline_summary,
              last_updated
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (place_id)
            DO UPDATE SET
              trailing_30d_mentions = EXCLUDED.trailing_30d_mentions,
              trailing_90d_mentions = EXCLUDED.trailing_90d_mentions,
              trailing_365d_mentions = EXCLUDED.trailing_365d_mentions,
              source_diversity = EXCLUDED.source_diversity,
              recurring_keywords = EXCLUDED.recurring_keywords,
              baseline_heat_score = EXCLUDED.baseline_heat_score,
              baseline_status = EXCLUDED.baseline_status,
              baseline_summary = EXCLUDED.baseline_summary,
              last_updated = now()
            """,
            (
                place.id,
                profile["trailing_30d_mentions"],
                profile["trailing_90d_mentions"],
                profile["trailing_365d_mentions"],
                profile["source_diversity"],
                profile["recurring_keywords"],
                profile["baseline_heat_score"],
                profile["baseline_status"],
                profile["baseline_summary"],
            ),
        )
        updated += 1
    conn.commit()
    return updated


def _profile_for(place: Place, rows: list[tuple], now: datetime) -> dict:
    trailing_30 = [row for row in rows if row[2] >= now - timedelta(days=30)]
    trailing_90 = [row for row in rows if row[2] >= now - timedelta(days=90)]
    source_diversity = len({row[0] for row in rows})
    keywords = _recurring_keywords([row[1] for row in rows])
    heat_score = _heat_score(len(trailing_30), len(trailing_90), len(rows), source_diversity)
    status = _status(heat_score, len(rows))
    return {
        "trailing_30d_mentions": len(trailing_30),
        "trailing_90d_mentions": len(trailing_90),
        "trailing_365d_mentions": len(rows),
        "source_diversity": source_diversity,
        "recurring_keywords": keywords,
        "baseline_heat_score": heat_score,
        "baseline_status": status,
        "baseline_summary": _summary(place, status, heat_score, len(rows), source_diversity, keywords),
    }


def _recurring_keywords(texts: list[str]) -> list[str]:
    stopwords = {
        "and",
        "all",
        "always",
        "are",
        "but",
        "can",
        "day",
        "the",
        "for",
        "font",
        "with",
        "this",
        "that",
        "they",
        "she",
        "her",
        "him",
        "had",
        "has",
        "have",
        "not",
        "from",
        "get",
        "place",
        "food",
        "good",
        "very",
        "was",
        "were",
        "when",
        "which",
        "will",
        "would",
        "you",
        "your",
        "relative",
        "time",
        "author",
        "rating",
        "nbsp",
    }
    counter: Counter[str] = Counter()
    for text in texts:
        words = re.findall(r"[a-z][a-z0-9'-]{2,}", text.lower())
        counter.update(word for word in words if word not in stopwords)
    return [word for word, count in counter.most_common(8) if count >= 1][:6]


def _heat_score(count_30: int, count_90: int, count_365: int, source_diversity: int) -> float:
    score = min(count_30 * 9, 30) + min(count_90 * 4, 25) + min(count_365 * 1.5, 25) + min(source_diversity * 10, 20)
    return round(min(score, 100), 2)


def _status(score: float, count_365: int) -> str:
    if score >= 70:
        return "Established hot spot"
    if score >= 45:
        return "Warm baseline"
    if count_365 <= 1:
        return "Quiet baseline"
    return "Emerging baseline"


def _summary(place: Place, status: str, score: float, count_365: int, source_diversity: int, keywords: list[str]) -> str:
    if count_365 == 0:
        return f"{place.name} does not yet have enough long-window evidence to establish baseline heat."
    keyword_text = ", ".join(keywords[:3]) if keywords else "general food interest"
    return (
        f"{place.name} is classified as {status.lower()} with a {score:.1f} baseline heat score, "
        f"based on {count_365} long-window item(s), {source_diversity} source type(s), and recurring language around {keyword_text}."
    )
