import re
from datetime import date, datetime, timedelta
from typing import Any

from keenbench.findallmcp.models import Entity, Task
from keenbench.shared.search.base import HttpSearchClient

USER_AGENT = "keenbench/0.1 (contact@keenable.ai)"

HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index"
FEDREG_DOCS = "https://www.federalregister.gov/api/v1/documents.json"
GITHUB_SEARCH = "https://api.github.com/search/repositories"
CPSC_RECALLS = "https://www.saferproducts.gov/RestWebServices/Recall"
USASPENDING_SEARCH = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
USASPENDING_COUNT = "https://api.usaspending.gov/api/v2/search/spending_by_award_count/"

HN_POINT_LADDER = (500, 400, 300, 250, 200, 150)
STAR_LADDER = (5000, 3000, 2000, 1000, 500)
CPSC_DAY_LADDER = (30, 21, 14, 10, 7)
AWARD_AMOUNT_LADDER = (
    2_000_000_000,
    1_500_000_000,
    1_000_000_000,
    750_000_000,
    500_000_000,
    400_000_000,
    300_000_000,
    250_000_000,
    200_000_000,
    150_000_000,
)
CONTRACT_TYPE_CODES = ("A", "B", "C", "D")
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


def amount_label(amount: int) -> str:
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:g} billion"
    return f"${amount / 1_000_000:g} million"


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


class CpscClient(HttpSearchClient):
    async def recalls(self, *, since: date, until: date) -> list[dict[str, Any]]:
        params = {
            "RecallDateStart": since.isoformat(),
            "RecallDateEnd": until.isoformat(),
            "format": "json",
        }
        payload, err = await self._request_json(
            "GET", CPSC_RECALLS, params=params, headers={"User-Agent": USER_AGENT}
        )
        if err is not None or not isinstance(payload, list):
            return []
        out = []
        for r in payload:
            number = str(r.get("RecallNumber") or "")
            title = " ".join(str(r.get("Title") or "").split())
            day = str(r.get("RecallDate") or "")[:10]
            if not number or not title or not day:
                continue
            products = [
                " ".join(str(p.get("Name") or "").split())
                for p in r.get("Products") or []
                if p.get("Name")
            ]
            out.append({"number": number, "title": title, "date": day, "products": products})
        return out


class UsaspendingClient(HttpSearchClient):
    def _filters(self, since: date, until: date, min_amount: int) -> dict[str, Any]:
        return {
            "time_period": [
                {
                    "start_date": since.isoformat(),
                    "end_date": until.isoformat(),
                    "date_type": "date_signed",
                }
            ],
            "award_type_codes": list(CONTRACT_TYPE_CODES),
            "award_amounts": [{"lower_bound": min_amount}],
        }

    async def awards(
        self, *, since: date, until: date, min_amount: int, limit: int = 100
    ) -> list[dict[str, Any]] | None:
        body = {
            "filters": self._filters(since, until, min_amount),
            "fields": ["Award ID", "Recipient Name", "Award Amount"],
            "limit": limit,
            "order": "desc",
            "sort": "Award Amount",
        }
        payload, err = await self._request_json(
            "POST", USASPENDING_SEARCH, json=body, headers={"User-Agent": USER_AGENT}
        )
        if err is not None or not isinstance(payload, dict):
            return None
        out = []
        for r in payload.get("results") or []:
            name = " ".join(str(r.get("Recipient Name") or "").split())
            if name:
                out.append({"id": str(r.get("Award ID") or ""), "name": name})
        return out

    async def award_count(self, *, since: date, until: date, min_amount: int) -> int | None:
        body = {"filters": self._filters(since, until, min_amount)}
        payload, err = await self._request_json(
            "POST", USASPENDING_COUNT, json=body, headers={"User-Agent": USER_AGENT}
        )
        if err is not None or not isinstance(payload, dict):
            return None
        count = (payload.get("results") or {}).get("contracts")
        return int(count) if isinstance(count, int) else None


class FedRegClient(HttpSearchClient):
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


