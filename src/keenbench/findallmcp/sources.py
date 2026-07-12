import re
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from keenbench.findallmcp.models import Entity, Task
from keenbench.shared.search.base import HttpSearchClient

USER_AGENT = "keenbench/0.1 (contact@keenable.ai)"

HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index"
LL2_LAUNCHES = "https://ll.thespacedevs.com/2.2.0/launch/"
FEDREG_DOCS = "https://www.federalregister.gov/api/v1/documents.json"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
GITHUB_SEARCH = "https://api.github.com/search/repositories"
NVD_CVES = "https://services.nvd.nist.gov/rest/json/cves/2.0"

HN_POINT_LADDER = (500, 400, 300, 250, 200, 150)
SITELINK_LADDER = (40, 30, 25, 20, 15)
STAR_LADDER = (5000, 3000, 2000, 1000, 500)
GOLD_MIN, GOLD_MAX = 8, 40

EDGAR_PHRASES = (
    "material cybersecurity incident",
    "reverse stock split",
    "at-the-market offering agreement",
    "special committee of the board",
    "voluntary petitions under chapter 11",
)

_DIGIT_RE = re.compile(r"\d")
_DISPLAY_RE = re.compile(r"^(.*?)\s*(?:\(([^)]*)\))?\s*\(CIK (\d+)\)\s*$")
_PAREN_RE = re.compile(r"\s*\([^)]*\)")


class HnClient(HttpSearchClient):
    async def show_hn(self, *, since: date, until: date) -> list[dict[str, Any]]:
        lower = int(datetime(since.year, since.month, since.day).timestamp())
        upper = int(datetime(until.year, until.month, until.day).timestamp())
        hits: list[dict[str, Any]] = []
        seen: set[str] = set()
        while True:
            params = {
                "tags": "show_hn",
                "numericFilters": f"created_at_i>{lower},created_at_i<{upper}",
                "hitsPerPage": 1000,
            }
            payload, err = await self._request_json(
                "GET", HN_SEARCH, params=params, headers={"User-Agent": USER_AGENT}
            )
            if err is not None or not isinstance(payload, dict):
                return []
            page = payload.get("hits") or []
            for h in page:
                title = " ".join((h.get("title") or "").split())
                if title and h.get("objectID") and str(h["objectID"]) not in seen:
                    seen.add(str(h["objectID"]))
                    hits.append(
                        {
                            "id": str(h["objectID"]),
                            "title": title,
                            "url": h.get("url")
                            or f"https://news.ycombinator.com/item?id={h['objectID']}",
                            "points": int(h.get("points") or 0),
                        }
                    )
            stamps = [int(h.get("created_at_i") or 0) for h in page]
            if len(page) < 1000 or not stamps or min(stamps) <= lower:
                return hits
            upper = min(stamps)


