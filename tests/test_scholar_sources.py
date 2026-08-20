from datetime import UTC, datetime

from needle.scholar.models import age_bucket, coarse_domain
from needle.scholar.sources import (
    _norm_arxiv_id,
    _norm_doi,
    _parse_dt,
    parse_arxiv_atom,
    parse_epmc_result,
)

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2506.12345v2</id>
    <title>SmoothQuant:  Accurate and
      Efficient Quantization</title>
    <summary>We propose a method.</summary>
    <published>2026-06-28T17:59:59Z</published>
    <arxiv:doi>10.48550/ARXIV.2506.12345</arxiv:doi>
    <arxiv:primary_category term="cs.LG"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/hep-th/9901001v1</id>
    <title>Old Style Identifier</title>
    <summary>Abstract text.</summary>
    <published>1999-01-04T00:00:00Z</published>
    <arxiv:primary_category term="hep-th"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2506.99999v1</id>
    <title>No Abstract Entry</title>
    <published>2026-06-28T00:00:00Z</published>
  </entry>
</feed>
"""


def test_parse_arxiv_atom():
    papers = parse_arxiv_atom(ATOM)
    assert len(papers) == 2
    first, second = papers
    assert first.arxiv_id == "2506.12345"
    assert first.title == "SmoothQuant: Accurate and Efficient Quantization"
    assert first.doi == "10.48550/arxiv.2506.12345"
    assert first.published == datetime(2026, 6, 28, 17, 59, 59, tzinfo=UTC)
    assert first.url == "https://arxiv.org/abs/2506.12345"
    assert first.domain == "computer science"
    assert first.ids == {"arxiv": "2506.12345", "doi": "10.48550/arxiv.2506.12345"}
    assert second.arxiv_id == "hep-th/9901001"
    assert second.domain == "physical sciences"
    assert second.doi is None


def test_parse_arxiv_atom_bad_xml():
    assert parse_arxiv_atom("not xml") == []
    assert parse_arxiv_atom("") == []


def test_norm_arxiv_id():
    assert _norm_arxiv_id("http://arxiv.org/abs/2506.12345v2") == "2506.12345"
    assert _norm_arxiv_id("https://arxiv.org/abs/2506.12345") == "2506.12345"
    assert _norm_arxiv_id("http://arxiv.org/abs/hep-th/9901001v11") == "hep-th/9901001"
    assert _norm_arxiv_id("https://example.com/paper") is None
    assert _norm_arxiv_id(None) is None


def test_norm_doi():
    assert _norm_doi("https://doi.org/10.1038/S41586") == "10.1038/s41586"
    assert _norm_doi("doi:10.1038/x") == "10.1038/x"
    assert _norm_doi("10.1038/x") == "10.1038/x"
    assert _norm_doi("") is None
    assert _norm_doi("https://doi.org/") is None


def test_parse_dt():
    assert _parse_dt("2026-06-28") == datetime(2026, 6, 28, tzinfo=UTC)
    assert _parse_dt("2026-06-28T17:59:59Z") == datetime(2026, 6, 28, 17, 59, 59, tzinfo=UTC)
    assert _parse_dt("junk") is None
    assert _parse_dt(None) is None


def _epmc(**overrides):
    rec = {
        "title": "Survival in  mice.",
        "abstractText": "We studied\nsurvival.",
        "firstPublicationDate": "2026-06-10",
        "pmcid": "PMC7654321",
        "pmid": "12345678",
        "doi": "10.1234/ABC",
    }
    rec.update(overrides)
    return rec


def test_parse_epmc_result():
    paper = parse_epmc_result(_epmc())
    assert paper is not None
    assert paper.suite == "europepmc"
    assert paper.title == "Survival in mice."
    assert paper.abstract == "We studied survival."
    assert paper.pmcid == "7654321"
    assert paper.pmid == "12345678"
    assert paper.doi == "10.1234/abc"
    assert paper.url == "https://europepmc.org/article/PMC/PMC7654321"
    assert paper.published == datetime(2026, 6, 10, tzinfo=UTC)
    assert paper.ids == {"doi": "10.1234/abc", "pmid": "12345678"}


def test_parse_epmc_result_rejects_incomplete():
    assert parse_epmc_result(_epmc(pmcid=None)) is None
    assert parse_epmc_result(_epmc(abstractText="")) is None
    assert parse_epmc_result(_epmc(firstPublicationDate=None)) is None
    paper = parse_epmc_result(_epmc(pmid=None, doi=None))
    assert paper is not None
    assert paper.pmid is None
    assert paper.doi is None
    assert paper.ids == {}


def test_coarse_domain():
    assert coarse_domain("cs.LG") == "computer science"
    assert coarse_domain("math.AT") == "physical sciences"
    assert coarse_domain("hep-th") == "physical sciences"
    assert coarse_domain("q-bio.NC") == "life sciences"
    assert coarse_domain("econ.EM") == "social sciences"
    assert coarse_domain("q-fin.PR") == "social sciences"
    assert coarse_domain("") == "physical sciences"


def test_age_bucket():
    now = datetime(2026, 7, 2, tzinfo=UTC)
    assert age_bucket(datetime(2026, 7, 1, tzinfo=UTC), now=now) == "7d"
    assert age_bucket(datetime(2026, 6, 25, tzinfo=UTC), now=now) == "7d"
    assert age_bucket(datetime(2026, 6, 10, tzinfo=UTC), now=now) == "30d"
    assert age_bucket(datetime(2025, 9, 1, tzinfo=UTC), now=now) == "1y"
    assert age_bucket(datetime(2020, 1, 1, tzinfo=UTC), now=now) == "older"
    assert age_bucket(datetime(2026, 7, 3, tzinfo=UTC), now=now) == "7d"
