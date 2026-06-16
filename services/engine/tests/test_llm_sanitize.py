import unittest

from localsignal_engine.llm import (
    BANNED_WORDS,
    BRIEFING_BANNED_WORDS,
    _sanitize_banned_words,
    find_banned_words,
)


class SanitizeBannedWordsTest(unittest.TestCase):
    def test_food_quality_does_not_duplicate_food(self):
        self.assertEqual(
            _sanitize_banned_words("The food quality is improving."),
            "The food is improving.",
        )

    def test_service_quality_handled_as_phrase(self):
        self.assertEqual(
            _sanitize_banned_words("Service quality keeps coming up."),
            "Service keeps coming up.",
        )

    def test_quality_alone_becomes_food(self):
        self.assertEqual(
            _sanitize_banned_words("Talk about quality at the bakery."),
            "Talk about food at the bakery.",
        )

    def test_no_mid_word_replacement(self):
        self.assertEqual(
            _sanitize_banned_words("Their bestseller is the croissant."),
            "Their bestseller is the croissant.",
        )

    def test_best_as_whole_word_is_replaced(self):
        self.assertEqual(
            _sanitize_banned_words("The best croissant in town."),
            "The notable croissant in town.",
        )

    def test_expectations_inside_word_untouched(self):
        # "metric" must not fire inside "metrical", "demand" not inside "demanding"
        self.assertEqual(
            _sanitize_banned_words("A demanding, metrical poem."),
            "A demanding, metrical poem.",
        )

    def test_customer_experience_phrase_wins_over_parts(self):
        self.assertEqual(
            _sanitize_banned_words("The customer experience is shifting."),
            "The visit language is shifting.",
        )

    def test_case_insensitive_and_keeps_leading_capital(self):
        self.assertEqual(
            _sanitize_banned_words("Confidence is high."),
            "Read is high.",
        )

    def test_word_with_no_replacement_is_dropped_cleanly(self):
        self.assertEqual(
            _sanitize_banned_words("A pattern was detected here.", ["detected"]),
            "A pattern was here.",
        )

    def test_nested_structures_sanitized_but_slug_skipped(self):
        payload = {
            "title": "Cafe Miel food quality watch",
            "signal_slug": "cafe-miel-quality-watch",
            "items": [{"summary": "service quality talk"}],
        }
        _sanitize_banned_words(payload)
        self.assertEqual(payload["title"], "Cafe Miel food watch")
        self.assertEqual(payload["signal_slug"], "cafe-miel-quality-watch")
        self.assertEqual(payload["items"][0]["summary"], "service talk")

    def test_output_contains_no_briefing_banned_words(self):
        text = (
            "Customer experience and service quality metrics show demand, "
            "momentum, engagement, and popularity around the market."
        )
        cleaned = _sanitize_banned_words(text, list(BRIEFING_BANNED_WORDS))
        self.assertEqual(find_banned_words(cleaned.lower(), BRIEFING_BANNED_WORDS), [])


class FindBannedWordsTest(unittest.TestCase):
    def test_substring_inside_word_not_flagged(self):
        self.assertEqual(find_banned_words("the bestseller list", BANNED_WORDS), [])

    def test_whole_word_flagged(self):
        self.assertEqual(find_banned_words("the best seller", BANNED_WORDS), ["best"])

    def test_phrase_flagged(self):
        self.assertIn(
            "service quality",
            find_banned_words("strong service quality here", BRIEFING_BANNED_WORDS),
        )


if __name__ == "__main__":
    unittest.main()
