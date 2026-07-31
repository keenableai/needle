from dataclasses import dataclass
from datetime import datetime
from typing import Any

from keenbench.finance.canon import LEGAL_SUFFIXES
from keenbench.shared.identity import query_hash, query_id

FINANCE_PRODUCER_ID = "finance"

FRESHNESS_LADDER = ("1h", "24h", "7d", "30d", "1y", "5y", "static")


@dataclass(frozen=True)
class FieldSpec:
    field_type: str
    freshness_window: str
    template: str
    cues: tuple[str, ...] = ()
    nl_template: str | None = None


FINANCE_FIELDS = {
    "ceo": FieldSpec("person", "1y", "{name} ceo", nl_template="who is the ceo of {name}"),
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
        nl_template="when was {name} founded",
    ),
    "hq_country": FieldSpec(
        "country",
        "static",
        "{name} headquarters country",
        nl_template="in which country is {name} headquartered",
    ),
    "website": FieldSpec(
        "domain",
        "static",
        "{name} official website",
        nl_template="what is the official website of {name}",
    ),
    "employees": FieldSpec(
        "numeric_band",
        "1y",
        "{name} number of employees",
        ("employee", "employees", "employs", "headcount", "workforce", "staff"),
        nl_template="how many people work at {name}",
    ),
    "lei": FieldSpec(
        "exact_id", "static", "{name} lei code", nl_template="what is the lei code of {name}"
    ),
    "ticker": FieldSpec(
        "exact_id",
        "static",
        "{name} stock ticker symbol",
        ("ticker", "symbol", "stock", "nasdaq", "nyse", "shares"),
        nl_template="what is the stock ticker symbol of {name}",
    ),
}

QUARTERLY_FIELDS = {
    "revenue": FieldSpec("money", "1y", "{name} {quarter} revenue"),
    "net_income": FieldSpec("money", "1y", "{name} {quarter} net income"),
    "operating_income": FieldSpec("money", "1y", "{name} {quarter} operating income"),
    "eps_diluted": FieldSpec(
        "money", "1y", "{name} {quarter} diluted eps", ("eps", "per share", "earnings per")
    ),
}

FILINGDOC_FIELD = "filing"
FILINGDOC_SPEC = FieldSpec("exact_id", "static", "")

FIELD_SPECS = {**FINANCE_FIELDS, **QUARTERLY_FIELDS, FILINGDOC_FIELD: FILINGDOC_SPEC}

FILINGS_SYNTAX_CYCLE = ("plain", "quoted")
FILINGDOC_SYNTAX_CYCLE = ("plain", "site", "plain", "quoted", "plain", "date")


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
    syntax: str = "plain",
    tier: str = "",
) -> dict[str, Any]:
    ts = hour_ts.isoformat()
    return {
        "query_id": query_id(query_text, hour_ts=hour_ts),
        "query_hash": query_hash(query_text),
        "query_text": query_text,
        "query_source": FINANCE_PRODUCER_ID,
        "query_origin": {
            "bucket": bucket,
            "syntax": syntax,
            "topical_domain": "finance",
            "subcategory": f"{bucket}_{field}",
            "provenance": {
                "producer": FINANCE_PRODUCER_ID,
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
            "tier": tier,
        },
    }
