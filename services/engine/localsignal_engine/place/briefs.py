import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

from .schema import ensure_place_knowledge_schema
from .documents import RESTAURANT_BRIEF_SOURCE, upsert_place_document, _clean_text
from .scraping import _places, _dedupe_display_values
from .profiles import upsert_place_profile
from .food_facts import extract_place_food_facts_from_brief

BRIEF_STALENESS_DAYS = int(os.getenv("PLACE_KNOWLEDGE_BRIEF_STALENESS_DAYS", "7"))


def _brief_is_fresh(conn, place_id: str) -> bool:
    row = conn.execute(
        """
        SELECT updated_at FROM place_documents
        WHERE place_id = %s AND content_type = 'restaurant_brief'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (place_id,),
    ).fetchone()
    if not row:
        return False
    age = datetime.now(timezone.utc) - row["updated_at"].replace(tzinfo=timezone.utc)
    return age.days < BRIEF_STALENESS_DAYS


def _brief_doc(row: dict) -> dict:
    return {
        "title": row.get("title") or "",
        "source": row.get("source") or "",
        "source_url": row.get("source_url"),
        "content": _clean_text(row.get("content") or "")[:2500],
        "metadata": row.get("metadata") or {},
    }


def _brief_location_format(place: dict) -> str:
    area = place.get("neighborhood") or place.get("city") or "the local area"
    return f"{area} · {place.get('category') or 'restaurant'}"


def _restaurant_brief_context(conn, place_id: str) -> dict:
    official_documents = conn.execute(
        """
        SELECT title, content, source, source_url, metadata
        FROM place_documents
        WHERE place_id = %s
          AND content_type = 'official_description'
        ORDER BY fetched_at DESC
        LIMIT 4
        """,
        (place_id,),
    ).fetchall()
    menu_documents = conn.execute(
        """
        SELECT title, content, source, source_url, metadata
        FROM place_documents
        WHERE place_id = %s
          AND content_type = 'menu'
        ORDER BY fetched_at DESC
        LIMIT 3
        """,
        (place_id,),
    ).fetchall()
    return {
        "official_documents": [_brief_doc(row) for row in official_documents],
        "menu_documents": [_brief_doc(row) for row in menu_documents],
    }


def _parse_llm_json(value: str) -> dict:
    cleaned = _clean_text(value)
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    return data if isinstance(data, dict) else {}


def _repair_restaurant_brief(place: dict, data: dict, context: dict) -> dict:
    source_chips: list = []
    if any(doc.get("source") == "website" for doc in context.get("official_documents") or []):
        source_chips.append("Official website")
    if any(doc.get("source") == "google_places" for doc in context.get("official_documents") or []):
        source_chips.append("Google profile")
    if context.get("menu_documents"):
        source_chips.append("Menu")
    if not source_chips:
        source_chips.append("Web search")
    what_it_is = _clean_text(data.get("what_it_is") or "")
    if not what_it_is:
        what_it_is = f"{place['name']} is a local restaurant in {place.get('neighborhood') or place.get('city') or 'the area'}."
    raw_highlights = data.get("highlight_items") or []
    highlight_items = [
        {"aspect": _clean_text(h.get("aspect") or ""), "detail": _clean_text(h.get("detail") or "")}
        for h in raw_highlights
        if isinstance(h, dict) and _clean_text(h.get("aspect") or "") and _clean_text(h.get("detail") or "")
    ][:4]
    cuisine_types = _dedupe_display_values(data.get("cuisine_types") or [])[:3]
    flavor_cues = _dedupe_display_values(data.get("flavor_cues") or [])[:4]
    return {
        "what_it_is": what_it_is,
        "cuisine_types": cuisine_types,
        "flavor_cues": flavor_cues,
        "official_context_note": _clean_text(data.get("official_context_note") or "Official context, not signal evidence."),
        "signature_menu_items": _dedupe_display_values(data.get("signature_menu_items") or [])[:8],
        "highlight_items": highlight_items,
        "location_format": _clean_text(data.get("location_format") or _brief_location_format(place)),
        "vibe_tags": [_clean_text(t) for t in (data.get("vibe_tags") or []) if _clean_text(t)][:5],
        "occasions": [_clean_text(o) for o in (data.get("occasions") or []) if _clean_text(o)][:4],
        "source_chips": source_chips[:5],
        "trust_note": _clean_text(data.get("trust_note") or "Restaurant brief is context only; recent movement is handled in the signal sections below."),
    }


def _generate_restaurant_brief(place: dict, context: dict) -> Optional[dict]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    place_name = place.get("name") or ""
    city = place.get("city") or place.get("neighborhood") or ""
    search_hint = f"{place_name} {city}".strip()
    instructions = [
        f"You are researching a local restaurant called '{place_name}' in {city} for a food discovery product.",
        f"Use the web_search tool to search for '{search_hint} restaurant' to find food reviews, articles, food blogs, or any content that describes what makes this place distinctive.",
        "Also use the provided official documents and food facts.",
        "Produce a Restaurant Brief with these structured fields. Be specific and concrete — name actual dishes, flavors, and characteristics. Write 3-4 sentences for what_it_is.",
        "For cuisine_types: 1-3 specific cuisine or food-category labels (e.g. 'Korean BBQ', 'Cajun Seafood', 'Japanese Ramen', 'Bakery / Café'). Be specific — not just 'Restaurant' or 'Food'. Only what is supported by evidence.",
        "For flavor_cues: 2-4 short food or taste descriptors that capture what the food is like (e.g. 'grilled meat', 'spicy broth', 'crispy cutlet', 'fresh seafood', 'house-made pastry'). These must describe taste, texture, or ingredients — not atmosphere, format, or service. Do not include words like 'cozy', 'sit-down', 'generous portions', or 'work-friendly'.",
        "For highlight_items: extract 3-4 things that make this place distinctive. Each item needs a short aspect label (e.g. 'The Sauce', 'The Portion', 'The Atmosphere') and a 1-2 sentence detail. Only include what is supported by evidence.",
        "For signature_menu_items: list each dish as 'Dish Name - brief description of what it is'. Include up to 6 items.",
        "For vibe_tags: 3-5 short descriptors about dining format or atmosphere (e.g. 'Sit-down', 'BYOB', 'Counter seating', 'Group-friendly'). Only what is supported.",
        "For occasions: 2-4 typical visit occasions (e.g. 'Date night', 'Family dinner', 'Late-night stop'). Do not invent.",
        "Avoid recommendation language: no 'must try', 'best', 'top rated', 'you should'.",
        "Output valid JSON only.",
    ]
    prompt = {
        "instructions": instructions,
        "place": place,
        "context": context,
        "json_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["what_it_is", "cuisine_types", "flavor_cues", "official_context_note", "signature_menu_items", "highlight_items", "location_format", "vibe_tags", "occasions", "source_chips", "trust_note"],
            "properties": {
                "what_it_is": {"type": "string"},
                "cuisine_types": {"type": "array", "items": {"type": "string"}},
                "flavor_cues": {"type": "array", "items": {"type": "string"}},
                "official_context_note": {"type": "string"},
                "signature_menu_items": {"type": "array", "items": {"type": "string"}},
                "highlight_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["aspect", "detail"],
                        "properties": {
                            "aspect": {"type": "string"},
                            "detail": {"type": "string"},
                        },
                    },
                },
                "location_format": {"type": "string"},
                "vibe_tags": {"type": "array", "items": {"type": "string"}},
                "occasions": {"type": "array", "items": {"type": "string"}},
                "source_chips": {"type": "array", "items": {"type": "string"}},
                "trust_note": {"type": "string"},
            },
        },
    }
    model = os.getenv("OPENAI_MODEL_RICH", "gpt-4o")
    try:
        from openai import OpenAI, RateLimitError, APIConnectionError, APITimeoutError, OpenAIError
    except ImportError:
        return None

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    retryable = (RateLimitError, APIConnectionError, APITimeoutError)
    last_exc = None
    for attempt in range(3):
        try:
            response = client.responses.create(
                model=model,
                tools=[{"type": "web_search_preview"}],
                input=[
                    {"role": "system", "content": "You research local restaurants using web search and provided documents. Return JSON only."},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
            )
            break
        except retryable as exc:
            last_exc = exc
            time.sleep(1.5 * (2 ** attempt))
        except OpenAIError:
            return None
    else:
        return None

    try:
        data = _parse_llm_json(response.output_text)
    except json.JSONDecodeError:
        return None
    return _repair_restaurant_brief(place, data, context)


def _restaurant_brief_content(place: dict, brief: dict) -> str:
    return "\n".join(
        [
            f"Restaurant Brief for {place['name']}",
            f"What it is: {brief['what_it_is']}",
            f"Official / stable context: {brief['official_context_note']}",
            f"Signature menu items: {', '.join(brief['signature_menu_items']) if brief['signature_menu_items'] else 'Not enough menu facts yet.'}",
            f"Location / format: {brief['location_format']}",
            f"Sources: {', '.join(brief['source_chips'])}",
            f"Trust note: {brief['trust_note']}",
        ]
    )


def _upsert_profile_from_brief(conn, place: dict, brief_metadata: dict) -> None:
    """Map a restaurant_brief metadata dict to place_profiles columns and upsert.

    Uses LLM-generated fields directly — no keyword extraction or post-processing:
      what_it_is        → known_for
      cuisine_types     → food_types   (LLM-generated cuisine labels)
      flavor_cues       → flavor_cues  (LLM-generated taste/ingredient descriptors)
      signature_menu_items → signature_items
      occasions         → occasions

    Brief is the authoritative source — always replaces, not merges.
    merge_place_profile() is for signal-derived incremental updates.
    """
    what_it_is = _clean_text(brief_metadata.get("what_it_is") or "")
    if not what_it_is:
        return

    raw_items: list = brief_metadata.get("signature_menu_items") or []
    signature_items = _dedupe_display_values([item.split(" - ")[0].strip() for item in raw_items])[:8]
    food_types = _dedupe_display_values(brief_metadata.get("cuisine_types") or [])[:3]
    flavor_cues = _dedupe_display_values(brief_metadata.get("flavor_cues") or [])[:4]
    occasions = [_clean_text(o) for o in (brief_metadata.get("occasions") or []) if _clean_text(o)]

    source_docs = brief_metadata.get("source_documents") or {}
    profile = {
        "known_for": what_it_is,
        "food_types": food_types,
        "signature_items": signature_items,
        "flavor_cues": flavor_cues,
        "occasions": occasions,
        "caveats": _clean_text(brief_metadata.get("trust_note") or "Profile is derived from restaurant brief; keep claims limited to context only."),
        "source_count": int(source_docs.get("official") or 0) + int(source_docs.get("menu") or 0) + len(signature_items),
    }
    upsert_place_profile(conn, place["id"], profile)


def build_restaurant_brief_documents(conn, place_ids: Optional[list] = None) -> int:
    """Generate restaurant briefs concurrently, write results serially.

    LLM + web_search calls (the slow part) run in a thread pool.
    All DB writes happen in the calling thread using the provided conn.
    Concurrency controlled by PLACE_KNOWLEDGE_BRIEF_MAX_WORKERS (default 4).
    """
    ensure_place_knowledge_schema(conn)
    if not os.getenv("OPENAI_API_KEY"):
        return 0

    places = [p for p in _places(conn, place_ids) if not _brief_is_fresh(conn, p["id"])]
    if not places:
        return 0

    max_workers = int(os.getenv("PLACE_KNOWLEDGE_BRIEF_MAX_WORKERS", "4"))

    def _generate_one(place: dict) -> Optional[tuple[dict, dict, dict]]:
        """Return (place, brief, context) or None on failure. Runs in worker thread."""
        try:
            context = _restaurant_brief_context(conn, place["id"])
            brief = _generate_restaurant_brief(place, context)
            if brief:
                return place, brief, context
        except Exception as exc:
            logger.warning("Brief generation failed for %s: %s", place.get("name"), exc)
        return None

    written = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_generate_one, place): place for place in places}
        for future in as_completed(futures):
            result = future.result()
            if not result:
                continue
            place, brief, context = result
            content = _restaurant_brief_content(place, brief)
            full_metadata = {
                **brief,
                "source_type": "llm_generated_context",
                "trust_level": "context_only",
                "source_documents": {
                    "official": len(context["official_documents"]),
                    "menu": len(context["menu_documents"]),
                },
            }
            if upsert_place_document(
                conn,
                place_id=place["id"],
                source=RESTAURANT_BRIEF_SOURCE,
                source_url=f"localsignal://restaurant-brief/{place['id']}",
                title=f"Restaurant brief for {place['name']}",
                content=content,
                content_type="restaurant_brief",
                metadata=full_metadata,
            ):
                written += 1
                logger.info("Brief written for %s.", place.get("name"))
                extract_place_food_facts_from_brief(conn, place["id"], brief)
                _upsert_profile_from_brief(conn, place, full_metadata)
    return written


def build_place_profiles_from_briefs(conn, place_ids: Optional[list] = None) -> int:
    """Offline-build place_profiles for all places that have a restaurant_brief.

    Maps LLM-generated brief fields directly — no keyword extraction:
      what_it_is        → known_for
      cuisine_types     → food_types   (LLM-generated cuisine labels)
      flavor_cues       → flavor_cues  (LLM-generated taste/ingredient descriptors)
      signature_menu_items → signature_items
      occasions         → occasions
    """
    ensure_place_knowledge_schema(conn)
    place_filter = "AND pd.place_id = ANY(%s::uuid[])" if place_ids else ""
    params = (place_ids,) if place_ids else ()
    rows = conn.execute(
        f"""
        SELECT
          pd.place_id::text AS place_id,
          p.name,
          p.category,
          pd.metadata,
          pd.fetched_at
        FROM place_documents pd
        JOIN places p ON p.id = pd.place_id
        WHERE pd.content_type = 'restaurant_brief'
          AND pd.metadata ? 'what_it_is'
          {place_filter}
        ORDER BY pd.fetched_at DESC
        """,
        params,
    ).fetchall()

    seen: set = set()
    written = 0
    for row in rows:
        place_id = row["place_id"]
        if place_id in seen:
            continue
        seen.add(place_id)
        brief_metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
        if not _clean_text(brief_metadata.get("what_it_is") or ""):
            continue
        place = {"id": place_id, "category": row.get("category") or ""}
        _upsert_profile_from_brief(conn, place, brief_metadata)
        written += 1
    return written
