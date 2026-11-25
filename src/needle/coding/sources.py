import asyncio
import html
import math
import os
import random
import re
import zlib
from datetime import UTC, date, datetime
from typing import Any

from needle.coding.models import Doc
from needle.shared.htmltext import html_text
from needle.shared.sampling import dedupe_by, interleave
from needle.shared.search.base import USER_AGENT, HttpSearchClient

SPHINX_SITES = (
    ("python", "https://docs.python.org/3/", "library/"),
    ("numpy", "https://numpy.org/doc/stable/", "reference/"),
    ("pandas", "https://pandas.pydata.org/docs/", "reference/"),
)
MDN_BASE = "https://developer.mozilla.org"
MDN_INDEX = f"{MDN_BASE}/en-US/search-index.json"
MDN_API = "/en-US/docs/Web/API/"
MDN_JS = "/en-US/docs/Web/JavaScript/Reference/"
MDN_JS_SKIP = frozenset({"Errors", "Lexical_grammar"})
GITHUB_SEARCH = "https://api.github.com/search/issues"
STACKEXCHANGE_QUESTIONS = "https://api.stackexchange.com/2.3/questions"

MIN_DESC_WORDS = 8
MIN_ISSUE_COMMENTS = 2
MIN_QUESTION_SCORE = 1
TEXT_CHARS = 3000
PAGE_SIZE = 50

INV_LINE_RE = re.compile(r"^(\S+)\s+py:(?:function|method|class)\s+-?\d+\s+(\S+)")
HEADERLINK_RE = re.compile(r'<a class="headerlink".*?</a>', re.S)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
PARA_RE = re.compile(r"<p>(.*?)</p>", re.S)
MDN_SUFFIX_RE = re.compile(r"_(?:static|event)$")


def parse_inventory(raw: bytes, *, path_prefix: str) -> list[tuple[str, str]]:
    parts = raw.split(b"\n", 4)
    if len(parts) < 5:
        return []
    try:
        body = zlib.decompress(parts[4]).decode("utf-8")
    except (zlib.error, UnicodeDecodeError):
        return []
    entries = []
    for line in body.splitlines():
        m = INV_LINE_RE.match(line)
        if not m:
            continue
        symbol, uri = m.group(1), m.group(2).replace("$", m.group(1))
        if uri.startswith(path_prefix) and not any(p.startswith("_") for p in symbol.split(".")):
            entries.append((symbol, uri))
    return entries


def sphinx_entry(page: str, symbol: str) -> str | None:
    m = re.search(
        rf'<dt[^>]*\bid="{re.escape(symbol)}"[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>', page, re.S
    )
    if not m:
        return None
    signature = html_text(HEADERLINK_RE.sub("", m.group(1))).replace("[source]", "").strip()
    description = " ".join(html_text(p) for p in PARA_RE.findall(m.group(2))[:3])
    if len(description.split()) < MIN_DESC_WORDS:
        return None
    return f"{signature}\n{description}"


def mdn_names(path: str) -> tuple[str, ...] | None:
    if path.startswith(MDN_API):
        segments = path[len(MDN_API) :].split("/")
    elif path.startswith(MDN_JS):
        segments = path[len(MDN_JS) :].split("/")
        if len(segments) < 2 or segments[0] in MDN_JS_SKIP:
            return None
        segments = segments[1:]
    else:
        return None
    names = tuple(MDN_SUFFIX_RE.sub("", s) for s in segments if s)
    return names or None


def parse_issue(item: dict[str, Any], repo: str) -> Doc | None:
    if item.get("pull_request"):
        return None
    url = str(item.get("html_url") or "")
    title = " ".join(str(item.get("title") or "").split())
    body = HTML_COMMENT_RE.sub("", str(item.get("body") or "")).strip()[:TEXT_CHARS]
    if not url or not title or not body:
        return None
    return Doc("issue", url, title, body, context=repo, banned=(str(item.get("number") or ""),))


def parse_question(item: dict[str, Any], tag: str) -> Doc | None:
    if int(item.get("score") or 0) < MIN_QUESTION_SCORE or not item.get("answer_count"):
        return None
    url = str(item.get("link") or "")
    title = html.unescape(" ".join(str(item.get("title") or "").split()))
    body = html_text(str(item.get("body") or ""))[:TEXT_CHARS]
    if not url or not title or not body:
        return None
    return Doc("qa", url, title, body, context=tag, banned=(str(item.get("question_id") or ""),))


