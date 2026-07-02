import asyncio
import re
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
    industry_qids,
    latest_annual,
    lei,
    website,
)

COMPANYFILL_MIN_FIELDS = 4
FINANCIALS_MIN_FIELDS = 3
FINANCIALS_MAX_AGE_YEARS = 2
_JUNK_INDUSTRY = ("classification", "standard industrial", "except", "n.e.c")


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
    ceo_qid: str | None,
    country: str | None,
    inds: list[str],
    *,
    min_employee_year: int,
) -> list[tuple[str, Any, list[str]]]:
    fields: list[tuple[str, Any, list[str]]] = []
    if ceo_qid and ceo_qid in labels:
        label, aliases = labels[ceo_qid]
        fields.append(("ceo", label, aliases))
    fy = founded_year(claims)
    if fy is not None:
        fields.append(("founded_year", fy, []))
    if country and country in labels:
        label, aliases = labels[country]
        fields.append(("hq_country", label, aliases))
    ind_labels = [
        re.sub(r"\s+industry$", "", labels[q][0], flags=re.IGNORECASE)
        for q in inds
        if q in labels and not any(j in labels[q][0].lower() for j in _JUNK_INDUSTRY)
    ]
    if ind_labels:
        fields.append(("industry", ind_labels, []))
    web = website(claims)
    if web:
        dom = registrable_domain(web)
        if dom and "." in dom:
            fields.append(("website", dom, [web]))
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
    if qid:
        source_url = f"https://www.wikidata.org/wiki/{qid}"
        claims = await wikidata.entity(qid)
        ceo_qid, _ = current_ceo(claims)
        country = await wikidata.country_qid(claims)
        inds = industry_qids(claims)
        labels = await wikidata.labels_and_aliases([q for q in [ceo_qid, country, *inds] if q])
        for field, value, aliases in _grounded_fields(
            claims, labels, ceo_qid, country, inds, min_employee_year=min_employee_year
        ):
            fields.append((field, value, aliases, "wikidata", source_url))
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
    return [
        build_gold_row(
            field=field,
            spec=COMPANYFILL_FIELDS[field],
            value=value,
            aliases=aliases,
            bucket="companyfill",
            query_text=COMPANYFILL_FIELDS[field].template.format(name=name),
            entity_keys=entity_keys,
            registry=registry,
            source_url=source_url,
            hour_ts=hour_ts,
        )
        for field, value, aliases, registry, source_url in fields
    ]


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

    async def one(row: dict) -> list[dict]:
        out: list[dict] = []
        try:
            if "companyfill" in suites and wikidata is not None:
                cf = await _companyfill_rows(
                    row,
                    wikidata,
                    gleif,
                    min_employee_year=min_employee_year,
                    hour_ts=hour_ts,
                )
                if any(r["query_origin"]["provenance"].get("qid") for r in cf):
                    stats.resolved += 1
                out.extend(cf)
            if "financials" in suites and sec is not None:
                out.extend(await _financials_rows(row, sec, hour_ts=hour_ts))
        except Exception:
            stats.errors += 1
        return out

    results = await asyncio.gather(*[one(row) for row in companies])
    rows = [r for batch in results for r in batch]
    stats.rows = len(rows)
    return rows, stats
