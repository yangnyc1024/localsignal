"""Canonical place display-name cleaning.

Google Places names often carry marketing payloads ("365 BBQ | Korean BBQ |
All You Can EAT", "Loui Boil - Cajun Seafood Boil Restaurant in Edgewater Nj
/Crab House - Spicy/Heat/Bold Flavor"). The cleaned name is stored in
places.display_name and used by every product surface (web, email, slugs);
the raw name stays in places.name.

CJK characters are kept on purpose — they carry meaning for the local
Korean/Chinese-speaking audience.
"""
import re

_MIN_HEAD_SEGMENT_CHARS = 6


def display_place_name(name: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f]", " ", str(name or ""))
    cleaned = cleaned.split("|")[0]
    head = re.split(r"\s+[-–—/]\s+", cleaned)[0].strip()
    if len(head) >= _MIN_HEAD_SEGMENT_CHARS:
        cleaned = head
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t-–—/,|")
    return cleaned or str(name or "").strip()