def _epoch(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


class SourceClient(HttpSearchClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.errors: list[str] = []

    def _note(self, source: str, message: str) -> None:
        self.errors.append(f"{source}: {message}"[:300])

    async def _fetch_json(self, source: str, url: str, **kwargs: Any) -> Any:
        payload, err = await self._request_json("GET", url, **kwargs)
        if err is not None:
            self._note(source, f"{err['error_type']}: {err['error_message']}")
        return payload


class ApiDocsClient(SourceClient):
    default_headers = {"User-Agent": USER_AGENT}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_concurrency", 4)
        super().__init__(**kwargs)

    async def docs(self, *, n: int, seed: int) -> list[Doc]:
        per_source = math.ceil(n / (len(SPHINX_SITES) + 1)) * 2
        lists = await asyncio.gather(
            *[self._sphinx(site, n=per_source, seed=seed) for site in SPHINX_SITES],
            self._mdn(n=per_source, seed=seed),
        )
        return interleave(list(lists))

    async def _sphinx(self, site: tuple[str, str, str], *, n: int, seed: int) -> list[Doc]:
        name, base, path_prefix = site
        resp, _, err = await self._send("GET", f"{base}objects.inv", follow_redirects=True)
        if resp is None:
            self._note(f"{name} objects.inv", str(err))
            return []
        if resp.status_code != 200:
            self._note(f"{name} objects.inv", f"http {resp.status_code}")
            return []
        entries = parse_inventory(resp.content, path_prefix=path_prefix)
        picked = random.Random(f"{seed}:{name}").sample(entries, min(n, len(entries)))
        picked = dedupe_by(picked, lambda e: e[1].split("#", 1)[0])
        docs = await asyncio.gather(*[self._sphinx_doc(name, base, *e) for e in picked])
        return [d for d in docs if d is not None]

    async def _sphinx_doc(self, name: str, base: str, symbol: str, uri: str) -> Doc | None:
        url = base + uri.split("#", 1)[0]
        page = await self._get_text(url)
        entry = sphinx_entry(page, symbol) if page else None
        if entry is None:
            return None
        banned = tuple(p for p in symbol.split(".") if p != name)
        return Doc("api", url, symbol, entry, context=name, banned=banned)

    async def _mdn(self, *, n: int, seed: int) -> list[Doc]:
        payload = await self._fetch_json("mdn index", MDN_INDEX)
        if not isinstance(payload, list):
            return []
        named = []
        for rec in payload:
            path = str(rec.get("url") or "") if isinstance(rec, dict) else ""
            names = mdn_names(path)
            if names is not None:
                named.append((path, names))
        picked = random.Random(f"{seed}:mdn").sample(named, min(n, len(named)))
        docs = await asyncio.gather(*[self._mdn_doc(*p) for p in picked])
        return [d for d in docs if d is not None]

    async def _mdn_doc(self, path: str, names: tuple[str, ...]) -> Doc | None:
        payload, err = await self._request_json("GET", f"{MDN_BASE}{path}/index.json")
        doc = payload.get("doc") if isinstance(payload, dict) else None
        if err is not None or not isinstance(doc, dict):
            return None
        summary = " ".join(str(doc.get("summary") or "").split())
        if len(summary.split()) < MIN_DESC_WORDS:
            return None
        title = str(doc.get("title") or path.rsplit("/", 1)[-1])
        return Doc("api", f"{MDN_BASE}{path}", title, summary, context="javascript", banned=names)


class GitHubClient(SourceClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(api_key=os.environ.get("GITHUB_TOKEN"), **kwargs)
        self.default_headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
        if self.api_key:
            self.default_headers["Authorization"] = f"Bearer {self.api_key}"
        self.min_interval_s = 2.1 if self.api_key else 6.1

    async def issues(self, repo: str, *, created_after: date, created_before: date) -> list[Doc]:
        query = (
            f"repo:{repo} is:issue comments:>{MIN_ISSUE_COMMENTS} "
            f"created:{created_after.isoformat()}..{created_before.isoformat()}"
        )
        payload = await self._fetch_json(
            f"github {repo}",
            GITHUB_SEARCH,
            params={"q": query, "sort": "comments", "order": "desc", "per_page": PAGE_SIZE},
        )
        if not isinstance(payload, dict):
            return []
        docs = [parse_issue(item, repo) for item in payload.get("items") or []]
        return [d for d in docs if d is not None]


class StackExchangeClient(SourceClient):
    default_headers = {"User-Agent": USER_AGENT}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(api_key=os.environ.get("STACKEXCHANGE_KEY"), **kwargs)

    async def questions(self, tag: str, *, created_after: date, created_before: date) -> list[Doc]:
        params: dict[str, Any] = {
            "site": "stackoverflow",
            "tagged": tag,
            "sort": "votes",
            "order": "desc",
            "fromdate": _epoch(created_after),
            "todate": _epoch(created_before),
            "pagesize": PAGE_SIZE,
            "filter": "withbody",
        }
        if self.api_key:
            params["key"] = self.api_key
        payload = await self._fetch_json(
            f"stackexchange {tag}",
            STACKEXCHANGE_QUESTIONS,
            params=params,
            error_field="error_message",
        )
        if not isinstance(payload, dict):
            return []
        docs = [parse_question(item, tag) for item in payload.get("items") or []]
        return [d for d in docs if d is not None]