def cpsc_entity(recall: dict[str, Any]) -> Entity:
    products = recall["products"]
    name = products[0] if products else recall["title"]
    aliases = [a for a in [recall["title"], *products[1:]] if a and a != name]
    return Entity(key=recall["number"], name=name, aliases=tuple(dict.fromkeys(aliases)))


async def cpsc_tasks(client: CpscClient, *, now: datetime) -> list[Task]:
    until = now.date()
    since = until - timedelta(days=max(CPSC_DAY_LADDER))
    recalls = await client.recalls(since=since, until=until)
    tasks: list[Task] = []
    for days in CPSC_DAY_LADDER:
        w_since = until - timedelta(days=days)
        chosen = [r for r in recalls if r["date"] >= w_since.isoformat()]
        if len(chosen) < GOLD_MIN:
            break
        if len(chosen) > GOLD_MAX:
            continue
        window = f"between {w_since.isoformat()} and {until.isoformat()}"
        tasks.append(
            Task(
                suite="cpsc",
                bucket="enumerate",
                prompt=(
                    f"Find ALL consumer product recalls announced by the US Consumer "
                    f"Product Safety Commission (CPSC) {window}. Be exhaustive - "
                    "completeness is scored. Respond with JSON only: "
                    '{"items": [{"name": "<recalled product>", "aliases": '
                    '["<recalling company or full recall title>"]}, ...]}'
                ),
                entities=tuple(cpsc_entity(r) for r in chosen),
                provenance={"since": w_since.isoformat()},
            )
        )
        break
    if len(recalls) >= 15:
        window = f"between {since.isoformat()} and {until.isoformat()}"
        tasks.append(
            Task(
                suite="cpsc",
                bucket="stat",
                prompt=(
                    f"How many consumer product recalls did the US Consumer Product "
                    f"Safety Commission (CPSC) announce {window}? "
                    'Respond with JSON only: {"value": <integer>}'
                ),
                stat_value=float(len(recalls)),
                stat_rel_tol=0.2,
                provenance={"since": since.isoformat()},
            )
        )
    return tasks


async def awards_tasks(client: UsaspendingClient, *, now: datetime) -> list[Task]:
    until = now.date()
    since = until - timedelta(days=30)
    window = f"between {since.isoformat()} and {until.isoformat()}"
    tasks: list[Task] = []
    for min_amount in AWARD_AMOUNT_LADDER:
        rows = await client.awards(since=since, until=until, min_amount=min_amount)
        if rows is None:
            break
        recipients: dict[str, dict[str, Any]] = {}
        for r in rows:
            recipients.setdefault(r["name"].lower(), r)
        if len(recipients) > GOLD_MAX:
            break
        if len(recipients) < GOLD_MIN:
            continue
        label = amount_label(min_amount)
        tasks.append(
            Task(
                suite="awards",
                bucket="enumerate",
                prompt=(
                    f"Find ALL companies that were awarded a US federal contract worth "
                    f"at least {label} (total contract value) signed {window}. "
                    "Be exhaustive - completeness is scored. Respond with JSON only: "
                    '{"items": [{"name": "<company name>"}, ...]}'
                ),
                entities=tuple(
                    Entity(key=r["id"] or r["name"], name=r["name"])
                    for r in recipients.values()
                ),
                provenance={"since": since.isoformat(), "min_amount": min_amount},
            )
        )
        break
    count = await client.award_count(since=since, until=until, min_amount=100_000_000)
    if count is not None and count >= 10:
        tasks.append(
            Task(
                suite="awards",
                bucket="stat",
                prompt=(
                    f"How many US federal contracts worth at least $100 million "
                    f"(total contract value) were signed {window}? "
                    'Respond with JSON only: {"value": <integer>}'
                ),
                stat_value=float(count),
                stat_rel_tol=0.25,
                provenance={"since": since.isoformat(), "min_amount": 100_000_000},
            )
        )
    return tasks


async def fedreg_tasks(client: FedRegClient, *, now: datetime) -> list[Task]:
    end = now.date()
    tasks: list[Task] = []
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
