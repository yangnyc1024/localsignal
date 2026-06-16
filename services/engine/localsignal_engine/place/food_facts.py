from typing import Any, Optional

from .documents import _text_hash, _clean_text


def extract_place_food_facts_from_brief(conn, place_id: str, brief: dict) -> int:
    """Persist dish facts from a restaurant_brief into place_food_facts for cross-signal reuse."""
    items: list = brief.get("signature_menu_items") or []
    highlight_items: list = brief.get("highlight_items") or []
    written = 0
    for raw in items:
        text = _clean_text(str(raw or ""))
        if not text:
            continue
        dish_name = text.split(" - ")[0].strip()
        normalized = dish_name.lower()
        evidence_hash = _text_hash(f"{place_id}:dish:{normalized}")
        conn.execute(
            """
            INSERT INTO place_food_facts (
              place_id, fact_type, fact_value, normalized_value,
              evidence_text, source, confidence, evidence_hash
            )
            VALUES (%s, 'dish', %s, %s, %s, 'restaurant_brief', 0.7, %s)
            ON CONFLICT (place_id, fact_type, normalized_value, evidence_hash) DO UPDATE SET
              fact_value = EXCLUDED.fact_value,
              evidence_text = EXCLUDED.evidence_text,
              confidence = GREATEST(place_food_facts.confidence, EXCLUDED.confidence),
              updated_at = now()
            """,
            (place_id, dish_name, normalized, text, evidence_hash),
        )
        written += 1
    for h in highlight_items:
        aspect = _clean_text(str(h.get("aspect") or ""))
        detail = _clean_text(str(h.get("detail") or ""))
        if not aspect or not detail:
            continue
        normalized = aspect.lower()
        evidence_hash = _text_hash(f"{place_id}:behavior:{normalized}")
        conn.execute(
            """
            INSERT INTO place_food_facts (
              place_id, fact_type, fact_value, normalized_value,
              evidence_text, source, confidence, evidence_hash
            )
            VALUES (%s, 'behavior', %s, %s, %s, 'restaurant_brief', 0.6, %s)
            ON CONFLICT (place_id, fact_type, normalized_value, evidence_hash) DO UPDATE SET
              evidence_text = EXCLUDED.evidence_text,
              updated_at = now()
            """,
            (place_id, aspect, normalized, detail, evidence_hash),
        )
        written += 1
    return written


def get_place_food_facts(conn, place_id: str, fact_type: Optional[str] = None, min_confidence: float = 0.5) -> list:
    """Retrieve persisted food facts for a place, ordered by confidence."""
    if fact_type:
        rows = conn.execute(
            """
            SELECT fact_type, fact_value, normalized_value, evidence_text, source, confidence
            FROM place_food_facts
            WHERE place_id = %s AND fact_type = %s AND confidence >= %s
            ORDER BY confidence DESC, updated_at DESC
            LIMIT 20
            """,
            (place_id, fact_type, min_confidence),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT fact_type, fact_value, normalized_value, evidence_text, source, confidence
            FROM place_food_facts
            WHERE place_id = %s AND confidence >= %s
            ORDER BY confidence DESC, updated_at DESC
            LIMIT 30
            """,
            (place_id, min_confidence),
        ).fetchall()
    return [dict(row) for row in rows]