class EdgarFtsClient(HttpSearchClient):
    async def filings(
        self, *, phrase: str, forms: str, start: date, end: date, max_hits: int = 200
    ) -> list[dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        offset = 0
        while offset < max_hits:
            params = {
                "q": f'"{phrase}"' if phrase else "",
                "forms": forms,
                "dateRange": "custom",
                "startdt": start.isoformat(),
                "enddt": end.isoformat(),
                "from": offset,
            }
            payload, err = await self._request_json(
                "GET",
                EDGAR_FTS,
                params={k: v for k, v in params.items() if v != ""},
                headers={"User-Agent": USER_AGENT},
            )
            if err is not None or not isinstance(payload, dict):
                break
            hits = ((payload.get("hits") or {}).get("hits")) or []
            if not hits:
                break
            for h in hits:
                src = h.get("_source") or {}
                for display in src.get("display_names") or []:
                    m = _DISPLAY_RE.match(display)
                    if not m:
                        continue
                    name, ticker, cik = m.group(1).strip(), m.group(2), m.group(3)
                    if cik not in out:
                        aliases = [a for a in (ticker,) if a]
                        out[cik] = {"cik": cik, "name": name, "aliases": aliases}
            offset += len(hits)
            total = ((payload.get("hits") or {}).get("total") or {}).get("value") or 0
            if offset >= total:
                break
        return list(out.values())


class LaunchLibraryClient(HttpSearchClient):
    async def launches(self, *, since: date, until: date) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        url: str | None = LL2_LAUNCHES
        params: dict[str, Any] | None = {
            "net__gte": f"{since.isoformat()}T00:00:00Z",
            "net__lte": f"{until.isoformat()}T00:00:00Z",
            "limit": 100,
            "mode": "list",
        }
        while url:
            payload, err = await self._request_json(
                "GET", url, params=params, headers={"User-Agent": USER_AGENT}
            )
            if err is not None or not isinstance(payload, dict):
                return []
            for r in payload.get("results") or []:
                name = " ".join(str(r.get("name") or "").split())
                if r.get("id") and name:
                    out.append({"id": str(r["id"]), "name": name})
            url = payload.get("next")
            params = None
        return out


class FedRegClient(HttpSearchClient):
    async def executive_orders(self, *, start: date, end: date) -> list[dict[str, Any]]:
        params = {
            "conditions[type][]": "PRESDOCU",
            "conditions[presidential_document_type][]": "executive_order",
            "conditions[publication_date][gte]": start.isoformat(),
            "conditions[publication_date][lte]": end.isoformat(),
            "fields[]": ["title", "document_number", "executive_order_number"],
            "per_page": 100,
        }
        payload, err = await self._request_json(
            "GET", FEDREG_DOCS, params=params, headers={"User-Agent": USER_AGENT}
        )
        if err is not None or not isinstance(payload, dict):
            return []
        out = []
        for r in payload.get("results") or []:
            if r.get("document_number") and r.get("title"):
                out.append(r)
        return out

    async def rule_count(self, *, agency: str, start: date, end: date) -> int | None:
        params = {
            "conditions[type][]": "RULE",
            "conditions[agencies][]": agency,
            "conditions[publication_date][gte]": start.isoformat(),
            "conditions[publication_date][lte]": end.isoformat(),
            "per_page": 1,
        }
        payload, err = await self._request_json(
            "GET", FEDREG_DOCS, params=params, headers={"User-Agent": USER_AGENT}
        )
        if err is not None or not isinstance(payload, dict):
            return None
        count = payload.get("count")
        return int(count) if isinstance(count, int) else None


class WikidataClient(HttpSearchClient):
    async def deaths(self, *, since: date, until: date, min_links: int) -> list[dict[str, Any]]:
        query = (
            "SELECT ?person ?personLabel ?links WHERE { "
            "?person wdt:P570 ?dod . "
            f'FILTER(?dod >= "{since.isoformat()}T00:00:00Z"^^xsd:dateTime && '
            f'?dod < "{until.isoformat()}T00:00:00Z"^^xsd:dateTime) '
            "?person wdt:P31 wd:Q5 . "
            "?person wikibase:sitelinks ?links . "
            f"FILTER(?links >= {min_links}) "
            'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }'
        )
        payload, err = await self._request_json(
            "GET",
            WIKIDATA_SPARQL,
            params={"query": query},
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        )
        if err is not None or not isinstance(payload, dict):
            return []
        out = []
        for b in (payload.get("results") or {}).get("bindings") or []:
            qid = str(b.get("person", {}).get("value") or "").rsplit("/", 1)[-1]
            label = str(b.get("personLabel", {}).get("value") or "")
            links = int(b.get("links", {}).get("value") or 0)
            if qid and label and label != qid:
                out.append({"qid": qid, "name": label, "links": links})
        return out


class GithubClient(HttpSearchClient):
    async def repos(
        self, *, since: date, until: date, min_stars: int, per_page: int = 100
    ) -> tuple[int | None, list[dict[str, Any]]]:
        params = {
            "q": f"created:{since.isoformat()}..{until.isoformat()} stars:>={min_stars}",
            "per_page": per_page,
        }
        payload, err = await self._request_json(
            "GET",
            GITHUB_SEARCH,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        )
        if err is not None or not isinstance(payload, dict):
            return None, []
        total = payload.get("total_count")
        items = [
            {"full_name": str(r["full_name"]), "name": str(r.get("name") or "")}
            for r in payload.get("items") or []
            if r.get("full_name")
        ]
        return (int(total) if isinstance(total, int) else None), items


class NvdClient(HttpSearchClient):
    async def cve_count(self, *, since: date, until: date) -> int | None:
        params = {
            "pubStartDate": f"{since.isoformat()}T00:00:00.000",
            "pubEndDate": f"{until.isoformat()}T23:59:59.999",
            "resultsPerPage": 1,
        }
        payload, err = await self._request_json(
            "GET", NVD_CVES, params=params, headers={"User-Agent": USER_AGENT}
        )
        if err is not None or not isinstance(payload, dict):
            return None
        total = payload.get("totalResults")
        return int(total) if isinstance(total, int) else None


def hn_entity(hit: dict[str, Any]) -> Entity:
    return Entity(key=hit["id"], name=hit["title"], aliases=(hit["url"],))


async def hn_tasks(client: HnClient, *, now: datetime) -> list[Task]:
    until = now.date()
    since = until - timedelta(days=30)
    window = f"between {since.isoformat()} and {until.isoformat()} (UTC)"
    tasks: list[Task] = []

    posts = await client.show_hn(since=since, until=until)

    chosen: list[dict[str, Any]] | None = None
    chosen_points = None
    for min_points in HN_POINT_LADDER:
        hits = [h for h in posts if h["points"] >= min_points]
        if GOLD_MIN <= len(hits) <= GOLD_MAX:
            chosen, chosen_points = hits, min_points
            break
        if hits and len(hits) > GOLD_MAX:
            break
    if chosen:
        tasks.append(
            Task(
                suite="hn",
                bucket="enumerate",
                prompt=(
                    f"Find ALL Show HN posts on Hacker News submitted {window} that reached "
                    f"at least {chosen_points} points. Be exhaustive - completeness is scored. "
                    'Respond with JSON only: {"items": [{"name": "<post title>", '
                    '"url": "<product or HN url>"}, ...]}'
                ),
                entities=tuple(hn_entity(h) for h in chosen),
                provenance={"since": since.isoformat(), "min_points": chosen_points},
            )
        )

    base = [h for h in posts if h["points"] >= 100]
    if len(base) >= 30:
        with_digit = sum(1 for h in base if _DIGIT_RE.search(h["title"]))
        tasks.append(
            Task(
                suite="hn",
                bucket="stat",
                prompt=(
                    f"Consider ALL Show HN posts submitted {window} that reached at least "
                    f"100 points. What fraction of their titles contain a digit? "
                    'Respond with JSON only: {"value": <number between 0 and 1>}'
                ),
                stat_value=with_digit / len(base),
                stat_rel_tol=0.25,
                provenance={"since": since.isoformat(), "population": len(base)},
            )
        )
        tasks.append(
            Task(
                suite="hn",
                bucket="stat",
                prompt=(
                    f"How many Show HN posts submitted {window} reached at least 100 points? "
                    'Respond with JSON only: {"value": <integer>}'
                ),
                stat_value=float(len(base)),
                stat_rel_tol=0.2,
                provenance={"since": since.isoformat(), "min_points": 100},
            )
        )
    return tasks


async def edgar_tasks(client: EdgarFtsClient, *, now: datetime) -> list[Task]:
    end = now.date()
    start = end - timedelta(days=45)
    window = f"between {start.isoformat()} and {end.isoformat()}"
    tasks: list[Task] = []
    for phrase in EDGAR_PHRASES:
        companies = await client.filings(phrase=phrase, forms="8-K", start=start, end=end)
        if not GOLD_MIN <= len(companies) <= GOLD_MAX:
            continue
        tasks.append(
            Task(
                suite="edgar",
                bucket="enumerate",
                prompt=(
                    f"Find ALL public companies that filed an 8-K with the SEC {window} "
                    f'containing the exact phrase "{phrase}". Be exhaustive - completeness '
                    'is scored. Respond with JSON only: {"items": [{"name": '
                    '"<company name>"}, ...]}'
                ),
                entities=tuple(
                    Entity(key=c["cik"], name=c["name"], aliases=tuple(c["aliases"]))
                    for c in companies
                ),
                provenance={"phrase": phrase, "start": start.isoformat(), "forms": "8-K"},
            )
        )
        if len(tasks) >= 3:
            break

    s1 = await client.filings(phrase="", forms="S-1", start=start, end=end, max_hits=1000)
    if len(s1) >= 20:
        tasks.append(
            Task(
                suite="edgar",
                bucket="stat",
                prompt=(
                    f"How many distinct companies filed an S-1 registration statement "
                    f"with the SEC {window}? "
                    'Respond with JSON only: {"value": <integer>}'
                ),
                stat_value=float(len(s1)),
                stat_rel_tol=0.25,
                provenance={"forms": "S-1", "start": start.isoformat()},
            )
        )
    return tasks


def launch_entities(hits: list[dict[str, Any]]) -> tuple[Entity, ...]:
    names = []
    for hit in hits:
        _, _, mission = hit["name"].partition(" | ")
        names.append(mission.strip() or hit["name"])
    stripped = [_PAREN_RE.sub("", n).strip() for n in names]
    counts = Counter(s.lower() for s in stripped if s)
    out = []
    for hit, name, plain in zip(hits, names, stripped, strict=True):
        aliases = [hit["name"]] if name != hit["name"] else []
        if plain and plain != name and counts[plain.lower()] == 1:
            aliases.append(plain)
        out.append(Entity(key=hit["id"], name=name, aliases=tuple(aliases)))
    return tuple(out)


async def launches_tasks(client: LaunchLibraryClient, *, now: datetime) -> list[Task]:
    until = now.date()
    since = until - timedelta(days=30)
    window = f"between {since.isoformat()} and {until.isoformat()} (UTC)"
    hits = await client.launches(since=since, until=until)
    tasks: list[Task] = []
    if GOLD_MIN <= len(hits) <= GOLD_MAX:
        tasks.append(
            Task(
                suite="launches",
                bucket="enumerate",
                prompt=(
                    f"Find ALL orbital rocket launch attempts worldwide {window}. "
                    "Be exhaustive - completeness is scored. Missions often have several "
                    "designations; list every one you saw. Respond with JSON only: "
                    '{"items": [{"name": "<mission or payload name>", "aliases": '
                    '["<other designations of the same mission>", ...]}, ...]}'
                ),
                entities=launch_entities(hits),
                provenance={"since": since.isoformat()},
            )
        )
    if len(hits) >= GOLD_MIN:
        tasks.append(
            Task(
                suite="launches",
                bucket="stat",
                prompt=(
                    f"How many orbital rocket launch attempts took place worldwide {window}? "
                    'Respond with JSON only: {"value": <integer>}'
                ),
                stat_value=float(len(hits)),
                stat_rel_tol=0.2,
                provenance={"since": since.isoformat()},
            )
        )
        falcon = sum(1 for h in hits if h["name"].lower().startswith("falcon 9"))
        tasks.append(
            Task(
                suite="launches",
                bucket="stat",
                prompt=(
                    f"Consider ALL orbital rocket launch attempts worldwide {window}. "
                    "What fraction of them were SpaceX Falcon 9 launches? "
                    'Respond with JSON only: {"value": <number between 0 and 1>}'
                ),
                stat_value=falcon / len(hits),
                stat_rel_tol=0.25,
                provenance={"since": since.isoformat(), "falcon": falcon},
            )
        )
    return tasks


async def fedreg_tasks(client: FedRegClient, *, now: datetime) -> list[Task]:
    end = now.date()
    eo_start = end - timedelta(days=45)
    eos = await client.executive_orders(start=eo_start, end=end)
    tasks: list[Task] = []
    if GOLD_MIN <= len(eos) <= GOLD_MAX:
        window = f"between {eo_start.isoformat()} and {end.isoformat()}"
        tasks.append(
            Task(
                suite="fedreg",
                bucket="enumerate",
                prompt=(
                    f"Find ALL executive orders of the US President published in the "
                    f"Federal Register {window}. Be exhaustive - completeness is scored. "
                    'Respond with JSON only: {"items": [{"name": "<executive order '
                    'title>", "aliases": ["Executive Order <number>"]}, ...]}'
                ),
                entities=tuple(
                    Entity(
                        key=str(r["document_number"]),
                        name=str(r["title"]),
                        aliases=tuple(
                            f"Executive Order {n}" for n in (r.get("executive_order_number"),) if n
                        ),
                    )
                    for r in eos
                ),
                provenance={"start": eo_start.isoformat()},
            )
        )
    rule_start = end - timedelta(days=30)
    count = await client.rule_count(
        agency="environmental-protection-agency", start=rule_start, end=end
    )
    if count is not None and count >= 10:
        tasks.append(
            Task(
                suite="fedreg",
                bucket="stat",
                prompt=(
                    f"How many final rules did the Environmental Protection Agency "
                    f"publish in the Federal Register between {rule_start.isoformat()} "
                    f"and {end.isoformat()}? "
                    'Respond with JSON only: {"value": <integer>}'
                ),
                stat_value=float(count),
                stat_rel_tol=0.25,
                provenance={
                    "agency": "environmental-protection-agency",
                    "start": rule_start.isoformat(),
                },
            )
        )
    return tasks


async def wikidata_tasks(client: WikidataClient, *, now: datetime) -> list[Task]:
    until = now.date()
    since = until - timedelta(days=30)
    people = await client.deaths(since=since, until=until, min_links=min(SITELINK_LADDER))
    for min_links in SITELINK_LADDER:
        chosen = [p for p in people if p["links"] >= min_links]
        if GOLD_MIN <= len(chosen) <= GOLD_MAX:
            return [
                Task(
                    suite="wikidata",
                    bucket="enumerate",
                    prompt=(
                        f"Find ALL people who died between {since.isoformat()} and "
                        f"{until.isoformat()} (UTC) and have a Wikipedia article in at "
                        f"least {min_links} languages. Be exhaustive - completeness is "
                        'scored. Respond with JSON only: {"items": [{"name": "<person '
                        'name>"}, ...]}'
                    ),
                    entities=tuple(Entity(key=p["qid"], name=p["name"]) for p in chosen),
                    provenance={"since": since.isoformat(), "min_links": min_links},
                )
            ]
    return []


async def github_tasks(client: GithubClient, *, now: datetime) -> list[Task]:
    until = now.date()
    since = until - timedelta(days=30)
    window = f"between {since.isoformat()} and {until.isoformat()}"
    tasks: list[Task] = []
    for min_stars in STAR_LADDER:
        total, items = await client.repos(since=since, until=until, min_stars=min_stars)
        if total is None:
            break
        if GOLD_MIN <= total <= GOLD_MAX and len(items) == total:
            tasks.append(
                Task(
                    suite="github",
                    bucket="enumerate",
                    prompt=(
                        f"Find ALL GitHub repositories created {window} that have "
                        f"reached at least {min_stars} stars. Be exhaustive - "
                        "completeness is scored. Respond with JSON only: "
                        '{"items": [{"name": "<owner/repo>"}, ...]}'
                    ),
                    entities=tuple(
                        Entity(key=r["full_name"], name=r["full_name"], aliases=(r["name"],))
                        for r in items
                    ),
                    provenance={"since": since.isoformat(), "min_stars": min_stars},
                )
            )
            break
        if total > GOLD_MAX:
            break
    total, _ = await client.repos(since=since, until=until, min_stars=300, per_page=1)
    if total is not None and total >= 50:
        tasks.append(
            Task(
                suite="github",
                bucket="stat",
                prompt=(
                    f"How many GitHub repositories created {window} have reached "
                    "at least 300 stars? "
                    'Respond with JSON only: {"value": <integer>}'
                ),
                stat_value=float(total),
                stat_rel_tol=0.25,
                provenance={"since": since.isoformat(), "min_stars": 300},
            )
        )
    return tasks


async def nvd_tasks(client: NvdClient, *, now: datetime) -> list[Task]:
    until = now.date()
    since = until - timedelta(days=30)
    total = await client.cve_count(since=since, until=until)
    if total is None or total < 500:
        return []
    return [
        Task(
            suite="nvd",
            bucket="stat",
            prompt=(
                f"How many CVEs (of any severity) were published between "
                f"{since.isoformat()} and {until.isoformat()}? "
                'Respond with JSON only: {"value": <integer>}'
            ),
            stat_value=float(total),
            stat_rel_tol=0.25,
            provenance={"since": since.isoformat()},
        )
    ]
