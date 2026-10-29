import re
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlsplit

from needle.coding.models import DocHost, DocPage
from needle.shared.search.base import USER_AGENT, HttpSearchClient

HOSTS: dict[str, DocHost] = {
    "firecrawl": DocHost("firecrawl", "Firecrawl", "https://docs.firecrawl.dev/llms.txt"),
    "browserbase": DocHost("browserbase", "Browserbase", "https://docs.browserbase.com/llms.txt"),
    "resend": DocHost("resend", "Resend", "https://resend.com/docs/llms.txt"),
    "langchain": DocHost("langchain", "LangChain", "https://docs.langchain.com/llms.txt"),
}

LINK_RE = re.compile(r"^\s*-\s+\[([^\]]+)\]\(([^)\s]+)\)(?:\s*:\s*(.*))?$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
GENERIC_TITLES = frozenset(
    {"overview", "introduction", "index", "welcome", "getting started", "get started", "home"}
)
GENERIC_HEADINGS = GENERIC_TITLES | {"documentation", "docs", "guide", "guides", "more"}
LOCALES = frozenset(
    {
        "en",
        "es",
        "fr",
        "ja",
        "zh",
        "zh-cn",
        "zh-tw",
        "de",
        "ko",
        "pt",
        "pt-br",
        "it",
        "nl",
        "ru",
        "pl",
        "tr",
        "vi",
        "ar",
        "hi",
        "sv",
        "da",
        "fi",
        "no",
        "cs",
        "uk",
        "th",
    }
)
MIN_TITLE_CHARS = 2
VERSION_HEADING_RE = re.compile(r"v\d+(\s*\(.*\))?$")


def page_key(raw: str) -> str | None:
    text = raw.strip().strip(".,);]>'\"}")
    if not text:
        return None
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    host = parts.netloc.lower().removeprefix("www.")
    if not host or "." not in host or " " in host:
        return None
    path = parts.path
    if path.lower().endswith(".md"):
        path = path[:-3]
    path = path.rstrip("/")
    if not path.startswith("/") or path == "/":
        return None
    return f"{host}{path}"


def path_locale(path: str) -> str | None:
    parts = [part for part in path.lower().split("/") if part]
    if not parts:
        return None
    cand = parts[1] if parts[0] == "_llms" and len(parts) > 1 else parts[0]
    cand = cand.removesuffix(".txt").removesuffix(".md")
    return cand if cand in LOCALES else None


def non_english_path(path: str) -> bool:
    return path_locale(path) not in (None, "en")


def english_indexes(urls: list[str]) -> list[str]:
    locales = [path_locale(urlsplit(url).path) for url in urls]
    if any(locale == "en" for locale in locales):
        return [url for url, locale in zip(urls, locales, strict=True) if locale in (None, "en")]
    if any(locale is None for locale in locales):
        return [url for url, locale in zip(urls, locales, strict=True) if locale is None]
    return urls


ACRONYMS = frozenset({"api", "sdk", "url", "dns", "oauth", "json", "cli", "mcp"})


def path_section(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    labels: list[str] = []
    for part in parts[:-1]:
        folded = part.replace("-", " ").lower()
        if folded in GENERIC_HEADINGS or part.lower() in LOCALES:
            continue
        words = [
            word.upper() if word.lower() in ACRONYMS else word.capitalize()
            for word in part.split("-")
            if word
        ]
        if words:
            labels.append(" ".join(words))
    return " ".join(labels[-2:])


def _nearest_section(stack: list[tuple[int, str]]) -> str:
    for level, label in reversed(stack):
        if level == 1:
            continue
        folded = label.lower()
        if folded in GENERIC_HEADINGS or VERSION_HEADING_RE.fullmatch(folded):
            continue
        return label
    return ""


def page_body(markdown: str) -> str:
    lines = markdown.splitlines()
    index = 0
    while index < len(lines) and (
        not lines[index].strip() or lines[index].lstrip().startswith(">")
    ):
        index += 1
    if index < len(lines) and lines[index].startswith("# "):
        index += 1
    return "\n".join(lines[index:]).strip()


def _classify(url: str, host: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    if parts.netloc.lower().removeprefix("www.") != host:
        return None
    path = parts.path.lower()
    if "/_llms/" in path and path.endswith(".txt"):
        return "index"
    if path.endswith(".md"):
        return "page"
    return None


def parse_llms(text: str, *, product: str, base_url: str) -> tuple[list[DocPage], list[str]]:
    origin = urlsplit(base_url)
    host = origin.netloc.lower().removeprefix("www.")
    pages: list[DocPage] = []
    indexes: list[str] = []
    seen: set[str] = set()
    headings: list[tuple[int, str]] = []
    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading is not None:
            level = len(heading.group(1))
            label = " ".join(unescape(heading.group(2)).split())
            headings = [(lv, name) for lv, name in headings if lv < level]
            headings.append((level, label))
            continue
        match = LINK_RE.match(line)
        if match is None:
            continue
        title = " ".join(unescape(match.group(1)).split())
        absolute = urljoin(base_url, match.group(2))
        kind = _classify(absolute, host)
        if kind == "index":
            key = absolute.split("#", 1)[0]
            if key not in seen:
                seen.add(key)
                indexes.append(key)
            continue
        if kind != "page" or len(title) < MIN_TITLE_CHARS:
            continue
        if title.lower() in GENERIC_TITLES:
            continue
        key = page_key(absolute)
        if key is None or key in seen:
            continue
        page_host, _, rest = key.partition("/")
        path = "/" + rest
        if non_english_path(path):
            continue
        seen.add(key)
        description = " ".join((match.group(3) or "").split())
        pages.append(
            DocPage(
                product=product,
                title=title,
                description=description,
                host=page_host,
                path=path,
                section=_nearest_section(headings),
            )
        )
    return pages, indexes


class MintlifyClient(HttpSearchClient):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_concurrency", 4)
        super().__init__(**kwargs)
        self.default_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/markdown, text/plain;q=0.9, */*;q=0.1",
        }

    async def fetch_text(self, url: str) -> str | None:
        return await self._get_text(url)
