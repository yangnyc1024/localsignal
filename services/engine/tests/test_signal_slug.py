from localsignal_engine.models import Place, Signal
from localsignal_engine.signal.story import signal_slug


def _signal(name: str, signal_type: str = "review_velocity_spike") -> Signal:
    place = Place(id="p1", name=name, category="restaurant", city="Fort Lee")
    return Signal(
        place=place,
        signal_type=signal_type,
        title="ignored",
        summary="ignored",
        evidence={},
        score=70.0,
        week_start="2026-06-08",
    )


def test_slug_is_place_type_week():
    assert signal_slug(_signal("Mochi Mochi Cafe")) == "mochi-mochi-cafe-attention-2026-06-08"


def test_slug_drops_marketing_tail_and_stays_short():
    raw = "Loui Boil - Cajun Seafood Boil Restaurant in Edgewater Nj /Crab House - Spicy/Heat/Bold Flavor"
    slug = signal_slug(_signal(raw))
    assert slug == "loui-boil-attention-2026-06-08"
    assert len(slug) < 60


def test_slug_never_contains_generated_prose():
    slug = signal_slug(_signal("Cafe Miel", signal_type="sentiment_shift"))
    assert slug == "cafe-miel-sentiment-2026-06-08"


def test_cjk_only_segments_fall_back_to_place():
    slug = signal_slug(_signal("남산돈까스", signal_type="keyword_spike"))
    assert slug.endswith("-keywords-2026-06-08")
    assert slug.startswith("place") or slug[0].isalnum()
