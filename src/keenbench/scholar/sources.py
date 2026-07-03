import asyncio
import random
import re
import time
from datetime import UTC, datetime
from typing import Any
from xml.etree.ElementTree import Element, ParseError

import defusedxml.ElementTree as ET
import httpx
from defusedxml.common import DefusedXmlException

from keenbench.scholar.bodies import html_body_text, jats_body_text
from keenbench.scholar.models import Paper, coarse_domain
from keenbench.shared.search.base import HttpSearchClient

USER_AGENT = "keenbench/0.1 (contact@keenable.ai)"

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_HTML = "https://arxiv.org/html/{arxiv_id}"
OPENALEX_WORKS = "https://api.openalex.org/works"
EUROPEPMC_XML = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC{pmcid}/fullTextXML"
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
ARXIV_ID_RE = re.compile(r"arxiv\.org/abs/(.+?)(v\d+)?$")
PMID_URL_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
PMCID_URL_RE = re.compile(r"PMC(\d+)", re.IGNORECASE)

ARXIV_DOMAIN_QUERY = {
    "computer science": "cat:cs.*",
    "physical sciences": "(cat:physics.* OR cat:math.* OR cat:stat.* OR cat:cond-mat.* OR cat:astro-ph.*)",
    "life sciences": "cat:q-bio.*",
    "social sciences": "(cat:econ.* OR cat:q-fin.*)",
}

OPENALEX_MAX_SAMPLE = 200
OPENALEX_DOMAINS = {
    "physical sciences": 3,
    "life sciences": 1,
    "health sciences": 4,
    "social sciences": 2,
}


def _norm_arxiv_id(raw: str | None) -> str | None:
    if not raw:
        return None
    m = ARXIV_ID_RE.search(raw.strip())
    return m.group(1) if m else None


def _norm_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    doi = raw.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi or None


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _el_text(el: Element | None) -> str | None:
    if el is None:
        return None
    return " ".join("".join(el.itertext()).split()) or None


def parse_arxiv_atom(text: str) -> list[Paper]:
    try:
        root = ET.fromstring(text)
    except (ParseError, DefusedXmlException, ValueError):
        return []
    papers = []
    for entry in root.findall("atom:entry", ARXIV_NS):
        arxiv_id = _norm_arxiv_id(_el_text(entry.find("atom:id", ARXIV_NS)))
        title = _el_text(entry.find("atom:title", ARXIV_NS))
        abstract = _el_text(entry.find("atom:summary", ARXIV_NS))
        published = _parse_dt(_el_text(entry.find("atom:published", ARXIV_NS)))
        if not arxiv_id or not title or not abstract or published is None:
            continue
        primary = entry.find("arxiv:primary_category", ARXIV_NS)
        category = primary.get("term", "") if primary is not None else ""
        papers.append(
            Paper(
                suite="arxiv",
                title=title,
                abstract=abstract,
                published=published,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                domain=coarse_domain(category, suite="arxiv"),
                arxiv_id=arxiv_id,
                doi=_norm_doi(_el_text(entry.find("arxiv:doi", ARXIV_NS))),
            )
        )
    return papers


def reconstruct_abstract(inverted_index: dict[str, list[int]]) -> str:
    positions = [(i, word) for word, idxs in inverted_index.items() for i in idxs]
    positions.sort()
    return " ".join(word for _, word in positions)


def parse_openalex_work(work: dict[str, Any]) -> Paper | None:
    title = " ".join((work.get("title") or "").split())
    abstract = reconstruct_abstract(work.get("abstract_inverted_index") or {})
    published = _parse_dt(work.get("publication_date"))
    ids = work.get("ids") or {}
    doi = _norm_doi(ids.get("doi") or work.get("doi"))
    if not title or not abstract or published is None or not doi:
        return None
    pmid_m = PMID_URL_RE.search(ids.get("pmid") or "")
    domain = ((work.get("primary_topic") or {}).get("domain") or {}).get("display_name") or ""
    url = (work.get("primary_location") or {}).get("landing_page_url") or f"https://doi.org/{doi}"
    return Paper(
        suite="openalex",
        title=title,
        abstract=abstract,
        published=published,
        url=url,
        domain=coarse_domain(domain, suite="openalex"),
        doi=doi,
        pmid=pmid_m.group(1) if pmid_m else None,
    )


