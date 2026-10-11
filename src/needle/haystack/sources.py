from typing import Any
from urllib.parse import quote

from needle.finance.sources import html_text
from needle.shared.search.base import USER_AGENT, HttpSearchClient

FR_DOCUMENTS_URL = "https://www.federalregister.gov/api/v1/documents.json"
FR_FIELDS = (
    "title",
    "document_number",
    "publication_date",
    "html_url",
    "raw_text_url",
    "agency_names",
    "page_length",
)
FR_MIN_PAGES = 6
WIKI_API_URL = "https://en.wikipedia.org/w/api.php"
WIKI_FEATURED_CATEGORY = "Category:Featured articles"
WIKI_PAGE_URL = "https://en.wikipedia.org/wiki/{title}"


def parse_fr_documents(payload: Any) -> list[dict]:
    results = payload.get("results") if isinstance(payload, dict) else None
    docs = []
    for r in results if isinstance(results, list) else []:
        if not isinstance(r, dict):
            continue
        if not r.get("title") or not r.get("raw_text_url") or not r.get("html_url"):
            continue
        if int(r.get("page_length") or 0) < FR_MIN_PAGES:
            continue
        docs.append(
            {
                "title": str(r["title"]),
                "document_number": str(r.get("document_number") or ""),
                "publication_date": str(r.get("publication_date") or ""),
                "html_url": str(r["html_url"]),
                "raw_text_url": str(r["raw_text_url"]),
                "agency_names": [str(a) for a in r.get("agency_names") or []],
            }
        )
    return docs


def parse_wiki_members(payload: Any) -> tuple[list[str], str | None]:
    if not isinstance(payload, dict):
        return [], None
    members = (payload.get("query") or {}).get("categorymembers") or []
    titles = [
        str(m["title"])
        for m in members
        if isinstance(m, dict) and m.get("title") and m.get("ns") == 0
    ]
    cont = payload.get("continue") or {}
    cmcontinue = cont.get("cmcontinue") if isinstance(cont, dict) else None
    return titles, str(cmcontinue) if cmcontinue else None


def parse_wiki_extract(payload: Any) -> tuple[str, str] | None:
    if not isinstance(payload, dict):
        return None
    pages = (payload.get("query") or {}).get("pages") or {}
    for page in pages.values() if isinstance(pages, dict) else []:
        if not isinstance(page, dict) or "missing" in page:
            continue
        title = page.get("title")
        extract = page.get("extract")
        if title and extract:
            return str(title), str(extract)
    return None


def wiki_url(title: str) -> str:
    return WIKI_PAGE_URL.format(title=quote(title.replace(" ", "_")))


class HaystackSourceClient(HttpSearchClient):
    default_headers = {"User-Agent": USER_AGENT}

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        payload, err = await self._request_json("GET", url, params=params)
        return None if err is not None else payload


class FederalRegisterClient(HaystackSourceClient):
    async def rules(self, *, pages: int = 3, per_page: int = 100) -> list[dict]:
        docs: list[dict] = []
        for page in range(1, pages + 1):
            payload = await self._get(
                FR_DOCUMENTS_URL,
                params={
                    "conditions[type][]": "RULE",
                    "order": "newest",
                    "per_page": per_page,
                    "page": page,
                    "fields[]": list(FR_FIELDS),
                },
            )
            docs.extend(parse_fr_documents(payload))
            results = payload.get("results") if isinstance(payload, dict) else None
            if not results:
                break
        return docs

    async def document_text(self, raw_text_url: str) -> str | None:
        raw = await self._get_text(raw_text_url)
        if raw is None:
            return None
        return html_text(raw) or None


class WikiClient(HaystackSourceClient):
    async def featured_titles(self, *, max_pages: int = 20) -> list[str]:
        titles: list[str] = []
        cmcontinue: str | None = None
        for _ in range(max_pages):
            params: dict[str, Any] = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": WIKI_FEATURED_CATEGORY,
                "cmtype": "page",
                "cmlimit": "500",
                "format": "json",
            }
            if cmcontinue:
                params["cmcontinue"] = cmcontinue
            payload = await self._get(WIKI_API_URL, params=params)
            got, cmcontinue = parse_wiki_members(payload)
            titles.extend(got)
            if not cmcontinue:
                break
        return titles

    async def extract(self, title: str) -> tuple[str, str] | None:
        payload = await self._get(
            WIKI_API_URL,
            params={
                "action": "query",
                "prop": "extracts",
                "explaintext": "1",
                "redirects": "1",
                "format": "json",
                "titles": title,
            },
        )
        return parse_wiki_extract(payload)
