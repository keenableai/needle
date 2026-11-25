import asyncio
import html
import math
import os
import random
import re
import zlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from needle.coding.models import Doc
from needle.shared.htmltext import html_text
from needle.shared.sampling import dedupe_by, interleave
from needle.shared.search.base import USER_AGENT, HttpSearchClient

TOP_PYPI = "https://hugovk.github.io/top-pypi-packages/top-pypi-packages.min.json"
PYPI_JSON = "https://pypi.org/pypi/{}/json"
PYPI_RANKS = (2000, 15000)
PYPI_TRIES = 5
CRATES_LIST = "https://crates.io/api/v1/crates"
CRATES_PAGES = (20, 200)
CRATES_PAGE_SIZE = 100
DOCSRS = "https://docs.rs"
SYMBOLS_PER_SITE = 3
GITHUB_SEARCH = "https://api.github.com/search/issues"
GITHUB_REPO_SEARCH = "https://api.github.com/search/repositories"
REPO_STARS = (100, 2000)
REPO_LANGUAGES = (
    "python",
    "rust",
    "go",
    "typescript",
    "javascript",
    "java",
    "cpp",
    "csharp",
    "ruby",
    "php",
    "kotlin",
    "swift",
)
LANGUAGES_PER_RUN = 6
REPO_PAGES = 10
REPO_PUSHED_DAYS = 90
MIN_OPEN_ISSUES = 10
STACKEXCHANGE_QUESTIONS = "https://api.stackexchange.com/2.3/questions"
MINTLIFY_HOSTS = Path(__file__).parent / "data" / "mintlify_hosts.csv"
MINTLIFY_MIN_RANK = 5_000_000
MINTLIFY_TRIES = 3
MIN_LLMS_LINKS = 10
CHANGELOG_FEEDS = (
    ("Cloudflare", "https://developers.cloudflare.com/changelog/rss/index.xml"),
    ("Vercel", "https://vercel.com/atom"),
    ("GitHub", "https://github.blog/changelog/feed/"),
    ("Supabase", "https://supabase.com/changelog-rss.xml"),
    ("Bedrock", "https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-ug.rss"),
)
FRESH_DAYS = 14

MIN_DESC_WORDS = 8
MIN_PAGE_WORDS = 30
MIN_ISSUE_COMMENTS = 2
MIN_QUESTION_SCORE = 1
TEXT_CHARS = 3000
PAGE_SIZE = 50

INV_LINE_RE = re.compile(r"^(\S+)\s+py:(?:function|method|class)\s+-?\d+\s+(\S+)")
HEADERLINK_RE = re.compile(r'<a class="headerlink".*?</a>', re.S)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
PARA_RE = re.compile(r"<p>(.*?)</p>", re.S)
DOCS_URL_KEY_RE = re.compile(r"doc", re.I)
RTD_SLUG_RE = re.compile(r"[._]")
DOCSRS_ITEM_RE = re.compile(
    r'<li><a href="((?:\w+/)*(?:struct|enum|fn|trait|macro|type|constant|union)\.\w+\.html)">'
)
DOCSRS_DECL_RE = re.compile(r'<pre class="rust item-decl"><code>(.*?)</code></pre>', re.S)
DOCSRS_TOP_DOC_RE = re.compile(
    r'<details class="toggle top-doc"[^>]*>.*?<div class="docblock">(.*?)</div></details>', re.S
)
LLMS_TITLE_RE = re.compile(r"^#\s+(.+)$", re.M)
LLMS_LINK_RE = re.compile(r"^\s*[-*]\s*\[([^\]]+)\]\((https?://[^)\s]+)\)", re.M)
SITE_NAME_SUFFIX_RE = re.compile(
    r"\s*[-|:–]?\s*\b(?:docs|documentation|developer docs|developers?|api reference|api docs|"
    r"help center|guides?|knowledge base)\b.*$",
    re.I,
)
STARTER_KIT_RE = re.compile(r"starter kit", re.I)
HOST_PREFIXES = frozenset({"docs", "doc", "developers", "developer", "dev", "api", "www", "help"})
FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.S)
MAIN_HTML_RE = re.compile(r"<(main|article)\b[^>]*>(.*?)</\1>", re.S | re.I)
ATOM = "{http://www.w3.org/2005/Atom}"
RSS_CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


@dataclass(frozen=True)
class FeedEntry:
    title: str
    url: str
    published: datetime | None
    text: str


