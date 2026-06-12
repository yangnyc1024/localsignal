from collections import Counter

from localsignal_engine.signal.scoring import _classify, _top_keywords


def test_generic_praise_terms_excluded_from_keywords():
    current = Counter({"service": 9, "friendly": 7, "good": 6, "katsu": 5, "bingsu": 3})
    keywords = _top_keywords(current, Counter())
    assert "service" not in keywords
    assert "friendly" not in keywords
    assert "good" not in keywords
    assert keywords[0] == "katsu"
    assert "bingsu" in keywords


def test_sentiment_shift_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SIGNAL_SENTIMENT_SHIFT_ENABLED", raising=False)
    # Strong negative delta would previously classify as sentiment_shift.
    assert _classify(velocity_ratio=1.0, sentiment_delta=-0.5, keywords=["wait"]) != "sentiment_shift"


def test_sentiment_shift_can_be_reenabled(monkeypatch):
    monkeypatch.setenv("SIGNAL_SENTIMENT_SHIFT_ENABLED", "true")
    assert _classify(velocity_ratio=1.0, sentiment_delta=-0.5, keywords=[]) == "sentiment_shift"
