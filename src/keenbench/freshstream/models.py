from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from keenbench.freshstream.taxonomy import TOPICAL_DOMAINS
from keenbench.shared.identity import query_hash, query_id

FRESH_PRODUCER_ID = "fresh-queries"


def subcategory_for(bucket: str, topical_domain: str) -> str:
    if bucket == "trending":
        return "google_trends"
    return f"rss_{topical_domain}"


def build_query_origin(
    *,
    bucket: str,
    topical_domain: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    if topical_domain not in TOPICAL_DOMAINS:
        topical_domain = "other"
    return {
        "bucket": bucket,
        "topical_domain": topical_domain,
        "subcategory": subcategory_for(bucket, topical_domain),
        "provenance": provenance,
    }


@dataclass(frozen=True)
class QueryRow:
    query_id: str
    query_hash: str
    query_text: str
    query_source: str
    query_origin: dict[str, Any]
    topical_domain: str
    hour_ts: datetime
    query_produced_at: datetime

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["hour_ts"] = self.hour_ts.isoformat()
        d["query_produced_at"] = self.query_produced_at.isoformat()
        return d


def build_query_row(
    *,
    query_text: str,
    hour_ts: datetime,
    bucket: str,
    topical_domain: str,
    provenance: dict[str, Any],
    produced_at: datetime | None = None,
) -> QueryRow:
    td = topical_domain if topical_domain in TOPICAL_DOMAINS else "other"
    return QueryRow(
        query_id=query_id(query_text, hour_ts=hour_ts),
        query_hash=query_hash(query_text),
        query_text=query_text,
        query_source=FRESH_PRODUCER_ID,
        query_origin=build_query_origin(bucket=bucket, topical_domain=td, provenance=provenance),
        topical_domain=td,
        hour_ts=hour_ts,
        query_produced_at=produced_at or hour_ts,
    )
