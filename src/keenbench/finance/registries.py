import re
from typing import Any

from keenbench.shared.search.base import USER_AGENT, HttpSearchClient

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_ENTITYDATA = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
GLEIF_API = "https://api.gleif.org/api/v1/lei-records"

COMPANY_CLASSES = {
    "Q4830453",
    "Q783794",
    "Q6881511",
    "Q891723",
    "Q18388277",
    "Q43229",
    "Q161726",
}

TIME_YEAR_RE = re.compile(r"([+-]?\d{1,4})-")


def _datavalue(stmt: dict) -> Any:
    return (stmt.get("mainsnak") or {}).get("datavalue", {}).get("value")


def _entity_id(stmt: dict) -> str | None:
    v = _datavalue(stmt)
    return v.get("id") if isinstance(v, dict) else None


def _time_year(stmt: dict) -> int | None:
    v = _datavalue(stmt)
    t = v.get("time") if isinstance(v, dict) else None
    if t:
        m = TIME_YEAR_RE.search(t)
        if m:
            return abs(int(m.group(1)))
    return None


def _string(stmt: dict) -> str | None:
    v = _datavalue(stmt)
    return v if isinstance(v, str) else None


def _quantity(stmt: dict) -> int | None:
    v = _datavalue(stmt)
    if isinstance(v, dict) and "amount" in v:
        try:
            return int(float(v["amount"]))
        except ValueError:
            return None
    return None


def _qual_year(stmt: dict, pcode: str) -> int | None:
    for q in (stmt.get("qualifiers") or {}).get(pcode, []):
        t = (q.get("datavalue") or {}).get("value", {})
        if isinstance(t, dict) and t.get("time"):
            m = TIME_YEAR_RE.search(t["time"])
            if m:
                return abs(int(m.group(1)))
    return None


def current_ceo(claims: dict) -> tuple[str | None, int | None]:
    candidates = []
    for stmt in claims.get("P169", []):
        if stmt.get("rank") == "deprecated" or "P582" in (stmt.get("qualifiers") or {}):
            continue
        pid = _entity_id(stmt)
        if not pid:
            continue
        candidates.append((stmt.get("rank") == "preferred", _qual_year(stmt, "P580") or 0, pid))
    if not candidates:
        return None, None
    _, year, pid = max(candidates)
    return pid, year or None


def founded_year(claims: dict) -> int | None:
    for stmt in claims.get("P571", []):
        y = _time_year(stmt)
        if y:
            return y
    return None


def website(claims: dict) -> str | None:
    for stmt in claims.get("P856", []):
        url = _string(stmt)
        if url:
            return url
    return None


def employees(claims: dict) -> tuple[int | None, int | None]:
    best, best_year = None, -1
    for stmt in claims.get("P1128", []):
        count = _quantity(stmt)
        if count is None:
            continue
        year = _qual_year(stmt, "P585") or 0
        if year >= best_year:
            best, best_year = count, year
    return best, (best_year if best_year > 0 else None)


def lei(claims: dict) -> str | None:
    for stmt in claims.get("P1278", []):
        value = _string(stmt)
        if value:
            return value
    return None


class RegistryClient(HttpSearchClient):
    def __init__(
        self,
        *,
        timeout_s: float = 30.0,
        max_concurrency: int = 4,
        user_agent: str = USER_AGENT,
    ) -> None:
        super().__init__(
            timeout_s=timeout_s,
            max_concurrency=max_concurrency,
            default_headers={"User-Agent": user_agent},
        )

    async def _get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        payload, err = await self._request_json("GET", url, params=params, headers=headers)
        return None if err is not None else payload


class WikidataClient(RegistryClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._entities: dict[str, dict] = {}

    async def entity(self, qid: str) -> dict:
        if qid in self._entities:
            return self._entities[qid]
        payload = await self._get(WIKIDATA_ENTITYDATA.format(qid=qid))
        claims = (((payload or {}).get("entities") or {}).get(qid) or {}).get("claims", {})
        self._entities[qid] = claims
        return claims

    async def resolve(self, name: str) -> str | None:
        payload = await self._get(
            WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "type": "item",
                "format": "json",
                "limit": 5,
            },
        )
        for hit in (payload or {}).get("search", []):
            qid = hit.get("id")
            if not qid:
                continue
            claims = await self.entity(qid)
            p31 = {_entity_id(s) for s in claims.get("P31", [])}
            if p31 & COMPANY_CLASSES or {"P1278", "P414", "P249"} & claims.keys():
                return qid
        return None

    async def labels_and_aliases(self, ids: list[str]) -> dict[str, tuple[str, list[str]]]:
        out: dict[str, tuple[str, list[str]]] = {}
        ids = [i for i in dict.fromkeys(ids) if i]
        for i in range(0, len(ids), 50):
            payload = await self._get(
                WIKIDATA_API,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(ids[i : i + 50]),
                    "props": "labels|aliases",
                    "languages": "en",
                    "format": "json",
                },
            )
            for qid, ent in ((payload or {}).get("entities") or {}).items():
                label = ((ent.get("labels") or {}).get("en") or {}).get("value")
                aliases = [
                    a["value"]
                    for a in ((ent.get("aliases") or {}).get("en") or [])
                    if a.get("value")
                ]
                if label:
                    out[qid] = (label, aliases)
        return out

    async def country_qid(self, claims: dict) -> str | None:
        for stmt in claims.get("P17", []):
            q = _entity_id(stmt)
            if q:
                return q
        for stmt in claims.get("P159", []):
            loc = _entity_id(stmt)
            if not loc:
                continue
            loc_claims = await self.entity(loc)
            for s2 in loc_claims.get("P17", []):
                q = _entity_id(s2)
                if q:
                    return q
        return None


class SecClient(RegistryClient):
    def __init__(self, *, timeout_s: float = 40.0, **kwargs: Any) -> None:
        super().__init__(timeout_s=timeout_s, **kwargs)
        self._tickers: list[dict] | None = None

    async def tickers(self, limit: int = 0) -> list[dict]:
        if self._tickers is None:
            payload = await self._get(SEC_TICKERS_URL)
            rows = payload.values() if isinstance(payload, dict) else (payload or [])
            out = []
            for row in rows:
                ticker = (row.get("ticker") or "").strip().upper()
                title = (row.get("title") or "").strip()
                if ticker and title:
                    out.append(
                        {"ticker": ticker, "title": title, "cik": int(row.get("cik_str", 0))}
                    )
            self._tickers = out
        return self._tickers[:limit] if limit > 0 else list(self._tickers)

    async def companyfacts(self, cik: int) -> dict | None:
        payload = await self._get(SEC_FACTS_URL.format(cik=int(cik)))
        facts = ((payload or {}).get("facts") or {}).get("us-gaap")
        return facts or None


class GleifClient(RegistryClient):
    async def lei_by_name(self, legal_name: str) -> str | None:
        payload = await self._get(
            GLEIF_API,
            params={"filter[entity.legalName]": legal_name, "page[size]": 5},
            headers={"Accept": "application/vnd.api+json"},
        )
        wanted = legal_name.strip().lower()
        for rec in (payload or {}).get("data") or []:
            attrs = rec.get("attributes") or {}
            record_name = ((attrs.get("entity") or {}).get("legalName") or {}).get("name", "")
            if record_name.strip().lower() == wanted:
                return attrs.get("lei") or rec.get("id")
        return None
