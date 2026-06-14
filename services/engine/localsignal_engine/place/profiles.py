from typing import Any, Optional

from psycopg.types.json import Jsonb

from .schema import ensure_place_knowledge_schema
from .scraping import _clean_text, _string_list, _clean_json_value, _dedupe_display_values


def place_profile(conn, place_id: str) -> Optional[dict]:
    ensure_place_knowledge_schema(conn)
    row = conn.execute(
        """
        SELECT known_for, food_types, signature_items, flavor_cues, occasions, caveats, source_count, profile, updated_at::text
        FROM place_profiles
        WHERE place_id = %s
        """,
        (place_id,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def upsert_place_profile(conn, place_id: str, profile: dict) -> None:
    ensure_place_knowledge_schema(conn)
    conn.execute(
        """
        INSERT INTO place_profiles (
          place_id,
          known_for,
          food_types,
          signature_items,
          flavor_cues,
          occasions,
          caveats,
          source_count,
          instagram_handle,
          profile,
          updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
        ON CONFLICT (place_id)
        DO UPDATE SET
          known_for = EXCLUDED.known_for,
          food_types = EXCLUDED.food_types,
          signature_items = EXCLUDED.signature_items,
          flavor_cues = EXCLUDED.flavor_cues,
          occasions = EXCLUDED.occasions,
          caveats = EXCLUDED.caveats,
          source_count = EXCLUDED.source_count,
          -- Keep an existing handle if the new profile lacks one (signal merges omit it).
          instagram_handle = CASE
            WHEN EXCLUDED.instagram_handle <> '' THEN EXCLUDED.instagram_handle
            ELSE place_profiles.instagram_handle
          END,
          profile = EXCLUDED.profile,
          updated_at = now()
        """,
        (
            place_id,
            _clean_text(profile.get("known_for") or ""),
            _string_list(profile.get("food_types")),
            _string_list(profile.get("signature_items")),
            _string_list(profile.get("flavor_cues")),
            _string_list(profile.get("occasions")),
            _clean_text(profile.get("caveats") or ""),
            int(profile.get("source_count") or 0),
            _clean_text(profile.get("instagram_handle") or ""),
            Jsonb(_clean_json_value(profile)),
        ),
    )


def merge_place_profile(conn, place_id: str, new_profile: dict) -> None:
    """Merge new signal-derived profile data into existing place_profiles, accumulating lists across weeks."""
    existing = place_profile(conn, place_id)
    if not existing:
        upsert_place_profile(conn, place_id, new_profile)
        return

    def _merge_list(old: list, new: list) -> list:
        seen: set = set()
        merged: list = []
        for item in list(old) + list(new):
            key = str(item).strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(str(item).strip())
        return merged[:8]

    merged = dict(existing)
    # Always take the newer known_for if it's richer
    new_known = str(new_profile.get("known_for") or "").strip()
    old_known = str(merged.get("known_for") or "").strip()
    if new_known and len(new_known) > len(old_known):
        merged["known_for"] = new_known

    merged["food_types"] = _merge_list(merged.get("food_types") or [], new_profile.get("food_types") or [])
    merged["signature_items"] = _merge_list(merged.get("signature_items") or [], new_profile.get("signature_items") or [])
    merged["flavor_cues"] = _merge_list(merged.get("flavor_cues") or [], new_profile.get("flavor_cues") or [])
    merged["occasions"] = _merge_list(merged.get("occasions") or [], new_profile.get("occasions") or [])
    merged["source_count"] = max(int(merged.get("source_count") or 0), int(new_profile.get("source_count") or 0))
    if new_profile.get("caveats"):
        merged["caveats"] = new_profile["caveats"]

    upsert_place_profile(conn, place_id, merged)
