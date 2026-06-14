from localsignal_engine.place.handles import (
    sanitize_instagram_handle as clean,
    _handle_matches_place,
    _candidate_handles,
)


def test_strips_at_and_whitespace():
    assert clean("@umacha_official") == "umacha_official"
    assert clean("  @Foo.Bar_1 ") == "Foo.Bar_1"


def test_extracts_from_url():
    assert clean("https://www.instagram.com/mochimochi.cafe/") == "mochimochi.cafe"
    assert clean("instagram.com/abc?hl=en") == "abc"


def test_rejects_blocklisted_and_junk():
    for bad in ["", "N/A", "none", "unknown", "reel", "instagram.com/explore/", "bad handle with spaces", "p"]:
        assert clean(bad) == "", bad


def test_rejects_single_char_truncation():
    assert clean("N/A") == ""


def test_passthrough_plain_handle():
    assert clean("umacha_official") == "umacha_official"


def test_handle_matches_place():
    assert _handle_matches_place("umacha_official", "Ümacha")
    assert _handle_matches_place("mochimochi.cafe", "Mochi Mochi Cafe")
    assert _handle_matches_place("chinosbakerycafe", "Chinos Bakery & Cafe")
    # An unrelated account for a different business should not match.
    assert not _handle_matches_place("davantbakery", "Chinos Bakery")


def test_candidate_handles_skips_post_paths():
    organic = [
        {"url": "https://www.instagram.com/p/abc123/"},
        {"url": "https://www.instagram.com/umacha_official/"},
    ]
    assert _candidate_handles(organic) == ["umacha_official"]
