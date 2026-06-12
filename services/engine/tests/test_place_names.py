from localsignal_engine.place.names import display_place_name


def test_strips_marketing_pipe_segments():
    assert display_place_name("365 BBQ | Korean BBQ | All You Can EAT") == "365 BBQ"


def test_strips_dash_separated_marketing_tail():
    raw = "Loui Boil - Cajun Seafood Boil Restaurant in Edgewater Nj /Crab House - Spicy/Heat/Bold Flavor"
    assert display_place_name(raw) == "Loui Boil"


def test_keeps_cjk_characters():
    assert display_place_name("Namsan donkatsu 남산돈까스") == "Namsan donkatsu 남산돈까스"


def test_keeps_hyphenated_words_without_spaces():
    assert display_place_name("Obaltan K-BBQ (곱창ㅣ조개구이ㅣ소고기)") == "Obaltan K-BBQ (곱창ㅣ조개구이ㅣ소고기)"


def test_keeps_short_head_segment_whole():
    # First segment under the minimum length keeps the full name.
    assert display_place_name("BCD - Tofu House") == "BCD - Tofu House"


def test_plain_names_unchanged():
    assert display_place_name("Mochi Mochi Cafe") == "Mochi Mochi Cafe"
    assert display_place_name("ETERI Boutique & Café Lounge") == "ETERI Boutique & Café Lounge"


def test_empty_name():
    assert display_place_name("") == ""
