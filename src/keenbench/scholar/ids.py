import re
from dataclasses import dataclass

from keenbench.shared.search import SearchResult

_ARXIV_ID = r"(?:[a-z-]+/\d{7}|\d{4}\.\d{4,5})"
ARXIV_URL_RE = re.compile(rf"arxiv\.org/(?:abs|pdf|html)/({_ARXIV_ID})(?:v\d+)?", re.IGNORECASE)
ARXIV_TEXT_RE = re.compile(rf"arxiv[:\s]+({_ARXIV_ID})(?:v\d+)?", re.IGNORECASE)
ARXIV_DOI_RE = re.compile(rf"10\.48550/arxiv\.({_ARXIV_ID})", re.IGNORECASE)

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


@dataclass
class PaperIds:
    arxiv: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None

    def as_match_dict(self) -> dict[str, str]:
        ids = {"arxiv": self.arxiv, "doi": self.doi, "pmid": self.pmid}
        return {k: v for k, v in ids.items() if v}


def extract_arxiv(url: str, text: str) -> str | None:
    for pat in (ARXIV_URL_RE, ARXIV_TEXT_RE, ARXIV_DOI_RE):
        m = pat.search(url) or pat.search(text)
        if m:
            return m.group(1).lower()
    return None


def extract_pmid(url: str, text: str) -> str | None:
    for pat in PMID_URL_RES:
        m = pat.search(url)
        if m:
            return m.group(1)
    m = PMID_TEXT_RE.search(text)
    return m.group(1) if m else None


def extract_pmcid(url: str) -> str | None:
    for pat in PMC_URL_RES:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def extract_doi(url: str, text: str) -> str | None:
    for src in (url, text):
        m = DOI_RE.search(src)
        if m:
            doi = m.group(1).rstrip(".)").rstrip(",")
            doi = DOI_SUFFIX_RE.sub("", doi)
            return doi.lower()
    return None


def _capped(result: SearchResult, snippet_chars: int) -> str:
    snippet = result.snippet or ""
    if snippet_chars > 0:
        snippet = snippet[:snippet_chars]
    return " ".join(part for part in (result.title, snippet) if part)


def extract_ids(result: SearchResult, *, snippet_chars: int) -> PaperIds:
    url = result.url or ""
    text = _capped(result, snippet_chars)
    return PaperIds(
        arxiv=extract_arxiv(url, text),
        doi=extract_doi(url, text),
        pmid=extract_pmid(url, text),
        pmcid=extract_pmcid(url),
    )
