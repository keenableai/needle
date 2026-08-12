import itertools
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from keenbench.finance.canon import registrable_domain
from keenbench.finance.models import (
    FILINGDOC_FIELD,
    FILINGDOC_SPEC,
    FILINGDOC_SYNTAX_CYCLE,
    FILINGS_SYNTAX_CYCLE,
    FINANCE_FIELDS,
    QUARTERLY_FIELDS,
    Filing,
    QuarterFact,
    build_gold_row,
    display_name,
)
from keenbench.finance.projection import (
    MIN_DOC_CHARS,
    build_filingdoc_prompt,
    clean_filingdoc_query,
    filingdoc_query_ok,
    filingdoc_syntax_query,
    filings_query,
)
from keenbench.finance.registries import (
    SEC_FACTS_URL,
    GleifClient,
    SecClient,
    WikidataClient,
    current_ceo,
    employees,
    founded_year,
    lei,
    website,
)
from keenbench.finance.sources import SEC_DOC_URL, EdgarClient, quarterly_facts
from keenbench.shared.concurrency import bounded_gather
from keenbench.shared.llm import LLMClient
from keenbench.shared.sampling import dedupe_by, shuffle_indices

FINANCE_MIN_FIELDS = 4
COMPANY_CONCURRENCY = 16
FILINGS_CONCURRENCY = 8
DOC_OVERSAMPLE = 3
DOC_FORMS = frozenset({"10-K", "10-Q", "8-K"})
TIER_BOUNDS = (("mega", 0, 100), ("large", 100, 500), ("mid", 500, 2500))
MEGA_CAP_TICKERS = frozenset({"AAPL", "MSFT", "NVDA", "GOOG", "GOOGL", "AMZN"})


def _seed_title(title: str) -> str:
    return " ".join(t for t in title.split() if not t.startswith("/"))


def tiered_companies(all_rows: list[dict], per_tier: int, seed: int) -> list[dict]:
    if len(all_rows) > 100 and not MEGA_CAP_TICKERS & {r["ticker"] for r in all_rows[:100]}:
        raise ValueError(
            "no mega-cap ticker in the first 100 company_tickers.json rows; "
            "the market-cap ordering that cap tiers rely on looks broken"
        )
    out = []
    for name, lo, hi in TIER_BOUNDS:
        pool = all_rows[lo:hi]
        perm = shuffle_indices(len(pool), seed ^ lo)
        for i in perm[:per_tier]:
            out.append({**pool[i], "tier": name})
    return out


@dataclass
class GenStats:
    companies: int = 0
    resolved: int = 0
    rows: int = 0
    filings_rows: int = 0
    filingdoc_rows: int = 0
    facts_missing: int = 0
    doc_candidates: int = 0
    doc_fetch_fail: int = 0
    doc_thin: int = 0
    doc_no_query: int = 0
    doc_rejected: int = 0
    doc_surplus: int = 0
    llm_errors: int = 0
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


