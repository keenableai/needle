import re
from dataclasses import dataclass, field

from needle.shared.search import SearchResult, titled_snippet

ARXIV_ID = r"(?:[a-z-]+/\d{7}|\d{4}\.\d{4,5})"
ARXIV_URL_RE = re.compile(rf"arxiv\.org/(?:abs|pdf|html)/({ARXIV_ID})(?:v\d+)?", re.IGNORECASE)
ARXIV_TEXT_RE = re.compile(rf"arxiv[:\s]+({ARXIV_ID})(?:v\d+)?", re.IGNORECASE)
ARXIV_DOI_RE = re.compile(rf"10\.48550/arxiv\.({ARXIV_ID})", re.IGNORECASE)

PMID_URL_RES = [
    re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)"),
    re.compile(r"ncbi\.nlm\.nih\.gov/pubmed/(\d+)"),
    re.compile(r"europepmc\.org/(?:article|abstract)/MED/(\d+)", re.IGNORECASE),
]
PMID_TEXT_RE = re.compile(r"\bPMID[:\s]*(\d{6,9})\b", re.IGNORECASE)
PMC_URL_RES = [
    re.compile(
        r"(?:pmc\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pmc)/articles?/PMC(\d+)", re.IGNORECASE
    ),
    re.compile(r"europepmc\.org/article/PMC/PMC(\d+)", re.IGNORECASE),
]
DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:a-z0-9]+)", re.IGNORECASE)
DOI_SUFFIX_RE = re.compile(r"/(full|pdf|epdf|html|meta|abstract|citations?)$", re.IGNORECASE)

MATCH_FIELDS = ("arxiv", "doi", "pmid")


@dataclass
class PaperIds:
    arxiv: set[str] = field(default_factory=set)
    doi: set[str] = field(default_factory=set)
    pmid: set[str] = field(default_factory=set)
    pmcid: set[str] = field(default_factory=set)

    def as_match_dict(self) -> dict[str, list[str]]:
        return {k: sorted(v) for k in MATCH_FIELDS if (v := getattr(self, k))}


def extract_arxiv(url: str, text: str) -> set[str]:
    return {
        m.group(1).lower()
        for pat in (ARXIV_URL_RE, ARXIV_TEXT_RE, ARXIV_DOI_RE)
        for src in (url, text)
        for m in pat.finditer(src)
    }


def extract_pmid(url: str, text: str) -> set[str]:
    return {m.group(1) for pat in PMID_URL_RES for m in pat.finditer(url)} | {
        m.group(1) for m in PMID_TEXT_RE.finditer(text)
    }


def extract_pmcid(url: str) -> set[str]:
    return {m.group(1) for pat in PMC_URL_RES for m in pat.finditer(url)}


def _clean_doi(raw: str) -> str:
    doi = raw.rstrip(".)").rstrip(",")
    return DOI_SUFFIX_RE.sub("", doi).lower()


def extract_doi(url: str, text: str) -> set[str]:
    return {_clean_doi(m.group(1)) for src in (url, text) for m in DOI_RE.finditer(src)}


def extract_ids(result: SearchResult, *, snippet_chars: int) -> PaperIds:
    url = result.url or ""
    text = titled_snippet(result, snippet_chars)
    return PaperIds(
        arxiv=extract_arxiv(url, text),
        doi=extract_doi(url, text),
        pmid=extract_pmid(url, text),
        pmcid=extract_pmcid(url),
    )
