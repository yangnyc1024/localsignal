from localsignal_engine.models import Place
from localsignal_engine.db.connection import get_conn
from localsignal_engine.place.names import display_place_name


def load_places() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id::text, name, category, city, neighborhood, latitude, longitude, google_place_id, map_url, display_name
            FROM places
            ORDER BY city, name
            """
        ).fetchall()
    return [
        Place(
            id=row[0],
            name=row[1],
            category=row[2],
            city=row[3],
            neighborhood=row[4],
            latitude=row[5],
            longitude=row[6],
            google_place_id=row[7],
            map_url=row[8],
            display_name=row[9] or display_place_name(row[1]),
        )
        for row in rows
    ]


def upsert_places_from_discovery(places: list) -> int:
    if not places:
        return 0

    written = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_places_google_place_id ON places(google_place_id) WHERE google_place_id IS NOT NULL"
            )
            for place in places:
                cur.execute(
                    """
                    INSERT INTO places (
                      name,
                      display_name,
                      category,
                      address,
                      city,
                      neighborhood,
                      latitude,
                      longitude,
                      google_place_id,
                      map_url
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (google_place_id) WHERE google_place_id IS NOT NULL
                    DO UPDATE SET
                      name = EXCLUDED.name,
                      display_name = EXCLUDED.display_name,
                      category = EXCLUDED.category,
                      address = EXCLUDED.address,
                      city = EXCLUDED.city,
                      neighborhood = EXCLUDED.neighborhood,
                      latitude = EXCLUDED.latitude,
                      longitude = EXCLUDED.longitude,
                      map_url = EXCLUDED.map_url
                    RETURNING id
                    """,
                    (
                        place["name"],
                        display_place_name(place["name"]),
                        place["category"],
                        place.get("address"),
                        place["city"],
                        place.get("neighborhood"),
                        place.get("latitude"),
                        place.get("longitude"),
                        place.get("google_place_id"),
                        place.get("map_url"),
                    ),
                )
                if cur.fetchone():
                    written += 1
        conn.commit()
    return written