async def _finance_rows(
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
    if len(fields) < FINANCE_MIN_FIELDS:
        return []
    name = display_name(title)
    entity_keys = {"entity": title, "ticker": ticker, "cik": cik, "qid": qid}
    rows = []
    for field, value, aliases, registry, source_url in fields:
        spec = FINANCE_FIELDS[field]
        variants = [("finance", spec.template)]
        if spec.nl_template:
            variants.append(("finance_nl", spec.nl_template))
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


def _age_days(end: str, now: datetime) -> int | None:
    try:
        return (now - datetime.fromisoformat(end).replace(tzinfo=UTC)).days
    except ValueError:
        return None


async def _filings_rows(
    seed_rows: list[dict],
    sec: SecClient,
    *,
    fields: tuple[str, ...],
    per_company: int,
    quarters_back: int,
    seed: int,
    hour_ts: datetime,
    now: datetime,
    stats: GenStats,
) -> list[dict]:
    async def company_facts(row: dict) -> list[tuple[dict, QuarterFact]]:
        try:
            facts = await sec.companyfacts(row["cik"])
        except Exception:
            stats.errors += 1
            return []
        if not facts:
            return []
        candidates: list[tuple[dict, QuarterFact]] = []
        for field in fields:
            for fact in quarterly_facts(facts, field)[:quarters_back]:
                candidates.append((row, fact))
        if not candidates:
            return []
        perm = shuffle_indices(len(candidates), seed ^ row["cik"])
        return [candidates[i] for i in perm[:per_company]]

    per_company_lists = await bounded_gather(
        seed_rows, company_facts, concurrency=FILINGS_CONCURRENCY
    )

    rows: list[dict] = []
    syntax_cycle = itertools.cycle(FILINGS_SYNTAX_CYCLE)
    for company_list in per_company_lists:
        if not company_list:
            stats.facts_missing += 1
        for row, fact in company_list:
            syntax = next(syntax_cycle)
            age_days = _age_days(fact.end, now)
            entity_keys = {
                "entity": row["title"],
                "ticker": row["ticker"],
                "cik": row["cik"],
                "fy": fact.fy,
                "fp": fact.fp,
                "period_end": fact.end,
                "age_bucket": "recent" if age_days is not None and age_days <= 200 else "older",
            }
            rows.append(
                build_gold_row(
                    field=fact.field,
                    spec=QUARTERLY_FIELDS[fact.field],
                    value=fact.value,
                    aliases=[],
                    bucket="filings",
                    query_text=filings_query(row["title"], fact, syntax),
                    entity_keys=entity_keys,
                    registry="sec_xbrl",
                    source_url=SEC_FACTS_URL.format(cik=int(row["cik"])),
                    hour_ts=hour_ts,
                    syntax=syntax,
                    tier=row.get("tier") or "",
                )
            )
    stats.filings_rows = len(rows)
    return rows


async def _filingdoc_rows(
    seed_rows: list[dict],
    edgar: EdgarClient,
    llm: LLMClient,
    *,
    target: int,
    seed: int,
    hour_ts: datetime,
    doc_concurrency: int,
    stats: GenStats,
) -> list[dict]:
    perm = shuffle_indices(len(seed_rows), seed ^ 0xF111)
    companies = [seed_rows[i] for i in perm[: target * DOC_OVERSAMPLE]]
    stats.doc_candidates = len(companies)

    async def project(row: dict) -> tuple[Filing, str] | str:
        filings = await edgar.filings(row["cik"], forms=DOC_FORMS, limit=20)
        if not filings:
            return "fetch"
        pick = filings[(seed ^ row["cik"]) % len(filings)]
        filing = Filing(
            cik=row["cik"],
            company=row["title"],
            ticker=row["ticker"],
            form=pick["form"],
            adsh=pick["adsh"],
            filed=pick["filed"],
            primary_doc=pick["primary_doc"],
            tier=row.get("tier") or "",
        )
        text = await edgar.document_text(filing)
        if not text:
            return "fetch"
        if len(text) < MIN_DOC_CHARS:
            return "thin"
        try:
            reply, err = await llm.complete(
                build_filingdoc_prompt(filing, text), max_tokens=256, reasoning_effort="minimal"
            )
        except Exception:
            return "llm_error"
        if err is not None:
            return "llm_error"
        query = clean_filingdoc_query(reply)
        if query is None:
            return "no_query"
        if not filingdoc_query_ok(query, filing=filing, text=text):
            return "rejected"
        return filing, query

    projected = await bounded_gather(companies, project, concurrency=doc_concurrency)

    drop_stat = {
        "fetch": "doc_fetch_fail",
        "thin": "doc_thin",
        "llm_error": "llm_errors",
        "no_query": "doc_no_query",
        "rejected": "doc_rejected",
    }
    rows: list[dict] = []
    syntax_cycle = itertools.cycle(FILINGDOC_SYNTAX_CYCLE)
    for outcome in projected:
        if isinstance(outcome, str):
            setattr(stats, drop_stat[outcome], getattr(stats, drop_stat[outcome]) + 1)
            continue
        if len(rows) >= target:
            stats.doc_surplus += 1
            continue
        filing, query = outcome
        syntax = next(syntax_cycle)
        entity_keys = {
            "entity": filing.company,
            "ticker": filing.ticker,
            "cik": filing.cik,
            "form": filing.form,
            "filed": filing.filed,
        }
        source_url = SEC_DOC_URL.format(
            cik=filing.cik, adsh_nodash=filing.adsh_nodash, doc=filing.primary_doc
        )
        rows.append(
            build_gold_row(
                field=FILINGDOC_FIELD,
                spec=FILINGDOC_SPEC,
                value=filing.adsh_nodash,
                aliases=[filing.adsh],
                bucket="filingdoc",
                query_text=filingdoc_syntax_query(query, syntax, filed=filing.filed),
                entity_keys=entity_keys,
                registry="sec_submissions",
                source_url=source_url,
                hour_ts=hour_ts,
                syntax=syntax,
                tier=filing.tier,
            )
        )
    stats.filingdoc_rows = len(rows)
    return rows


async def run_generate(
    all_rows: list[dict],
    *,
    wikidata: WikidataClient | None,
    sec: SecClient | None,
    gleif: GleifClient | None,
    suites: tuple[str, ...],
    hour_ts: datetime,
    min_employee_year: int,
    edgar: EdgarClient | None = None,
    llm: LLMClient | None = None,
    now: datetime | None = None,
    max_companies: int = 1_000_000,
    fields: tuple[str, ...] = ("net_income", "operating_income", "eps_diluted"),
    per_company: int = 2,
    quarters_back: int = 6,
    filingdoc_target: int = 40,
    seed: int = 0,
    doc_concurrency: int = 8,
) -> tuple[list[dict], GenStats]:
    now = now or hour_ts
    stats = GenStats()
    seen_titles: set[str] = set()
    cf_seed = []
    for row in all_rows:
        key = row["title"].strip().lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        cf_seed.append(row)
        if len(cf_seed) >= max_companies:
            break
    stats.companies = len(cf_seed)

    rows: list[dict] = []
    if "finance" in suites and wikidata is not None:

        async def company_rows(row: dict) -> list[dict]:
            try:
                out = await _finance_rows(
                    row, wikidata, gleif, min_employee_year=min_employee_year, hour_ts=hour_ts
                )
            except Exception:
                stats.errors += 1
                return []
            if any(r["query_origin"]["provenance"].get("qid") for r in out):
                stats.resolved += 1
            return out

        batches = await bounded_gather(cf_seed, company_rows, concurrency=COMPANY_CONCURRENCY)
        rows.extend(r for batch in batches for r in batch)

    fin_seed = []
    if ("filings" in suites and sec is not None) or (
        "filingdoc" in suites and edgar is not None and llm is not None
    ):
        fin_seed = tiered_companies(all_rows, max(1, max_companies // 3), seed)
    if "filings" in suites and sec is not None:
        rows.extend(
            await _filings_rows(
                fin_seed,
                sec,
                fields=fields,
                per_company=per_company,
                quarters_back=quarters_back,
                seed=seed,
                hour_ts=hour_ts,
                now=now,
                stats=stats,
            )
        )
    if "filingdoc" in suites and edgar is not None and llm is not None:
        rows.extend(
            await _filingdoc_rows(
                fin_seed,
                edgar,
                llm,
                target=filingdoc_target,
                seed=seed,
                hour_ts=hour_ts,
                doc_concurrency=doc_concurrency,
                stats=stats,
            )
        )

    unique = dedupe_by(rows, lambda row: row["query_id"])
    stats.rows = len(unique)
    return unique, stats
