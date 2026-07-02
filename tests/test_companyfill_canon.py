import pytest

from keenbench.companyfill.canon import (
    gold_in_text,
    registrable_domain,
    squad_norm,
    strip_legal,
    text_amounts,
    text_years,
)


def test_squad_norm_replaces_punctuation_with_spaces():
    assert squad_norm("Coca-Cola, Inc.") == "coca cola inc"
    assert squad_norm("  The  NVIDIA   Corp ") == "nvidia corp"


def test_strip_legal_drops_suffix_tokens():
    assert strip_legal("Apple Inc.") == "apple"
    assert strip_legal("Berkshire Hathaway Holdings Group") == "berkshire hathaway"


def test_registrable_domain():
    assert registrable_domain("https://www.nvidia.com/en-us/") == "nvidia.com"
    assert registrable_domain("http://investor.apple.com/faq") == "apple.com"
    assert registrable_domain("nvidia.com") == "nvidia.com"


def test_text_years_word_boundaries():
    assert text_years("founded in 1993, revised 2026") == {1993, 2026}
    assert text_years("id 19935 and 020261") == set()


def test_text_amounts_with_scales():
    assert text_amounts("revenue of $416.16 billion") == [416.16e9]
    assert text_amounts("34,000 employees") == [34000.0]
    assert 130.5e9 in text_amounts("$130.5B in FY2025")


def test_person_exact_and_nickname():
    assert gold_in_text("person", "Jensen Huang", text="Nvidia CEO Jensen Huang announced")
    assert gold_in_text("person", "Timothy Donald Cook", text="Apple chief executive Tim Cook said")
    assert not gold_in_text("person", "Jensen Huang", text="Lisa Su of AMD presented")
    assert not gold_in_text("person", "Ann Lee", text="the annual meeting agenda")


def test_person_alias_forms():
    assert gold_in_text(
        "person", "William Henry Gates III", ("Bill Gates",), text="Microsoft founder Bill Gates"
    )


def test_money_two_percent_band():
    assert gold_in_text("money", 416161000000, text="revenue of $416.16 billion in fiscal 2025")
    assert gold_in_text("money", 416161000000, text="reported $416.2B revenue")
    assert not gold_in_text("money", 416161000000, text="about $390 billion")


def test_numeric_band_requires_cue():
    cues = ("employee", "employees", "headcount")
    assert gold_in_text(
        "numeric_band", 36000, text="NVIDIA has about 34,000 employees worldwide", cues=cues
    )
    assert not gold_in_text("numeric_band", 36000, text="raised $34,000 in funding", cues=cues)
    assert not gold_in_text(
        "numeric_band", 36000, text="NVIDIA has about 20,000 employees", cues=cues
    )


def test_year_requires_cue():
    cues = ("founded", "established")
    assert gold_in_text("year", 1993, text="Nvidia was founded in 1993", cues=cues)
    assert not gold_in_text("year", 1993, text="revenue peaked in 1993", cues=cues)
    assert not gold_in_text("year", 1993, text="founded in 1995", cues=cues)


def test_country_phrases_aliases_and_short_forms():
    aliases = ("USA", "US", "U.S.", "America")
    assert gold_in_text(
        "country", "United States of America", aliases, text="based in Santa Clara, United States"
    )
    assert gold_in_text("country", "United States of America", aliases, text="a US-based company")
    assert gold_in_text("country", "United States of America", aliases, text="a U.S. company")
    assert not gold_in_text(
        "country", "United States of America", aliases, text="trust us on this one"
    )
    assert not gold_in_text(
        "country",
        "United States of America",
        ("the States",),
        text="operates stores in all 50 states",
    )


def test_domain_matches_result_url_or_text():
    assert gold_in_text("domain", "nvidia.com", text="", url="https://www.nvidia.com/about")
    assert gold_in_text("domain", "nvidia.com", text="visit nvidia.com for details", url="")
    assert not gold_in_text("domain", "nvidia.com", text="visit amd.com", url="https://amd.com")


def test_exact_id_ticker_case_sensitive_word_boundary():
    assert gold_in_text("exact_id", "AAPL", text="(NASDAQ: AAPL)")
    assert gold_in_text("exact_id", "GM", text="GM shares rose")
    assert not gold_in_text("exact_id", "AAPL", text="aapl lowercase mention")
    assert not gold_in_text("exact_id", "GM", text="a gmail programme")


def test_exact_id_lei_substring():
    lei = "549300MLUDYVRQOOXS22"
    assert gold_in_text("exact_id", lei, text=f"LEI: {lei}")
    assert gold_in_text("exact_id", lei, text="lei 549300 MLUDYVRQOOXS22 registered")
    assert not gold_in_text("exact_id", lei, text="LEI: 549300MLUDYVRQOOXS99")


def test_list_industry_with_plural_tolerance():
    assert gold_in_text("list", ["semiconductors"], text="leader in the semiconductor industry")
    assert gold_in_text("list", ["consumer electronics", "software"], text="makes software")
    assert not gold_in_text("list", ["semiconductors"], text="a retail chain")


def test_entity_token_boundaries():
    assert gold_in_text("entity", "Apple Inc.", text="Apple company overview")
    assert not gold_in_text("entity", "Cook Industries", text="cooking supplies wholesale")


def test_unknown_field_type_raises():
    with pytest.raises(ValueError):
        gold_in_text("bogus", "x", text="x")
