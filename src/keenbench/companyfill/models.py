from dataclasses import dataclass
from datetime import datetime
from typing import Any

from keenbench.companyfill.canon import LEGAL_SUFFIXES
from keenbench.shared.identity import query_hash, query_id

COMPANYFILL_PRODUCER_ID = "companyfill"

FRESHNESS_LADDER = ("1h", "24h", "7d", "30d", "1y", "5y", "static")


@dataclass(frozen=True)
class FieldSpec:
    field_type: str
    freshness_window: str
    template: str
    cues: tuple[str, ...] = ()


COMPANYFILL_FIELDS = {
    "ceo": FieldSpec("person", "1y", "{name} ceo"),
    "ceo_since": FieldSpec(
        "year",
        "1y",
        "when did {ceo} become ceo of {name}",
        ("became", "become", "since", "appointed", "named", "succeeded", "took over"),
    ),
    "ceo_company": FieldSpec(
        "entity",
        "1y",
        "which company is {ceo} the ceo of",
        ("ceo", "chief executive"),
    ),
    "founded_year": FieldSpec(
        "year",
        "static",
        "{name} founded year",
        ("founded", "founding", "established", "incorporated", "began", "started", "since"),
    ),
    "hq_country": FieldSpec("country", "static", "{name} headquarters country"),
    "website": FieldSpec("domain", "static", "{name} official website"),
    "employees": FieldSpec(
        "numeric_band",
        "1y",
        "{name} number of employees",
        ("employee", "employees", "employs", "headcount", "workforce", "staff"),
    ),
    "lei": FieldSpec("exact_id", "static", "{name} lei code"),
    "ticker": FieldSpec(
        "exact_id",
        "static",
        "{name} stock ticker symbol",
        ("ticker", "symbol", "stock", "nasdaq", "nyse", "shares"),
    ),
}

NL_TEMPLATES = {
    "ceo": "who is the ceo of {name}",
    "founded_year": "when was {name} founded",
    "hq_country": "in which country is {name} headquartered",
    "website": "what is the official website of {name}",
    "employees": "how many people work at {name}",
    "lei": "what is the lei code of {name}",
    "ticker": "what is the stock ticker symbol of {name}",
}

FINANCIALS_FIELDS = {
    "revenue": FieldSpec("money", "1y", "{name} revenue fiscal year {fy}"),
    "net_income": FieldSpec("money", "1y", "{name} net income fiscal year {fy}"),
    "total_assets": FieldSpec("money", "1y", "{name} total assets fiscal year {fy}"),
    "stockholders_equity": FieldSpec("money", "1y", "{name} stockholders equity fiscal year {fy}"),
}

FIELD_SPECS = {**COMPANYFILL_FIELDS, **FINANCIALS_FIELDS}


def display_name(title: str) -> str:
    tokens = [t for t in title.strip().lower().split() if not t.startswith("/")]
    while tokens and (tokens[-1] == "&" or tokens[-1].strip(".,/") in LEGAL_SUFFIXES):
        tokens.pop()
    name = " ".join(tokens).rstrip(" ,.")
    return name or title.strip().lower()


def cues_for(field: str) -> tuple[str, ...]:
    spec = FIELD_SPECS.get(field)
    return spec.cues if spec else ()


def build_gold_row(
    *,
    field: str,
    spec: FieldSpec,
    value: Any,
    aliases: list[str],
    bucket: str,
    query_text: str,
    entity_keys: dict[str, Any],
    registry: str,
    source_url: str,
    hour_ts: datetime,
) -> dict[str, Any]:
    ts = hour_ts.isoformat()
    return {
        "query_id": query_id(query_text, hour_ts=hour_ts),
        "query_hash": query_hash(query_text),
        "query_text": query_text,
        "query_source": COMPANYFILL_PRODUCER_ID,
        "query_origin": {
            "bucket": bucket,
            "topical_domain": "finance",
            "subcategory": f"{bucket}_{field}",
            "provenance": {
                "producer": COMPANYFILL_PRODUCER_ID,
                "registry": registry,
                "source_url": source_url,
                **entity_keys,
            },
        },
        "topical_domain": "finance",
        "hour_ts": ts,
        "query_produced_at": ts,
        "gold": {
            "field": field,
            "field_type": spec.field_type,
            "value": value,
            "aliases": aliases,
            "freshness_window": spec.freshness_window,
        },
    }