def parse_inventory(raw: bytes) -> list[tuple[str, str]]:
    parts = raw.split(b"\n", 4)
    if len(parts) < 5 or not parts[0].startswith(b"# Sphinx inventory"):
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
        names = symbol.split(".")
        if len(names) >= 2 and not any(n.startswith("_") for n in names):
            entries.append((symbol, uri))
    return entries


def sphinx_entry(page: str, symbol: str) -> str | None:
    m = re.search(
        rf'<dt[^>]*\bid="{re.escape(symbol)}"[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>', page, re.S
    )
    if not m:
        return None
    signature = html_text(HEADERLINK_RE.sub("", m.group(1))).replace("[source]", "").strip()
    return _with_description(signature, m.group(2))


def docsrs_entry(page: str) -> str | None:
    decl, doc = DOCSRS_DECL_RE.search(page), DOCSRS_TOP_DOC_RE.search(page)
    if not decl or not doc:
        return None
    return _with_description(html_text(decl.group(1)).strip(), doc.group(1))


def _with_description(signature: str, body: str) -> str | None:
    description = " ".join(html_text(p) for p in PARA_RE.findall(body)[:3])
    if len(description.split()) < MIN_DESC_WORDS:
        return None
    return f"{signature}\n{description}"


def docs_bases(info: dict[str, Any], package: str) -> list[str]:
    urls = info.get("project_urls") or {}
    bases = [
        url
        for label, url in urls.items()
        if DOCS_URL_KEY_RE.search(label) and str(url).startswith("http")
    ]
    bases.append(f"https://{RTD_SLUG_RE.sub('-', package.lower())}.readthedocs.io/en/latest/")
    return dedupe_by([str(b).rstrip("/") + "/" for b in bases], lambda b: b)


def docsrs_items(page: str) -> list[str]:
    return dedupe_by(DOCSRS_ITEM_RE.findall(page), lambda href: href)


def load_mintlify_hosts(
    path: Path = MINTLIFY_HOSTS, *, min_rank: int = MINTLIFY_MIN_RANK
) -> list[str]:
    hosts = []
    for line in path.read_text().splitlines():
        host, _, rank = line.partition(",")
        if host and rank.isdigit() and int(rank) >= min_rank:
            hosts.append(host)
    return hosts


def host_label(host: str) -> str:
    labels = host.split(".")
    while len(labels) > 2 and labels[0] in HOST_PREFIXES:
        labels = labels[1:]
    return labels[0]


def parse_llms_txt(text: str, host: str) -> tuple[str, list[tuple[str, str]]] | None:
    title = LLMS_TITLE_RE.search(text[:500])
    if not text.lstrip().startswith("# ") or not title or STARTER_KIT_RE.search(title.group(1)):
        return None
    links = [
        (label.strip(), url)
        for label, url in LLMS_LINK_RE.findall(text)
        if urlsplit(url).hostname == host and urlsplit(url).path.strip("/")
    ]
    if len(links) < MIN_LLMS_LINKS:
        return None
    name = SITE_NAME_SUFFIX_RE.sub("", title.group(1)).strip(" #-|:")
    return name or host_label(host), dedupe_by(links, lambda link: link[1])


def markdown_page(text: str) -> str | None:
    if text.lstrip().startswith("<"):
        return None
    body = FRONTMATTER_RE.sub("", text.lstrip()).strip()
    return body[:TEXT_CHARS] if len(body.split()) >= MIN_PAGE_WORDS else None


def _feed_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = (
            datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if value.strip()[:4].isdigit()
            else parsedate_to_datetime(value)
        )
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_feed(raw: bytes) -> list[FeedEntry]:
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return []
    entries = []
    for item in root.iter("item"):
        entries.append(
            FeedEntry(
                " ".join((item.findtext("title") or "").split()),
                (item.findtext("link") or "").strip(),
                _feed_date(item.findtext("pubDate")),
                html_text(item.findtext(RSS_CONTENT) or item.findtext("description") or ""),
            )
        )
    for item in root.iter(f"{ATOM}entry"):
        link = item.find(f"{ATOM}link[@rel='alternate']")
        if link is None:
            link = item.find(f"{ATOM}link")
        entries.append(
            FeedEntry(
                " ".join((item.findtext(f"{ATOM}title") or "").split()),
                (link.get("href") or "").strip() if link is not None else "",
                _feed_date(item.findtext(f"{ATOM}published") or item.findtext(f"{ATOM}updated")),
                html_text(item.findtext(f"{ATOM}content") or item.findtext(f"{ATOM}summary") or ""),
            )
        )
    return [e for e in entries if e.title and e.url.startswith("http")]


