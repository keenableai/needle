from needle.haystack.sources import (
    parse_fr_documents,
    parse_wiki_extract,
    parse_wiki_members,
    wiki_url,
)


def test_parse_fr_documents_keeps_complete_rows():
    payload = {
        "results": [
            {
                "title": "Air Quality Standards",
                "document_number": "2026-01234",
                "publication_date": "2026-09-01",
                "html_url": "https://www.federalregister.gov/d/2026-01234",
                "raw_text_url": "https://www.federalregister.gov/raw/2026-01234",
                "agency_names": ["EPA"],
                "page_length": 12,
            },
            {
                "title": "No raw text",
                "html_url": "https://www.federalregister.gov/d/2026-99999",
                "page_length": 12,
            },
            {
                "title": "Too short",
                "html_url": "https://www.federalregister.gov/d/2026-00002",
                "raw_text_url": "https://www.federalregister.gov/raw/2026-00002",
                "page_length": 2,
            },
            {"raw_text_url": "https://x", "html_url": "https://y", "page_length": 12},
            "not-a-dict",
        ]
    }
    docs = parse_fr_documents(payload)
    assert len(docs) == 1
    assert docs[0]["document_number"] == "2026-01234"
    assert docs[0]["agency_names"] == ["EPA"]


def test_parse_fr_documents_tolerates_bad_payload():
    assert parse_fr_documents(None) == []
    assert parse_fr_documents({"results": None}) == []
    assert parse_fr_documents([]) == []


def test_parse_wiki_members_titles_and_continue():
    payload = {
        "query": {
            "categorymembers": [
                {"title": "Deep Article", "ns": 0},
                {"title": "Talk:Skip", "ns": 1},
                {"ns": 0},
            ]
        },
        "continue": {"cmcontinue": "page|abc|123"},
    }
    titles, cont = parse_wiki_members(payload)
    assert titles == ["Deep Article"]
    assert cont == "page|abc|123"


def test_parse_wiki_members_last_page_has_no_continue():
    titles, cont = parse_wiki_members({"query": {"categorymembers": [{"title": "A", "ns": 0}]}})
    assert titles == ["A"]
    assert cont is None
    assert parse_wiki_members(None) == ([], None)


def test_parse_wiki_extract_resolves_first_page():
    payload = {
        "query": {"pages": {"42": {"title": "Deep Article", "extract": "body text", "pageid": 42}}}
    }
    assert parse_wiki_extract(payload) == ("Deep Article", "body text")


def test_parse_wiki_extract_missing_page_is_none():
    assert parse_wiki_extract({"query": {"pages": {"-1": {"missing": ""}}}}) is None
    assert parse_wiki_extract({"query": {"pages": {"7": {"title": "No extract"}}}}) is None
    assert parse_wiki_extract(None) is None


def test_wiki_url_underscores_and_quoting():
    assert wiki_url("Deep Article") == "https://en.wikipedia.org/wiki/Deep_Article"
    assert wiki_url("Café au lait") == "https://en.wikipedia.org/wiki/Caf%C3%A9_au_lait"
