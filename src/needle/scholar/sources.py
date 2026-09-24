import asyncio
import random
import re
import ssl
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from xml.etree.ElementTree import Element, ParseError

import defusedxml.ElementTree as ET
import httpx
from defusedxml.common import DefusedXmlException

from needle.scholar.bodies import html_body_text, jats_body_text
from needle.scholar.models import Paper, coarse_domain
from needle.shared.search.base import USER_AGENT, HttpSearchClient, SourceError

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_OAI = "https://oaipmh.arxiv.org/oai"
ARXIV_HTML = "https://arxiv.org/html/{arxiv_id}"
EUROPEPMC_XML = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC{pmcid}/fullTextXML"
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
OAI_NS = {"oai": "http://www.openarchives.org/OAI/2.0/", "ax": "http://arxiv.org/OAI/arXiv/"}
ARXIV_ID_RE = re.compile(r"arxiv\.org/abs/(.+?)(v\d+)?$")
NEW_ARXIV_ID_RE = re.compile(r"^(\d{2})(\d{2})\.\d{4,5}$")
PMCID_URL_RE = re.compile(r"PMC(\d+)", re.IGNORECASE)

ARXIV_DOMAIN_QUERY = {
    "computer science": "cat:cs.*",
    "physical sciences": "(cat:physics.* OR cat:math.* OR cat:stat.* OR cat:cond-mat.* OR cat:astro-ph.*)",
    "life sciences": "cat:q-bio.*",
    "social sciences": "(cat:econ.* OR cat:q-fin.*)",
}
ARXIV_DOMAIN_OAI_SETS = {
    "computer science": ("cs",),
    "physical sciences": ("physics", "math", "stat"),
    "life sciences": ("q-bio",),
    "social sciences": ("econ", "q-fin"),
}
ARXIV_TLS_CIPHERS = "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:!aNULL:!DSS"
OAI_ANNOUNCE_LAG = (1, 4)


def _arxiv_ssl_context() -> ssl.SSLContext:
    ctx = httpx.create_ssl_context()
    ctx.set_ciphers(ARXIV_TLS_CIPHERS)
    return ctx


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
                domain=coarse_domain(category),
                arxiv_id=arxiv_id,
                doi=_norm_doi(_el_text(entry.find("arxiv:doi", ARXIV_NS))),
            )
        )
    return papers


def _shift_day(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def _first_version_month(arxiv_id: str, created: str) -> bool:
    m = NEW_ARXIV_ID_RE.match(arxiv_id)
    return m is not None and created[2:4] == m.group(1) and created[5:7] == m.group(2)


def parse_arxiv_oai(text: str, *, from_date: str, to_date: str) -> list[Paper]:
    try:
        root = ET.fromstring(text)
    except (ParseError, DefusedXmlException, ValueError):
        return []
    papers = []
    for meta in root.iterfind(".//oai:metadata/ax:arXiv", OAI_NS):
        arxiv_id = _el_text(meta.find("ax:id", OAI_NS))
        title = _el_text(meta.find("ax:title", OAI_NS))
        abstract = _el_text(meta.find("ax:abstract", OAI_NS))
        created = _el_text(meta.find("ax:created", OAI_NS))
        if not arxiv_id or not title or not abstract or not created:
            continue
        if not from_date <= created <= to_date or not _first_version_month(arxiv_id, created):
            continue
        published = _parse_dt(created)
        if published is None:
            continue
        category = (_el_text(meta.find("ax:categories", OAI_NS)) or "").split(" ", 1)[0]
        doi = (_el_text(meta.find("ax:doi", OAI_NS)) or "").split(" ", 1)[0]
        papers.append(
            Paper(
                suite="arxiv",
                title=title,
                abstract=abstract,
                published=published,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                domain=coarse_domain(category),
                arxiv_id=arxiv_id,
                doi=_norm_doi(doi),
            )
        )
    return papers


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
    suite: str
    default_headers = {"User-Agent": USER_AGENT}
    retry_attempts = 4
    retry_base_s = 2.0

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_concurrency", 8)
        super().__init__(**kwargs)

    def _source_error(self, err: dict[str, str]) -> SourceError:
        return SourceError(f"{self.suite}: {err['error_type']}: {err['error_message']}")

    async def _fetch_text(self, url: str, *, params: dict[str, Any] | None = None) -> str:
        text, err = await self._request_text(url, params=params)
        if err is not None:
            raise self._source_error(err)
        assert text is not None
        return text


class ArxivClient(ScholarClient):
    suite = "arxiv"
    ssl_context = _arxiv_ssl_context()

    def __init__(self, *, delay_s: float = 3.0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.delay_s = delay_s
        self.oai_fallbacks = 0
        self._api_lock = asyncio.Lock()
        self._last_api = 0.0

    async def _paced_fetch(self, url: str, params: dict[str, Any]) -> str:
        async with self._api_lock:
            wait = self._last_api + self.delay_s - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                return await self._fetch_text(url, params=params)
            finally:
                self._last_api = time.monotonic()

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
        try:
            text = await self._paced_fetch(ARXIV_API, params)
        except SourceError:
            self.oai_fallbacks += 1
            return await self.oai_domain(domain, from_date=from_date, to_date=to_date)
        return parse_arxiv_atom(text)

    async def oai_domain(self, domain: str, *, from_date: str, to_date: str) -> list[Paper]:
        papers: list[Paper] = []
        for oai_set in ARXIV_DOMAIN_OAI_SETS[domain]:
            params = {
                "verb": "ListRecords",
                "metadataPrefix": "arXiv",
                "from": _shift_day(from_date, OAI_ANNOUNCE_LAG[0]),
                "until": _shift_day(to_date, OAI_ANNOUNCE_LAG[1]),
                "set": oai_set,
            }
            text = await self._paced_fetch(ARXIV_OAI, params)
            papers.extend(parse_arxiv_oai(text, from_date=from_date, to_date=to_date))
        return papers

    async def body(self, arxiv_id: str) -> str | None:
        html = await self._get_text(ARXIV_HTML.format(arxiv_id=arxiv_id))
        if not html:
            return None
        return html_body_text(html) or None


class EuropePmcClient(ScholarClient):
    suite = "europepmc"

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
        payload, err = await self._request_json("GET", EUROPEPMC_SEARCH, params=params)
        if err is not None:
            raise self._source_error(err)
        if not isinstance(payload, dict):
            raise self._source_error({"error_type": "bad_json", "error_message": "not an object"})
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
        xml = await self._get_text(EUROPEPMC_XML.format(pmcid=pmcid))
        if not xml:
            return None
        return jats_body_text(xml) or None
