from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from keenbench.shared.identity import query_hash, query_id

LEGAL_SOURCE = "legal"
SUITES = ("caselaw", "code")

COURT_PHRASES = {
    "scotus": "supreme court",
    "ca1": "first circuit",
    "ca2": "second circuit",
    "ca3": "third circuit",
    "ca4": "fourth circuit",
    "ca5": "fifth circuit",
    "ca6": "sixth circuit",
    "ca7": "seventh circuit",
    "ca8": "eighth circuit",
    "ca9": "ninth circuit",
    "ca10": "tenth circuit",
    "ca11": "eleventh circuit",
    "cadc": "dc circuit",
    "cafc": "federal circuit",
    "dcd": "district court district of columbia",
    "nysd": "southern district of new york",
    "cand": "northern district of california",
    "ilnd": "northern district of illinois",
}

@dataclass(frozen=True)
class Case:
    court_id: str
    case_name: str
    docket: str
    citations: tuple[str, ...]
    date_filed: date
    cluster_id: int
    absolute_url: str

    @property
    def case_key(self) -> str:
        return str(self.cluster_id)


@dataclass(frozen=True)
class CodeSection:
    title_num: int
    part: str
    section: str
    heading: str
    text: str

    @property
    def citation(self) -> str:
        return f"{self.title_num} CFR {self.section}"

    @property
    def section_key(self) -> str:
        return f"{self.title_num}:{self.section}"


def build_case_row(
    case: Case,
    *,
    query_text: str,
    syntax: str,
    party_tokens: list[str],
    hour_ts: datetime,
) -> dict[str, Any]:
    gold = {
        "case_key": case.case_key,
        "ids": {
            "cluster": str(case.cluster_id),
            "docket": case.docket,
            "cites": list(case.citations),
        },
        "party_tokens": party_tokens,
        "court": case.court_id,
        "date_filed": case.date_filed.isoformat(),
        "case_name": case.case_name,
    }
    provenance = {
        "case_name": case.case_name,
        "url": f"https://www.courtlistener.com{case.absolute_url}",
        "date_filed": case.date_filed.isoformat(),
    }
    return _row(
        query_text,
        bucket="caselaw",
        syntax=syntax,
        gold=gold,
        provenance=provenance,
        hour_ts=hour_ts,
    )


def build_code_row(
    section: CodeSection,
    *,
    query_text: str,
    syntax: str,
    hour_ts: datetime,
) -> dict[str, Any]:
    gold = {
        "case_key": section.section_key,
        "ids": {"cfr": section.section_key},
        "citation": section.citation,
        "heading": section.heading,
    }
    provenance = {
        "citation": section.citation,
        "heading": section.heading,
        "url": (
            f"https://www.ecfr.gov/current/title-{section.title_num}/section-{section.section}"
        ),
    }
    return _row(
        query_text,
        bucket="code",
        syntax=syntax,
        gold=gold,
        provenance=provenance,
        hour_ts=hour_ts,
    )


def _row(
    query_text: str,
    *,
    bucket: str,
    syntax: str,
    gold: dict[str, Any],
    provenance: dict[str, Any],
    hour_ts: datetime,
) -> dict[str, Any]:
    return {
        "query_id": query_id(query_text, hour_ts=hour_ts),
        "query_hash": query_hash(query_text),
        "query_text": query_text,
        "query_source": LEGAL_SOURCE,
        "query_origin": {"bucket": bucket, "syntax": syntax, "provenance": provenance},
        "gold": gold,
        "hour_ts": hour_ts.astimezone(UTC).isoformat(),
    }
