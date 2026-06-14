from datetime import datetime, timezone

from localsignal_engine.ingestion.instagram_profile import (
    InstagramProfileAdapter,
    _caption_text,
    _iter_posts,
    _post_timestamp,
)
from localsignal_engine.models import Place


def _place(pid="p1", name="Ümacha", city="Edgewater"):
    return Place(id=pid, name=name, category="cafe", city=city)


def test_caption_text_handles_dict_and_str():
    assert _caption_text({"caption": {"text": "Bucket lemonade"}}) == "Bucket lemonade"
    assert _caption_text({"caption": "ÜMACHA Milk tea"}) == "ÜMACHA Milk tea"
    assert _caption_text({"description": "fallback"}) == "fallback"
    assert _caption_text({}) == ""


def test_post_timestamp_from_caption_created_at():
    ts = _post_timestamp({"caption": {"created_at": 1717800000}})
    assert ts is not None and ts.year == 2024


def test_iter_posts_flat_and_nested():
    nested = {"latestPosts": [{"caption": "a", "shortCode": "x"}, {"caption": "b", "shortCode": "y"}]}
    assert len(_iter_posts(nested)) == 2
    flat = {"caption": "solo", "shortCode": "z", "timestamp": "2026-06-01T00:00:00Z"}
    assert _iter_posts(flat) == [flat]
    assert _iter_posts({"name": "profile only, no posts"}) == []


def test_parse_binds_posts_to_place_by_owner(monkeypatch):
    monkeypatch.setenv("SOCIAL_MAX_AGE_DAYS", "100000")  # keep old test posts
    adapter = InstagramProfileAdapter()
    adapter.handle_to_place = {"umacha_official": _place()}
    recent = int(datetime.now(timezone.utc).timestamp())
    records = [
        {
            "ownerUsername": "umacha_official",
            "caption": {"text": "Ready for summer", "created_at": recent},
            "shortCode": "abc",
            "likesCount": 42,
        },
        # unknown owner -> dropped
        {"ownerUsername": "some_random_acct", "caption": {"text": "x", "created_at": recent}, "shortCode": "d"},
    ]
    mentions = adapter._parse(records)
    assert len(mentions) == 1
    assert mentions[0].place_id == "p1"
    assert mentions[0].source == "instagram"
    assert "summer" in mentions[0].body


def test_parse_drops_empty_caption(monkeypatch):
    monkeypatch.setenv("SOCIAL_MAX_AGE_DAYS", "100000")
    adapter = InstagramProfileAdapter()
    adapter.handle_to_place = {"umacha_official": _place()}
    recent = int(datetime.now(timezone.utc).timestamp())
    records = [{"ownerUsername": "umacha_official", "caption": "", "shortCode": "abc", "timestamp": recent}]
    assert adapter._parse(records) == []
