import re
from datetime import date, datetime, timedelta
from typing import Any

from keenbench.findallmcp.models import Entity, Task
from keenbench.shared.search.base import HttpSearchClient

USER_AGENT = "keenbench/0.1 (contact@keenable.ai)"

HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index"

HN_POINT_LADDER = (500, 400, 300, 250, 200, 150)
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
