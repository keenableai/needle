import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from needle.shared.identity import query_hash, query_id

CODING_SOURCE = "coding"
DOC_TYPES = ("api", "issue", "qa")

DOC_KEY_RULES = (
    (
        "docs.python.org",
        "py",
        re.compile(r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:\d+(?:\.\d+)*|dev)/(.+?)(?:\.html)?$"),
    ),
    (
        "numpy.org",
        "numpy",
        re.compile(r"^/(?:doc/(?:stable|dev|\d+(?:\.\d+)*)|devdocs)/(.+?)(?:\.html)?$"),
    ),
    (
        "pandas.pydata.org",
        "pandas",
        re.compile(
            r"^/(?:docs(?:/dev)?|pandas-docs/(?:stable|dev|version/[\d.]+))/(.+?)(?:\.html)?$"
        ),
    ),
    ("developer.mozilla.org", "mdn", re.compile(r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?docs/(.+)$")),
    ("github.com", "gh", re.compile(r"^/([\w.-]+/[\w.-]+)/(?:issues|pull)/(\d+)(?:/|$)")),
    ("stackoverflow.com", "so", re.compile(r"^/(?:questions|q)/(\d+)(?:/|$)")),
)


def doc_key(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").removeprefix("www.")
    path = parts.path.rstrip("/").lower()
    for rule_host, prefix, pattern in DOC_KEY_RULES:
        if host == rule_host:
            m = pattern.match(path)
            return f"{prefix}:{'#'.join(m.groups())}" if m else None
    return None


@dataclass(frozen=True)
class Doc:
    doc_type: str
    key: str
    url: str
    title: str
    text: str
    context: str
    banned: tuple[str, ...] = ()


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
