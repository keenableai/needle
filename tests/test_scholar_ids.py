from needle.scholar.ids import (
    extract_arxiv,
    extract_doi,
    extract_ids,
    extract_pmcid,
    extract_pmid,
)
from needle.shared.search import SearchResult


def test_extract_arxiv_url_forms():
    assert extract_arxiv("https://arxiv.org/abs/2506.12345", "") == {"2506.12345"}
    assert extract_arxiv("https://arxiv.org/abs/2506.12345v3", "") == {"2506.12345"}
    assert extract_arxiv("https://arxiv.org/pdf/2506.12345", "") == {"2506.12345"}
    assert extract_arxiv("https://arxiv.org/pdf/2506.12345v2", "") == {"2506.12345"}
    assert extract_arxiv("https://arxiv.org/html/2506.12345v1", "") == {"2506.12345"}
    assert extract_arxiv("https://arxiv.org/abs/hep-th/9901001", "") == {"hep-th/9901001"}


def test_extract_arxiv_from_text_and_doi():
    assert extract_arxiv("https://example.com", "see arXiv:2506.12345 for details") == {
        "2506.12345"
    }
    assert extract_arxiv("https://doi.org/10.48550/arXiv.2506.12345", "") == {"2506.12345"}
    assert extract_arxiv("https://example.com/paper", "no id here") == set()


def test_extract_arxiv_collects_all_ids():
    text = "compare arXiv:2506.11111 with arXiv:2506.22222"
    assert extract_arxiv("https://example.com", text) == {"2506.11111", "2506.22222"}


def test_extract_pmid():
    assert extract_pmid("https://pubmed.ncbi.nlm.nih.gov/12345678", "") == {"12345678"}
    assert extract_pmid("https://www.ncbi.nlm.nih.gov/pubmed/999", "") == {"999"}
    assert extract_pmid("https://europepmc.org/article/MED/42342999", "") == {"42342999"}
    assert extract_pmid("https://x.com", "PMID: 12345678 in text") == {"12345678"}
    assert extract_pmid("https://x.com", "nothing") == set()


def test_extract_pmcid():
    assert extract_pmcid("https://pmc.ncbi.nlm.nih.gov/articles/PMC7654321") == {"7654321"}
    assert extract_pmcid("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7654321/") == {"7654321"}
    assert extract_pmcid("https://europepmc.org/article/PMC/PMC13294337") == {"13294337"}
    assert extract_pmcid("https://x.com") == set()


def test_extract_doi():
    assert extract_doi("https://doi.org/10.1038/S41586-021", "") == {"10.1038/s41586-021"}
    assert extract_doi("https://journal.example/10.1234/abc.def", "") == {"10.1234/abc.def"}
    assert extract_doi("https://x.com", "cite 10.1234/xyz.") == {"10.1234/xyz"}
    assert extract_doi("https://x.com", "no doi") == set()


def test_extract_doi_collects_all_ids():
    text = "see 10.1234/first, also 10.5678/second."
    assert extract_doi("https://x.com", text) == {"10.1234/first", "10.5678/second"}


def test_extract_doi_strips_publisher_suffix():
    assert extract_doi(
        "https://www.frontiersin.org/articles/10.3389/fimmu.2026.1856481/full", ""
    ) == {"10.3389/fimmu.2026.1856481"}
    assert extract_doi("https://onlinelibrary.wiley.com/doi/epdf/10.1002/etc.4890", "") == {
        "10.1002/etc.4890"
    }
    assert extract_doi("https://x.com/doi/10.1002/etc.4890/pdf", "") == {"10.1002/etc.4890"}


def test_extract_ids_caps_snippet():
    result = SearchResult(
        url="https://journal.example/article",
        title="A Paper",
        snippet="x" * 100 + " 10.1234/deep.buried",
    )
    ids = extract_ids(result, snippet_chars=50)
    assert ids.doi == set()
    ids_full = extract_ids(result, snippet_chars=0)
    assert ids_full.doi == {"10.1234/deep.buried"}


def test_extract_ids_match_dict():
    result = SearchResult(url="https://arxiv.org/abs/2506.12345", title="T", snippet="")
    ids = extract_ids(result, snippet_chars=500)
    assert ids.as_match_dict() == {"arxiv": ["2506.12345"]}
