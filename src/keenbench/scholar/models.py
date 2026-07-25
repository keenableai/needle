import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from keenbench.shared.identity import query_hash, query_id

AGE_BUCKETS = ("7d", "30d", "1y", "older")
AGE_BUCKET_DAYS = {"7d": 7, "30d": 30, "1y": 365}
AGE_BANDS = {
    "7d": (7, 0),
    "30d": (29, 8),
    "1y": (364, 31),
    "older": (1800, 366),
}

SCHOLAR_SOURCE = "scholar"

ARXIV_CAT_DOMAIN = {
    "cs": "computer science",
    "q-bio": "life sciences",
    "econ": "social sciences",
    "q-fin": "social sciences",
}


def coarse_domain(category: str) -> str:
    prefix = category.split(".", 1)[0].lower()
    return ARXIV_CAT_DOMAIN.get(prefix, "physical sciences")


@dataclass(frozen=True)
class Paper:
    suite: str
    title: str
    abstract: str
    published: datetime
    url: str
    domain: str
    arxiv_id: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None

    @property
    def ids(self) -> dict[str, str]:
        ids = {"arxiv": self.arxiv_id, "doi": self.doi, "pmid": self.pmid}
        return {k: v for k, v in ids.items() if v}

    @property
    def paper_key(self) -> str:
        return self.arxiv_id or self.doi or self.pmid or self.url


def age_bucket(published: datetime, *, now: datetime) -> str:
    days = (now - published).days
    for bucket in ("7d", "30d", "1y"):
        if days <= AGE_BUCKET_DAYS[bucket]:
            return bucket
    return "older"


def build_gold_row(
    paper: Paper,
    *,
    query_text: str,
    bucket: str,
    hour_ts: datetime,
    now: datetime,
) -> dict[str, Any]:
    provenance = {
        "suite": paper.suite,
        "title": paper.title,
        "url": paper.url,
        "published_date": paper.published.date().isoformat(),
    }
    query_origin = {
        "bucket": bucket,
        "suite": paper.suite,
        "provenance": provenance,
    }
    gold = {
        "paper_key": paper.paper_key,
        "ids": paper.ids,
        "published_date": paper.published.date().isoformat(),
        "age_bucket": age_bucket(paper.published, now=now),
        "domain": paper.domain,
    }
    return {
        "query_id": query_id(query_text, hour_ts=hour_ts),
        "query_hash": query_hash(query_text),
        "query_text": query_text,
        "query_source": SCHOLAR_SOURCE,
        "query_origin": query_origin,
        "gold": gold,
        "hour_ts": hour_ts.astimezone(UTC).isoformat(),
    }


def serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["query_origin"] = json.dumps(row["query_origin"], sort_keys=True)
    out["gold"] = json.dumps(row["gold"], sort_keys=True)
    return out
