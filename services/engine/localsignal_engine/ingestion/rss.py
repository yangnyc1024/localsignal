import logging
import email.utils
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from localsignal_engine.ingestion.base import IngestionAdapter
from localsignal_engine.ingestion.matching import matching_places
from localsignal_engine.models import Mention, Place

logger = logging.getLogger(__name__)


class RssAdapter(IngestionAdapter):
    source = "rss"

    def __init__(self, feed_urls: list[str], source: str = "rss") -> None:
        self.feed_urls = feed_urls
        self.source = source

    def fetch_mentions(self, places: list[Place]) -> list[Mention]:
        mentions: list[Mention] = []
        for feed_url in self.feed_urls:
            try:
                body = _fetch(feed_url)
            except OSError as exc:
                logger.warning(f"RSS fetch failed for {feed_url}: {exc}")
                continue

            mentions.extend(_parse_feed(body, feed_url, places, self.source))
        return mentions


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "LocalSignalBot/0.1 (+https://localsignal.local)"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def _parse_feed(body: bytes, feed_url: str, places: list[Place], source: str = "rss") -> list[Mention]:
    root = ET.fromstring(body)
    entries = root.findall(".//item") or root.findall("{http://www.w3.org/2005/Atom}entry")
    mentions: list[Mention] = []

    for entry in entries:
        title = _text(entry, "title")
        summary = _text(entry, "description") or _text(entry, "{http://www.w3.org/2005/Atom}summary")
        link = _text(entry, "link") or _atom_link(entry) or feed_url
        published = _text(entry, "pubDate") or _text(entry, "published") or _text(entry, "{http://www.w3.org/2005/Atom}updated")
        text = f"{title}\n{summary}".strip()
        if not text:
            continue

        for place in matching_places(text, places):
            mentions.append(
                Mention(
                    place_id=place.id,
                    source=source,
                    source_url=link,
                    body=text,
                    author_region=place.city,
                    sentiment=None,
                    occurred_at=_parse_date(published),
                )
            )

    return mentions


def _text(entry: ET.Element, tag: str) -> str:
    value = entry.findtext(tag)
    return value.strip() if value else ""


def _atom_link(entry: ET.Element) -> str:
    link = entry.find("{http://www.w3.org/2005/Atom}link")
    if link is None:
        return ""
    return link.attrib.get("href", "")


def _parse_date(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = email.utils.parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