def page_main_text(page: str) -> str:
    main = MAIN_HTML_RE.search(page)
    return html_text(main.group(2) if main else page)


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


def small_repo_names(payload: Any) -> list[str]:
    items = payload.get("items") if isinstance(payload, dict) else None
    return [
        str(item["full_name"])
        for item in items or []
        if item.get("has_issues") and int(item.get("open_issues_count") or 0) >= MIN_OPEN_ISSUES
    ]


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
        per_source = math.ceil(n / 2)
        lists = await asyncio.gather(
            self._sphinx_sites(n=per_source, seed=seed),
            self._docsrs_crates(n=per_source, seed=seed),
        )
        return interleave(list(lists))

    async def _sphinx_sites(self, *, n: int, seed: int) -> list[Doc]:
        payload = await self._fetch_json("top pypi", TOP_PYPI, follow_redirects=True)
        rows = payload.get("rows") if isinstance(payload, dict) else None
        names = [str(r["project"]) for r in (rows or [])[PYPI_RANKS[0] : PYPI_RANKS[1]]]
        picked = random.Random(f"{seed}:pypi").sample(names, min(n * PYPI_TRIES, len(names)))
        docs = await asyncio.gather(*[self._sphinx_doc(name, seed) for name in picked])
        return [d for d in docs if d is not None][:n]

    async def _sphinx_doc(self, package: str, seed: int) -> Doc | None:
        meta, _ = await self._request_json("GET", PYPI_JSON.format(package), follow_redirects=True)
        info = meta.get("info") if isinstance(meta, dict) else None
        for base in docs_bases(info or {}, package):
            resp, _, _ = await self._send("GET", f"{base}objects.inv", follow_redirects=True)
            entries = parse_inventory(resp.content) if resp and resp.status_code == 200 else []
            if not entries:
                continue
            site = str(resp.url).removesuffix("objects.inv") if resp else base
            rng = random.Random(f"{seed}:{package}")
            for symbol, uri in rng.sample(entries, min(SYMBOLS_PER_SITE, len(entries))):
                url = site + uri.split("#", 1)[0]
                page = await self._get_text(url)
                entry = sphinx_entry(page, symbol) if page else None
                if entry is not None:
                    library, *rest = symbol.split(".")
                    return Doc("api", url, symbol, entry, context=library, banned=tuple(rest))
            return None
        return None

    async def _docsrs_crates(self, *, n: int, seed: int) -> list[Doc]:
        rng = random.Random(f"{seed}:crates")
        pages = rng.sample(range(*CRATES_PAGES), math.ceil(n * 2 / CRATES_PAGE_SIZE))
        crates: list[str] = []
        for page in pages:
            payload = await self._fetch_json(
                f"crates.io page {page}",
                CRATES_LIST,
                params={"page": page, "per_page": CRATES_PAGE_SIZE, "sort": "downloads"},
            )
            listed = payload.get("crates") if isinstance(payload, dict) else None
            crates += [str(c["name"]) for c in listed or []]
        picked = rng.sample(crates, min(n * 2, len(crates)))
        docs = await asyncio.gather(*[self._docsrs_doc(name, seed) for name in picked])
        return [d for d in docs if d is not None][:n]

    async def _docsrs_doc(self, crate: str, seed: int) -> Doc | None:
        root = f"{DOCSRS}/{crate}/latest/{crate.replace('-', '_')}/"
        index = await self._get_text(f"{root}all.html")
        items = docsrs_items(index) if index else []
        rng = random.Random(f"{seed}:{crate}")
        for href in rng.sample(items, min(SYMBOLS_PER_SITE, len(items))):
            page = await self._get_text(root + href)
            entry = docsrs_entry(page) if page else None
            if entry is not None:
                *modules, item = href.removesuffix(".html").split("/")
                name = item.split(".", 1)[1]
                title = "::".join([crate.replace("-", "_"), *modules, name])
                return Doc("api", root + href, title, entry, context=crate, banned=(*modules, name))
        return None


