import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from keenbench.shared.identity import query_hash, query_id

FINANCE_SOURCE = "finance"
SUITES = ("filings", "filingdoc")
SYNTAXES = ("plain", "quoted", "site", "date")

FILINGS_SYNTAX_CYCLE = ("plain", "quoted")
FILINGDOC_SYNTAX_CYCLE = ("plain", "site", "plain", "quoted", "plain", "date")


@dataclass(frozen=True)
class QuarterlyField:
    field_type: str
    template: str
    cues: tuple[str, ...] = ()


QUARTERLY_FIELDS = {
    "revenue": QuarterlyField("money", "{name} {quarter} revenue"),
    "net_income": QuarterlyField("money", "{name} {quarter} net income"),
    "operating_income": QuarterlyField("money", "{name} {quarter} operating income"),
    "eps_diluted": QuarterlyField(
        "money", "{name} {quarter} diluted eps", ("eps", "per share", "earnings per")
    ),
}


@dataclass(frozen=True)
class QuarterFact:
    field: str
    value: float
    fy: int
    fp: str
    end: str


@dataclass(frozen=True)
class Filing:
    cik: int
    company: str
    ticker: str
    form: str
    adsh: str
    filed: str
    primary_doc: str
    tier: str = ""

    @property
    def adsh_nodash(self) -> str:
        return self.adsh.replace("-", "")


def quarter_phrase(fact: QuarterFact) -> str:
    return f"{fact.fp.lower()} fiscal {fact.fy}"


def build_filing_row(
    *,
    company: str,
    ticker: str,
    cik: int,
    tier: str,
    fact: QuarterFact,
    query_text: str,
    syntax: str,
    hour_ts: datetime,
    now: datetime,
) -> dict[str, Any]:
    spec = QUARTERLY_FIELDS[fact.field]
    age_days = _age_days(fact.end, now)
    gold = {
        "field": fact.field,
        "field_type": spec.field_type,
        "value": fact.value,
        "aliases": [],
        "fy": fact.fy,
        "fp": fact.fp,
        "period_end": fact.end,
        "tier": tier,
        "age_bucket": "recent" if age_days is not None and age_days <= 200 else "older",
    }
    provenance = {
        "company": company,
        "ticker": ticker,
        "cik": cik,
        "registry": "sec_xbrl",
        "source_url": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
    }
    return _row(
        query_text,
        bucket="filings",
        syntax=syntax,
        gold=gold,
        provenance=provenance,
        hour_ts=hour_ts,
    )


def build_filingdoc_row(
    filing: Filing,
    *,
    query_text: str,
    syntax: str,
    hour_ts: datetime,
) -> dict[str, Any]:
    gold = {
        "ids": {"adsh": filing.adsh_nodash},
        "form": filing.form,
        "company": filing.company,
        "filed": filing.filed,
        "tier": filing.tier,
    }
    provenance = {
        "company": filing.company,
        "ticker": filing.ticker,
        "cik": filing.cik,
        "form": filing.form,
        "filed": filing.filed,
        "url": (
            f"https://www.sec.gov/Archives/edgar/data/{filing.cik}"
            f"/{filing.adsh_nodash}/{filing.primary_doc}"
        ),
    }
    return _row(
        query_text,
        bucket="filingdoc",
        syntax=syntax,
        gold=gold,
        provenance=provenance,
        hour_ts=hour_ts,
    )


def _age_days(end: str, now: datetime) -> int | None:
    try:
        end_dt = datetime.fromisoformat(end).replace(tzinfo=UTC)
    except ValueError:
        return None
    return (now - end_dt).days


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
        "query_source": FINANCE_SOURCE,
        "query_origin": {"bucket": bucket, "syntax": syntax, "provenance": provenance},
        "gold": gold,
        "hour_ts": hour_ts.astimezone(UTC).isoformat(),
    }


def serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["query_origin"] = json.dumps(row["query_origin"], sort_keys=True)
    out["gold"] = json.dumps(row["gold"], sort_keys=True)
    return out
