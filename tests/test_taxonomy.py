from keenbench.news.taxonomy import (
    TOPICAL_DOMAINS,
    trends_category_to_topical_domain,
)


def test_known_category_maps():
    assert trends_category_to_topical_domain(["business_and_finance"]) == "finance"
    assert trends_category_to_topical_domain(["Technology"]) == "tech"


def test_first_matching_category_wins():
    assert trends_category_to_topical_domain(["unlisted", "sports"]) == "sports"


def test_unknown_and_empty_default_to_other():
    assert trends_category_to_topical_domain([]) == "other"
    assert trends_category_to_topical_domain(None) == "other"
    assert trends_category_to_topical_domain(["nope"]) == "other"


def test_accepts_json_string():
    assert trends_category_to_topical_domain('["health"]') == "health"
    assert trends_category_to_topical_domain("not json") == "other"


def test_all_mapped_values_are_valid_domains():
    for cat in ["sports", "games", "climate"]:
        assert trends_category_to_topical_domain([cat]) in TOPICAL_DOMAINS
