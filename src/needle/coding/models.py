from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from needle.shared.identity import query_hash, query_id

CODING_SOURCE = "coding"
BUCKETS = ("title", "task")
DEFAULT_HOSTS = ("firecrawl", "browserbase", "resend", "langchain")


@dataclass(frozen=True)
class DocHost:
    slug: str
    product: str
    llms_url: str


@dataclass(frozen=True)
class DocPage:
    product: str
    title: str
    description: str
    host: str
    path: str
    section: str = ""
    body: str = ""

    @property
    def item_key(self) -> str:
        return f"{self.host}{self.path}"

    @property
    def url(self) -> str:
        return f"https://{self.item_key}"

    @property
    def markdown_url(self) -> str:
        return f"{self.url}.md"

    @property
    def slug(self) -> str:
        return self.path.rsplit("/", 1)[-1]


def build_gold_row(
    page: DocPage,
    *,
    query_text: str,
    bucket: str,
    hour_ts: datetime,
) -> dict[str, Any]:
    gold = {
        "item_key": page.item_key,
        "ids": {"page": page.item_key},
        "product": page.product,
        "host": page.host,
        "path": page.path,
    }
    provenance = {
        "title": page.title,
        "url": page.url,
        "product": page.product,
        "description": page.description,
    }
    return {
        "query_id": query_id(query_text, hour_ts=hour_ts),
        "query_hash": query_hash(query_text),
        "query_text": query_text,
        "query_source": CODING_SOURCE,
        "query_origin": {"bucket": bucket, "provenance": provenance},
        "gold": gold,
        "hour_ts": hour_ts.astimezone(UTC).isoformat(),
    }
