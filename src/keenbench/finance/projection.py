import re
from datetime import date, timedelta

from keenbench.finance.models import (
    QUARTERLY_FIELDS,
    Filing,
    QuarterFact,
    display_name,
    quarter_phrase,
)
from keenbench.shared.prompts import render_prompt

FILING_QUERY_TEMPLATE = "filing_query.jinja"
DOC_EXCERPT_OFFSET = 1500
DOC_EXCERPT_CHARS = 8000
MIN_DOC_CHARS = 3000
MIN_QUERY_WORDS = 3
FILINGDOC_SITE = "sec.gov"
DATE_WINDOW_DAYS = 45

QUOTED_SPAN_RE = re.compile(r'"([^"]+)"')
ADSH_RE = re.compile(r"\d{10}-?\d{2}-?\d{6}")


def filings_query(company_title: str, fact: QuarterFact, syntax: str) -> str:
    name = display_name(company_title)
    spec = QUARTERLY_FIELDS[fact.field]
    if syntax == "quoted":
        return spec.template.format(name=f'"{name}"', quarter=quarter_phrase(fact))
    return spec.template.format(name=name, quarter=quarter_phrase(fact))


def doc_excerpt(text: str) -> str:
    if len(text) <= DOC_EXCERPT_OFFSET + DOC_EXCERPT_CHARS:
        return text[-DOC_EXCERPT_CHARS:]
    return text[DOC_EXCERPT_OFFSET : DOC_EXCERPT_OFFSET + DOC_EXCERPT_CHARS]


def build_filingdoc_prompt(filing: Filing, text: str) -> str:
    return render_prompt(
        "keenbench.finance",
        FILING_QUERY_TEMPLATE,
        company=filing.company,
        form=filing.form,
        filed=filing.filed,
        text=doc_excerpt(text),
    )


def clean_filingdoc_query(text: str | None) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    cleaned = text.splitlines()[0].strip().strip("'").strip()
    if not cleaned or "NO_DISTINCT_QUERY" in cleaned.upper():
        return None
    return cleaned


def filingdoc_query_ok(query: str, *, filing: Filing, text: str) -> bool:
    if len(query.split()) < MIN_QUERY_WORDS:
        return False
    if ADSH_RE.search(query):
        return False
    spans = QUOTED_SPAN_RE.findall(query)
    if len(spans) != 1:
        return False
    span_words = spans[0].split()
    if not 2 <= len(span_words) <= 8:
        return False
    return " ".join(spans[0].lower().split()) in " ".join(text.lower().split())


def filingdoc_syntax_query(base: str, syntax: str, *, filed: str) -> str:
    if syntax == "quoted":
        return base
    stripped = " ".join(base.replace('"', " ").split())
    if syntax == "site":
        return f"{stripped} site:{FILINGDOC_SITE}"
    if syntax == "date":
        try:
            filed_date = date.fromisoformat(filed)
        except ValueError:
            return stripped
        after = filed_date - timedelta(days=DATE_WINDOW_DAYS)
        before = filed_date + timedelta(days=DATE_WINDOW_DAYS)
        return f"{stripped} after:{after.isoformat()} before:{before.isoformat()}"
    return stripped
