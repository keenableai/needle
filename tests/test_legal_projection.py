from datetime import date

from needle.legal.models import Case, CodeSection
from needle.legal.projection import (
    caption_parties,
    caption_query,
    caselaw_syntax_query,
    clean_code_query,
    code_query_ok,
    code_syntax_query,
    party_tokens,
)


def _case(name: str, court: str = "ca9") -> Case:
    return Case(
        court_id=court,
        case_name=name,
        docket="25-2462",
        citations=("89 F.4th 1188",),
        date_filed=date(2026, 5, 28),
        cluster_id=10865557,
        absolute_url="/opinion/10865557/x/",
    )


def test_caption_parties_strips_suffixes_and_noise():
    assert caption_parties("Fresh Mix, LLC v. Pisanelli Bice, PLLC") == [
        "fresh mix",
        "pisanelli bice",
    ]
    assert caption_parties("Trump v. Barbara Revisions: 7/01/26") == ["trump", "barbara"]
    assert caption_parties("United States v. Gonzalez-Godinez") == [
        "united states",
        "gonzalez-godinez",
    ]


def test_party_tokens_skip_generic_terms():
    assert party_tokens("United States v. Gonzalez-Godinez") == ["gonzalez-godinez"]
    assert "pisanelli" in party_tokens("Fresh Mix, LLC v. Pisanelli Bice, PLLC")


def test_caption_query_includes_court_phrase():
    q = caption_query(_case("Fresh Mix, LLC v. Pisanelli Bice, PLLC"))
    assert q == "fresh mix v pisanelli bice ninth circuit"


def test_caption_query_rejects_all_generic():
    assert caption_query(_case("State v. City")) is None


def test_caselaw_syntax_variants():
    case = _case("Fresh Mix, LLC v. Pisanelli Bice, PLLC")
    base = caption_query(case)
    assert caselaw_syntax_query(case, base, "plain") == base
    quoted = caselaw_syntax_query(case, base, "quoted")
    assert quoted.startswith('"fresh mix v pisanelli bice"')
    assert caselaw_syntax_query(case, base, "site").endswith("site:courtlistener.com")
    dated = caselaw_syntax_query(case, base, "date")
    assert "after:2026-04-13" in dated and "before:2026-07-12" in dated


SECTION = CodeSection(
    title_num=17,
    part="240",
    section="240.10b-5",
    heading="Employment of manipulative and deceptive devices.",
    text=(
        "It shall be unlawful for any person to employ any device scheme or artifice "
        "to defraud in connection with the purchase or sale of any security."
    ),
)


def test_clean_code_query_handles_sentinel_and_noise():
    assert clean_code_query("NO_DISTINCT_QUERY") is None
    assert clean_code_query("") is None
    assert clean_code_query(' securities fraud "artifice to defraud" rule ') == (
        'securities fraud "artifice to defraud" rule'
    )


def test_code_query_ok_requires_one_verbatim_span():
    assert code_query_ok('securities fraud "artifice to defraud" purchase', section=SECTION)
    assert not code_query_ok("securities fraud rule", section=SECTION)
    assert not code_query_ok('securities "not in the text at all" rule', section=SECTION)
    assert not code_query_ok('"device scheme" and "artifice to defraud"', section=SECTION)


def test_code_query_ok_rejects_citation_leaks():
    assert not code_query_ok('cfr securities "artifice to defraud"', section=SECTION)
    assert not code_query_ok('rule 240.10b-5 "artifice to defraud"', section=SECTION)
    assert not code_query_ok('rule 10b-5 fraud "artifice to defraud"', section=SECTION)
    assert not code_query_ok('title 17 fraud "artifice to defraud"', section=SECTION)


def test_code_syntax_variants():
    base = 'securities fraud "artifice to defraud" rule'
    assert code_syntax_query(base, "quoted") == base
    assert code_syntax_query(base, "plain") == "securities fraud artifice to defraud rule"
    assert code_syntax_query(base, "site") == (
        "securities fraud artifice to defraud rule site:law.cornell.edu"
    )
