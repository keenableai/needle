import base64
import binascii
import xml.etree.ElementTree as ET
from typing import Any

from needle.shared.search.base import HttpSearchClient, SearchResult
from needle.shared.search.queryops import QueryOps, clipped_text, parse_ops

MAX_GROUPS = 100
MAX_PASSAGES = 5
MAX_QUERY_CHARS = 400
NO_RESULTS_CODE = "15"


def _operators(ops: QueryOps) -> list[str]:
    terms: list[str] = []
    if len(ops.sites) == 1:
        terms.append(f"site:{ops.sites[0]}")
    elif ops.sites:
        terms.append("(" + " | ".join(f"site:{s}" for s in ops.sites) + ")")
    lo = ops.after.strftime("%Y%m%d") if ops.after else None
    hi = ops.before.strftime("%Y%m%d") if ops.before else None
    if lo and hi:
        terms.append(f"date:{lo}..{hi}")
    elif lo:
        terms.append(f"date:>={lo}")
    elif hi:
        terms.append(f"date:<={hi}")
    return terms


def query_text(query: str) -> str:
    ops = parse_ops(query)
    terms = _operators(ops)
    budget = MAX_QUERY_CHARS - sum(len(t) + 1 for t in terms)
    return " ".join([clipped_text(ops.text, budget), *terms]).strip()


def _text(elem: ET.Element | None) -> str | None:
    return "".join(elem.itertext()).strip() or None if elem is not None else None


class YandexClient(HttpSearchClient):
    engine = "yandex"
    base_url = "https://searchapi.api.cloud.yandex.net/v2"

    def __init__(self, *, api_key: str, folder_id: str, timeout_s: float = 30.0) -> None:
        super().__init__(api_key=api_key, timeout_s=timeout_s)
        self.folder_id = folder_id

    async def search(
        self, query: str, *, num_results: int = 10
    ) -> tuple[list[SearchResult] | None, dict[str, str] | None]:
        body: dict[str, Any] = {
            "query": {
                "searchType": "SEARCH_TYPE_COM",
                "queryText": query_text(query),
                "familyMode": "FAMILY_MODE_NONE",
            },
            "groupSpec": {
                "groupMode": "GROUP_MODE_FLAT",
                "groupsOnPage": min(num_results, MAX_GROUPS),
                "docsInGroup": 1,
            },
            "maxPassages": MAX_PASSAGES,
            "l10N": "LOCALIZATION_EN",
            "responseFormat": "FORMAT_XML",
            "folderId": self.folder_id,
        }
        payload, err = await self._request_json(
            "POST",
            f"{self.base_url}/web/search",
            json=body,
            headers={"Authorization": f"Api-Key {self.api_key}"},
        )
        if err is not None:
            return None, err
        raw = payload.get("rawData") if isinstance(payload, dict) else None
        if not raw:
            return [], None
        try:
            root = ET.fromstring(base64.b64decode(raw))
        except (binascii.Error, ValueError, ET.ParseError) as exc:
            return None, {"error_type": "bad_xml", "error_message": str(exc)}
        error = root.find("./response/error")
        if error is not None and error.get("code") != NO_RESULTS_CODE:
            return None, {
                "error_type": "api_error",
                "error_message": f"{error.get('code')}: {_text(error)}",
            }
        results: list[SearchResult] = []
        for doc in root.iterfind("./response/results/grouping/group/doc"):
            url = _text(doc.find("url"))
            if not url:
                continue
            passages = [p for p in (_text(e) for e in doc.iterfind("passages/passage")) if p]
            results.append(
                SearchResult(
                    url=url,
                    title=_text(doc.find("title")),
                    snippet=" ".join(passages) or _text(doc.find("headline")),
                    published_date=_text(doc.find("modtime")),
                )
            )
        return results[:num_results], None