def parse_epmc_result(rec: dict[str, Any]) -> Paper | None:
    title = " ".join((rec.get("title") or "").split())
    abstract = " ".join((rec.get("abstractText") or "").split())
    published = _parse_dt(rec.get("firstPublicationDate"))
    pmcid_m = PMCID_URL_RE.search(rec.get("pmcid") or "")
    if not title or not abstract or published is None or not pmcid_m:
        return None
    pmid = (rec.get("pmid") or "").strip() or None
    return Paper(
        suite="europepmc",
        title=title,
        abstract=abstract,
        published=published,
        url=f"https://europepmc.org/article/PMC/PMC{pmcid_m.group(1)}",
        domain="health sciences",
        doi=_norm_doi(rec.get("doi")),
        pmid=pmid,
        pmcid=pmcid_m.group(1),
    )


class ScholarClient(HttpSearchClient):
    async def _request_text(self, url: str, *, params: dict[str, Any] | None = None) -> str | None:
        try:
            async with self._sem:
                resp = await self._http().request(
                    "GET",
                    url,
                    params=params,
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=True,
                )
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        return resp.text


class ArxivClient(ScholarClient):
    def __init__(self, *, delay_s: float = 3.0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.delay_s = delay_s
        self._api_lock = asyncio.Lock()
        self._last_api = 0.0

    async def search_domain(
        self, domain: str, *, from_date: str, to_date: str, max_results: int = 100
    ) -> list[Paper]:
        start = from_date.replace("-", "") + "0000"
        end = to_date.replace("-", "") + "2359"
        query = f"{ARXIV_DOMAIN_QUERY[domain]} AND submittedDate:[{start} TO {end}]"
        params = {
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": max_results,
        }
        async with self._api_lock:
            wait = self._last_api + self.delay_s - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            text = await self._request_text(ARXIV_API, params=params)
            self._last_api = time.monotonic()
        return parse_arxiv_atom(text or "")

    async def body(self, arxiv_id: str) -> str | None:
        html = await self._request_text(ARXIV_HTML.format(arxiv_id=arxiv_id))
        if not html:
            return None
        return html_body_text(html) or None


class OpenAlexClient(ScholarClient):
    def __init__(self, *, mailto: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.mailto = mailto

    async def sample(
        self, *, from_date: str, to_date: str, n: int, seed: int, extra_filter: str = ""
    ) -> list[Paper]:
        n = min(n, OPENALEX_MAX_SAMPLE)
        filter_expr = (
            "type:article,has_doi:true,has_abstract:true,language:en,"
            f"from_publication_date:{from_date},to_publication_date:{to_date}"
        )
        if extra_filter:
            filter_expr += f",{extra_filter}"
        params = {
            "filter": filter_expr,
            "sample": n,
            "seed": seed,
            "per-page": n,
            "select": (
                "title,doi,ids,publication_date,primary_topic,"
                "primary_location,abstract_inverted_index"
            ),
        }
        if self.mailto:
            params["mailto"] = self.mailto
        payload, err = await self._request_json(
            "GET", OPENALEX_WORKS, params=params, headers={"User-Agent": USER_AGENT}
        )
        if err is not None or not isinstance(payload, dict):
            return []
        papers = []
        for work in payload.get("results") or []:
            paper = parse_openalex_work(work)
            if paper is not None:
                papers.append(paper)
        return papers

    async def sample_balanced(
        self, *, from_date: str, to_date: str, n: int, seed: int
    ) -> list[Paper]:
        per_domain = max(1, n // len(OPENALEX_DOMAINS))
        papers = []
        for domain_id in OPENALEX_DOMAINS.values():
            papers.extend(
                await self.sample(
                    from_date=from_date,
                    to_date=to_date,
                    n=per_domain,
                    seed=seed,
                    extra_filter=f"primary_topic.domain.id:{domain_id}",
                )
            )
        return papers


class EuropePmcClient(ScholarClient):
    async def recent(self, *, from_date: str, to_date: str, n: int, seed: int) -> list[Paper]:
        params = {
            "query": (
                'OPEN_ACCESS:y AND HAS_FT:y AND HAS_ABSTRACT:y AND LANG:"eng" '
                f"AND FIRST_PDATE:[{from_date} TO {to_date}]"
            ),
            "format": "json",
            "resultType": "core",
            "pageSize": min(1000, max(n * 5, 50)),
        }
        payload, err = await self._request_json(
            "GET", EUROPEPMC_SEARCH, params=params, headers={"User-Agent": USER_AGENT}
        )
        if err is not None or not isinstance(payload, dict):
            return []
        records = ((payload.get("resultList") or {}).get("result")) or []
        papers = []
        for rec in records:
            paper = parse_epmc_result(rec)
            if paper is not None:
                papers.append(paper)
        if len(papers) > n:
            papers = random.Random(seed).sample(papers, n)
        return papers

    async def body(self, pmcid: str) -> str | None:
        xml = await self._request_text(EUROPEPMC_XML.format(pmcid=pmcid))
        if not xml:
            return None
        return jats_body_text(xml) or None
