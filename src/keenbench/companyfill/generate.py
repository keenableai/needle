import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from keenbench.companyfill.canon import registrable_domain
from keenbench.companyfill.models import (
    COMPANYFILL_FIELDS,
    FINANCIALS_FIELDS,
    build_gold_row,
    display_name,
)
from keenbench.companyfill.registries import (
    FINANCIAL_CONCEPTS,
    GleifClient,
    SecClient,
    WikidataClient,
    current_ceo,
    employees,
    founded_year,
    latest_annual,
    lei,
    website,
)
from keenbench.shared.concurrency import bounded_gather

COMPANYFILL_MIN_FIELDS = 4
FINANCIALS_MIN_FIELDS = 3
FINANCIALS_MAX_AGE_YEARS = 2
COMPANY_CONCURRENCY = 16


def _seed_title(title: str) -> str:
    return " ".join(t for t in title.split() if not t.startswith("/"))


@dataclass
class GenStats:
    companies: int = 0
    resolved: int = 0
    rows: int = 0
    errors: int = 0


def _grounded_fields(
    claims: dict,
    labels: dict[str, tuple[str, list[str]]],
    qid: str,
    ceo_qid: str | None,
    ceo_since: int | None,
    country: str | None,
    *,
    min_employee_year: int,
) -> list[tuple[str, Any, list[str]]]:
    fields: list[tuple[str, Any, list[str]]] = []
    if ceo_qid and ceo_qid in labels:
        label, aliases = labels[ceo_qid]
        fields.append(("ceo", label, aliases))
        if ceo_since is not None:
            fields.append(("ceo_since", ceo_since, []))
        if qid in labels:
            company_label, company_aliases = labels[qid]
            fields.append(("ceo_company", company_label, company_aliases))
    founded = founded_year(claims)
    if founded is not None:
        fields.append(("founded_year", founded, []))
    if country and country in labels:
        label, aliases = labels[country]
        fields.append(("hq_country", label, aliases))
    site = website(claims)
    if site:
        domain = registrable_domain(site)
        if domain and "." in domain:
            fields.append(("website", domain, [site]))
    emp, emp_year = employees(claims)
    if emp is not None and emp_year and emp_year >= min_employee_year:
        fields.append(("employees", emp, []))
    return fields


async def _companyfill_rows(
    seed_row: dict,
    wikidata: WikidataClient,
    gleif: GleifClient | None,
    *,
    min_employee_year: int,
    hour_ts: datetime,
) -> list[dict]:
    title, ticker, cik = seed_row["title"], seed_row["ticker"], seed_row["cik"]
    qid = await wikidata.resolve(_seed_title(title))
    fields: list[tuple[str, Any, list[str], str, str]] = []
    ceo_name = ""
    if qid:
        source_url = f"https://www.wikidata.org/wiki/{qid}"
        claims = await wikidata.entity(qid)
        ceo_qid, ceo_since = current_ceo(claims)
        country = await wikidata.country_qid(claims)
        labels = await wikidata.labels_and_aliases([q for q in [qid, ceo_qid, country] if q])
        for field, value, aliases in _grounded_fields(
            claims, labels, qid, ceo_qid, ceo_since, country, min_employee_year=min_employee_year
        ):
            fields.append((field, value, aliases, "wikidata", source_url))
        if ceo_qid and ceo_qid in labels:
            ceo_name = labels[ceo_qid][0].lower()
        lei_val = lei(claims)
        lei_registry = "wikidata"
        if gleif is not None and not lei_val:
            lei_val = await gleif.lei_by_name(_seed_title(title))
            lei_registry = "gleif"
        if lei_val:
            fields.append(("lei", lei_val, [], lei_registry, source_url))
    if len(ticker) >= 2:
        sec_url = f"https://www.sec.gov/cgi-bin/browse-edgar?CIK={cik}"
        fields.append(("ticker", ticker, [], "sec", sec_url))
    if len(fields) < COMPANYFILL_MIN_FIELDS:
        return []
    name = display_name(title)
    entity_keys = {"entity": title, "ticker": ticker, "cik": cik, "qid": qid}
    rows = []
    for field, value, aliases, registry, source_url in fields:
        spec = COMPANYFILL_FIELDS[field]
        variants = [("companyfill", spec.template)]
        if spec.nl_template:
            variants.append(("companyfill_nl", spec.nl_template))
        for bucket, template in variants:
            rows.append(
                build_gold_row(
                    field=field,
                    spec=spec,
                    value=value,
                    aliases=aliases,
                    bucket=bucket,
                    query_text=template.format(name=name, ceo=ceo_name),
                    entity_keys=entity_keys,
                    registry=registry,
                    source_url=source_url,
                    hour_ts=hour_ts,
                )
            )
    return rows


async def _financials_rows(seed_row: dict, sec: SecClient, *, hour_ts: datetime) -> list[dict]:
    title, ticker, cik = seed_row["title"], seed_row["ticker"], seed_row["cik"]
    facts = await sec.companyfacts(cik)
    if not facts:
        return []
    fields = []
    for field, concepts in FINANCIAL_CONCEPTS.items():
        val, end, fy = latest_annual(facts, concepts)
        if val is None or not fy or not end:
            continue
        if int(end[:4]) < hour_ts.year - FINANCIALS_MAX_AGE_YEARS:
            continue
        fields.append((field, int(val), fy))
    if len(fields) < FINANCIALS_MIN_FIELDS:
        return []
    name = display_name(title)
    source_url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}&type=10-K"
    )
    entity_keys = {"entity": title, "ticker": ticker, "cik": cik}
    return [
        build_gold_row(
            field=field,
            spec=FINANCIALS_FIELDS[field],
            value=value,
            aliases=[],
            bucket="financials",
            query_text=FINANCIALS_FIELDS[field].template.format(name=name, fy=fy),
            entity_keys=entity_keys,
            registry="sec_xbrl",
            source_url=source_url,
            hour_ts=hour_ts,
        )
        for field, value, fy in fields
    ]


async def run_generate(
    seed_rows: list[dict],
    *,
    wikidata: WikidataClient | None,
    sec: SecClient | None,
    gleif: GleifClient | None,
    suites: tuple[str, ...],
    hour_ts: datetime,
    min_employee_year: int,
) -> tuple[list[dict], GenStats]:
    stats = GenStats()
    seen_titles: set[str] = set()
    companies = []
    for row in seed_rows:
        key = row["title"].strip().lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        companies.append(row)
    stats.companies = len(companies)

    async def company_rows(row: dict) -> list[dict]:
        tasks = []
        if "companyfill" in suites and wikidata is not None:
            tasks.append(
                _companyfill_rows(
                    row, wikidata, gleif, min_employee_year=min_employee_year, hour_ts=hour_ts
                )
            )
        if "financials" in suites and sec is not None:
            tasks.append(_financials_rows(row, sec, hour_ts=hour_ts))
        try:
            batches = await asyncio.gather(*tasks)
        except Exception:
            stats.errors += 1
            return []
        out = [r for batch in batches for r in batch]
        if any(r["query_origin"]["provenance"].get("qid") for r in out):
            stats.resolved += 1
        return out

    results = await bounded_gather(companies, company_rows, concurrency=COMPANY_CONCURRENCY)
    rows = [r for batch in results for r in batch]
    stats.rows = len(rows)
    return rows, stats