class GitHubClient(SourceClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(api_key=os.environ.get("GITHUB_TOKEN"), **kwargs)
        self.default_headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
        if self.api_key:
            self.default_headers["Authorization"] = f"Bearer {self.api_key}"
        self.min_interval_s = 2.1 if self.api_key else 6.1

    async def small_repos(self, *, now: datetime, seed: int, n: int) -> list[str]:
        rng = random.Random(f"{seed}:repos")
        pushed = (now - timedelta(days=REPO_PUSHED_DAYS)).date().isoformat()
        searches = [
            (
                lang,
                f"stars:{REPO_STARS[0]}..{REPO_STARS[1]} pushed:>{pushed} "
                f"fork:false archived:false language:{lang}",
                rng.randint(1, REPO_PAGES),
            )
            for lang in rng.sample(REPO_LANGUAGES, LANGUAGES_PER_RUN)
        ]
        payloads = await asyncio.gather(
            *[
                self._fetch_json(
                    f"github repos {lang}",
                    GITHUB_REPO_SEARCH,
                    params={"q": query, "sort": "updated", "per_page": 100, "page": page},
                )
                for lang, query, page in searches
            ]
        )
        lists = [small_repo_names(p) for p in payloads]
        for names in lists:
            rng.shuffle(names)
        return interleave(lists)[:n]

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


class MintlifyClient(SourceClient):
    default_headers = {"User-Agent": USER_AGENT}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_concurrency", 6)
        super().__init__(**kwargs)

    async def docs(self, *, n: int, seed: int) -> list[Doc]:
        hosts = load_mintlify_hosts()
        rng = random.Random(f"{seed}:mintlify")
        picked = rng.sample(hosts, min(n * MINTLIFY_TRIES, len(hosts)))
        docs = await asyncio.gather(*[self._site_doc(host, seed) for host in picked])
        return dedupe_by([d for d in docs if d is not None], lambda d: d.context.lower())[:n]

    async def _site_doc(self, host: str, seed: int) -> Doc | None:
        for base in (f"https://{host}", f"https://{host}/docs"):
            resp, _, _ = await self._send("GET", f"{base}/llms.txt", follow_redirects=True)
            if resp is None or resp.status_code != 200:
                continue
            site = parse_llms_txt(resp.text, resp.url.host)
            if site is None:
                return None
            name, links = site
            rng = random.Random(f"{seed}:{host}")
            for label, url in rng.sample(links, min(SYMBOLS_PER_SITE, len(links))):
                page_url = url.removesuffix(".md").rstrip("/")
                text = await self._get_text(f"{page_url}.md")
                body = markdown_page(text) if text else None
                if body is not None:
                    return Doc("mintlify", page_url, label, body, context=name)
            return None
        return None


class ChangelogClient(SourceClient):
    default_headers = {"User-Agent": USER_AGENT}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_concurrency", 4)
        super().__init__(**kwargs)

    async def docs(self, *, n: int, seed: int, now: datetime) -> list[Doc]:
        cutoff = now - timedelta(days=FRESH_DAYS)
        lists = await asyncio.gather(
            *[self._feed(name, url, cutoff=cutoff, seed=seed) for name, url in CHANGELOG_FEEDS]
        )
        picked = interleave(list(lists))[:n]
        docs = await asyncio.gather(*[self._entry_doc(name, entry) for name, entry in picked])
        return [d for d in docs if d is not None]

    async def _feed(
        self, name: str, url: str, *, cutoff: datetime, seed: int
    ) -> list[tuple[str, FeedEntry]]:
        resp, _, err = await self._send("GET", url, follow_redirects=True)
        if resp is None or resp.status_code != 200:
            self._note(f"feed {name}", str(err) if resp is None else f"http {resp.status_code}")
            return []
        recent = [e for e in parse_feed(resp.content) if e.published and e.published >= cutoff]
        recent = dedupe_by(recent, lambda e: e.url.split("#", 1)[0])
        random.Random(f"{seed}:{name}").shuffle(recent)
        return [(name, e) for e in recent]

    async def _entry_doc(self, name: str, entry: FeedEntry) -> Doc | None:
        url = entry.url.split("#", 1)[0]
        text = entry.text
        if len(text.split()) < MIN_PAGE_WORDS:
            page = await self._get_text(url)
            text = f"{text}\n{page_main_text(page)}".strip() if page else text
        if len(text.split()) < MIN_PAGE_WORDS:
            return None
        return Doc("fresh", url, entry.title, text[:TEXT_CHARS], context=name)
