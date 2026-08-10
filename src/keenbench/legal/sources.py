import os
import re
from datetime import date, datetime
from typing import Any
from xml.etree.ElementTree import ParseError

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from keenbench.legal.models import Case, CodeSection
from keenbench.shared.sampling import shuffle_indices
from keenbench.shared.search.base import USER_AGENT, HttpSearchClient

COURTLISTENER_SEARCH = "https://www.courtlistener.com/api/rest/v4/search/"
ECFR_TITLES = "https://www.ecfr.gov/api/versioner/v1/titles.json"
ECFR_STRUCTURE = "https://www.ecfr.gov/api/versioner/v1/structure/{issue_date}/title-{title}.json"
ECFR_SECTION = "https://www.ecfr.gov/api/versioner/v1/full/{issue_date}/title-{title}.xml"

SECTION_ID_RE = re.compile(r"^\d+\.[\w.\-]+$")


def _parse_date(raw: str | None) -> date | None:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def parse_search_case(rec: dict[str, Any]) -> Case | None:
    case_name = " ".join((rec.get("caseName") or "").split())
    docket = (rec.get("docketNumber") or "").strip()
    filed = _parse_date(rec.get("dateFiled"))
    cluster_id = rec.get("cluster_id")
    court_id = (rec.get("court_id") or "").strip()
    if not case_name or filed is None or not cluster_id or not court_id:
        return None
    citations = tuple(str(c).strip() for c in rec.get("citation") or [] if str(c).strip())
    if not docket and not citations:
        return None
    return Case(
        court_id=court_id,
        case_name=case_name,
        docket=docket,
        citations=citations,
        date_filed=filed,
        cluster_id=int(cluster_id),
        absolute_url=str(rec.get("absolute_url") or ""),
    )


class CourtListenerClient(HttpSearchClient):
    def __init__(self, *, api_token: str | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("max_concurrency", 2)
        self.api_token = api_token or os.environ.get("COURTLISTENER_API_TOKEN") or None
        headers = {"User-Agent": USER_AGENT}
        if self.api_token:
            headers["Authorization"] = f"Token {self.api_token}"
        kwargs.setdefault("default_headers", headers)
        super().__init__(**kwargs)

    async def opinions(
        self,
        court: str,
        *,
        filed_after: date,
        filed_before: date,
        published_only: bool = True,
    ) -> list[Case]:
        params: dict[str, str] = {
            "type": "o",
            "court": court,
            "filed_after": filed_after.strftime("%m/%d/%Y"),
            "filed_before": filed_before.strftime("%m/%d/%Y"),
            "order_by": "dateFiled desc",
        }
        if published_only:
            params["stat_Published"] = "on"
        payload, err = await self._request_json("GET", COURTLISTENER_SEARCH, params=params)
        if err is not None or not isinstance(payload, dict):
            return []
        cases = []
        seen: set[int] = set()
        for rec in payload.get("results") or []:
            case = parse_search_case(rec)
            if case is not None and case.cluster_id not in seen:
                seen.add(case.cluster_id)
                cases.append(case)
        return cases


def walk_structure_sections(node: dict[str, Any], part: str = "") -> list[tuple[str, str, str]]:
    if node.get("reserved"):
        return []
    node_type = node.get("type")
    identifier = str(node.get("identifier") or "")
    if node_type == "part":
        part = identifier
    if node_type == "section":
        label = " ".join(str(node.get("label_description") or "").split())
        if part and label and SECTION_ID_RE.match(identifier):
            return [(part, identifier, label)]
        return []
    out = []
    for child in node.get("children") or []:
        out.extend(walk_structure_sections(child, part))
    return out


def parse_section_xml(
    xml_text: str, *, title_num: int, part: str, section: str, heading: str
) -> CodeSection | None:
    try:
        root = ET.fromstring(xml_text)
    except (ParseError, DefusedXmlException, ValueError):
        return None
    paragraphs = []
    for p in root.iter("P"):
        text = " ".join("".join(p.itertext()).split())
        if text:
            paragraphs.append(text)
    body = " ".join(paragraphs)
    if not body:
        return None
    head = root.find("HEAD")
    head_text = " ".join("".join(head.itertext()).split()) if head is not None else ""
    return CodeSection(
        title_num=title_num,
        part=part,
        section=section,
        heading=head_text or heading,
        text=body,
    )


class EcfrClient(HttpSearchClient):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_concurrency", 4)
        kwargs.setdefault("default_headers", {"User-Agent": USER_AGENT})
        super().__init__(**kwargs)
        self._issue_dates: dict[int, str] | None = None

    async def _get_json(self, url: str, **kwargs: Any) -> Any:
        payload, err = await self._request_json("GET", url, **kwargs)
        return None if err is not None else payload

    async def issue_date(self, title_num: int) -> str | None:
        if self._issue_dates is None:
            payload = await self._get_json(ECFR_TITLES)
            self._issue_dates = {}
            for rec in (payload or {}).get("titles") or []:
                number = rec.get("number")
                up_to_date = rec.get("up_to_date_as_of")
                if number and up_to_date and not rec.get("reserved"):
                    self._issue_dates[int(number)] = str(up_to_date)
        return self._issue_dates.get(title_num)

    async def sections(self, title_num: int, *, n: int, seed: int) -> list[tuple[str, str, str]]:
        issue = await self.issue_date(title_num)
        if not issue:
            return []
        payload = await self._get_json(ECFR_STRUCTURE.format(issue_date=issue, title=title_num))
        if not isinstance(payload, dict):
            return []
        entries = walk_structure_sections(payload)
        if len(entries) > n:
            perm = shuffle_indices(len(entries), seed ^ title_num)
            entries = [entries[i] for i in perm[:n]]
        return entries

    async def section(
        self, title_num: int, part: str, identifier: str, heading: str
    ) -> CodeSection | None:
        issue = await self.issue_date(title_num)
        if not issue:
            return None
        xml_text = await self._get_text(
            ECFR_SECTION.format(issue_date=issue, title=title_num),
            params={"part": part, "section": identifier},
        )
        if xml_text is None:
            return None
        return parse_section_xml(
            xml_text, title_num=title_num, part=part, section=identifier, heading=heading
        )


def month_windows(*, now: datetime, months_back: int) -> list[tuple[date, date]]:
    windows = []
    year, month = now.year, now.month
    for _ in range(months_back):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        first = date(year, month, 1)
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        windows.append((first, date(next_year, next_month, 1)))
    return windows
