from dataclasses import dataclass
from datetime import datetime
from typing import Any

from needle.finance.canon import FIELD_TYPES
from needle.shared.identity import query_hash, query_id

HAYSTACK_PRODUCER_ID = "haystack"

SUITES = ("gov", "sec", "wiki", "arxiv")

HAYSTACK_FIELD_TYPES = FIELD_TYPES - {"country", "domain"}

DEFAULT_SYNTAX_CYCLE = ("plain", "site", "plain", "date")
WIKI_SYNTAX_CYCLE = ("plain", "site")


@dataclass(frozen=True)
class SuiteSpec:
    site: str
    syntax_cycle: tuple[str, ...]
    source_label: str


SUITE_SPECS = {
    "gov": SuiteSpec("federalregister.gov", DEFAULT_SYNTAX_CYCLE, "Federal Register rule"),
    "sec": SuiteSpec("sec.gov", DEFAULT_SYNTAX_CYCLE, "SEC filing"),
    "wiki": SuiteSpec("en.wikipedia.org", WIKI_SYNTAX_CYCLE, "Wikipedia article"),
    "arxiv": SuiteSpec("arxiv.org", DEFAULT_SYNTAX_CYCLE, "arXiv paper"),
}


@dataclass(frozen=True)
class DeepDoc:
    suite: str
    title: str
    url: str
    published: str
    text: str
    doc_keys: dict[str, Any]


def build_gold_row(
    *,
    suite: str,
    field_type: str,
    value: str,
    query_text: str,
    doc: DeepDoc,
    depth_pct: int,
    hour_ts: datetime,
    syntax: str = "plain",
) -> dict[str, Any]:
    ts = hour_ts.isoformat()
    return {
        "query_id": query_id(query_text, hour_ts=hour_ts),
        "query_hash": query_hash(query_text),
        "query_text": query_text,
        "query_source": HAYSTACK_PRODUCER_ID,
        "query_origin": {
            "bucket": suite,
            "syntax": syntax,
            "topical_domain": "haystack",
            "subcategory": f"{suite}_{field_type}",
            "provenance": {
                "producer": HAYSTACK_PRODUCER_ID,
                "source_url": doc.url,
                "doc_title": doc.title,
                "published": doc.published,
                "depth_pct": depth_pct,
                "doc_chars": len(doc.text),
                **doc.doc_keys,
            },
        },
        "topical_domain": "haystack",
        "hour_ts": ts,
        "query_produced_at": ts,
        "gold": {
            "field": "haystack",
            "field_type": field_type,
            "value": value,
            "aliases": [],
            "freshness_window": "static",
            "tier": "",
        },
    }
