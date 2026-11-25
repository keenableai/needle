import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from needle.shared.identity import query_hash, query_id

CODING_SOURCE = "coding"
DOC_TYPES = ("api", "issue", "qa")

DOC_KEY_RULES = (
    ("github.com", "gh", re.compile(r"^([\w.-]+/[\w.-]+)/(?:issues|pull)/(\d+)(?:/|$)")),
    ("stackoverflow.com", "so", re.compile(r"^(?:questions|q)/(\d+)(?:/|$)")),
)
VERSION_SEGMENT_RE = re.compile(
    r"^(?:latest|stable|dev|devel|main|master|current|release|v?\d+(?:\.\d+)*[a-z0-9.+-]*)$"
)
LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2})?$")
VERSION_SUFFIX_RE = re.compile(r"(?<=[a-z])[-_]v?\d+(?:\.\d+)*$")
PAGE_SUFFIX_RE = re.compile(r"\.(?:html?|md)$")
RUSTDOC_ITEM_RE = re.compile(
    r"^(?:struct|enum|fn|trait|macro|type|constant|union|static|attr|derive)\.[a-z0-9_]+\.html$"
)
RUST_MODULE_RE = re.compile(r"^[a-z0-9_]+$")


def _page_path(segments: list[str]) -> str:
    if segments and PAGE_SUFFIX_RE.sub("", segments[-1]) == "index":
        segments = segments[:-1]
    if segments:
        segments = [*segments[:-1], PAGE_SUFFIX_RE.sub("", segments[-1])]
    kept = []
    for i, segment in enumerate(segments[:-1]):
        following = segments[i + 1]
        if VERSION_SEGMENT_RE.match(segment):
            continue
        if LOCALE_SEGMENT_RE.match(segment) and VERSION_SEGMENT_RE.match(following):
            continue
        kept.append(VERSION_SUFFIX_RE.sub("", segment))
    return "/".join(kept + segments[-1:])


def _rustdoc_path(segments: list[str]) -> str | None:
    if not segments or not RUSTDOC_ITEM_RE.match(segments[-1]):
        return None
    start = len(segments) - 1
    while (
        start > 0
        and RUST_MODULE_RE.match(segments[start - 1])
        and not VERSION_SEGMENT_RE.match(segments[start - 1])
    ):
        start -= 1
    if start == len(segments) - 1:
        return None
    return "/".join([*segments[start:-1], segments[-1].removesuffix(".html")])


def doc_key(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").removeprefix("www.")
    if not host:
        return None
    segments = [s for s in parts.path.lower().split("/") if s]
    path = "/".join(segments)
    for rule_host, prefix, pattern in DOC_KEY_RULES:
        if host == rule_host and (m := pattern.match(path)):
            return f"{prefix}:{'#'.join(m.groups())}"
    if rustdoc := _rustdoc_path(segments):
        return f"rustdoc:{rustdoc}"
    return f"doc:{host}/{_page_path(segments)}"


@dataclass(frozen=True)
class Doc:
    doc_type: str
    url: str
    title: str
    text: str
    context: str
    banned: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return doc_key(self.url) or self.url


def build_row(doc: Doc, *, query_text: str, syntax: str, hour_ts: datetime) -> dict[str, Any]:
    return {
        "query_id": query_id(query_text, hour_ts=hour_ts),
        "query_hash": query_hash(query_text),
        "query_text": query_text,
        "query_source": CODING_SOURCE,
        "query_origin": {
            "bucket": doc.doc_type,
            "syntax": syntax,
            "provenance": {"title": doc.title, "url": doc.url, "context": doc.context},
        },
        "gold": {"doc_key": doc.key, "ids": {"doc": doc.key}, "url": doc.url, "title": doc.title},
        "hour_ts": hour_ts.astimezone(UTC).isoformat(),
    }
