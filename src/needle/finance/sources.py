import itertools
from datetime import date

from needle.finance.models import Filing, QuarterFact
from needle.finance.registries import RegistryClient
from needle.shared.htmltext import html_text

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

QUARTERLY_CONCEPTS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
}
CONCEPT_UNITS = {"eps_diluted": "USD/shares"}
QUARTER_FPS = frozenset({"Q1", "Q2", "Q3"})


def quarterly_facts(facts: dict, field: str) -> list[QuarterFact]:
    unit = CONCEPT_UNITS.get(field, "USD")
    best: dict[tuple[int, str], QuarterFact] = {}
    for concept in QUARTERLY_CONCEPTS[field]:
        for fact in ((facts.get(concept, {}) or {}).get("units", {}) or {}).get(unit, []):
            fp = fact.get("fp")
            fy = fact.get("fy")
            val = fact.get("val")
            end = fact.get("end")
            start = fact.get("start")
            if fact.get("form") != "10-Q" or fp not in QUARTER_FPS or not fy or not end:
                continue
            if val is None or not start:
                continue
            span_days = _span_days(start, end)
            if span_days is None or not 70 <= span_days <= 110:
                continue
            key = (int(fy), str(fp))
            if key not in best or end > best[key].end:
                best[key] = QuarterFact(
                    field=field, value=float(val), fy=int(fy), fp=str(fp), end=str(end)
                )
        if best:
            break
    return sorted(best.values(), key=lambda f: f.end, reverse=True)


def _span_days(start: str, end: str) -> int | None:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


class EdgarClient(RegistryClient):
    async def filings(self, cik: int, *, forms: frozenset[str], limit: int = 40) -> list[dict]:
        payload = await self._get(SEC_SUBMISSIONS_URL.format(cik=int(cik)))
        recent = ((payload or {}).get("filings") or {}).get("recent") or {}
        accessions = recent.get("accessionNumber") or []
        matched = (
            {"adsh": adsh, "form": form, "filed": filed, "primary_doc": doc}
            for adsh, form, filed, doc in itertools.zip_longest(
                accessions,
                recent.get("form") or (),
                recent.get("filingDate") or (),
                recent.get("primaryDocument") or (),
                fillvalue="",
            )
            if adsh and form in forms
        )
        return list(itertools.islice(matched, limit))

    async def document_text(self, filing: Filing) -> str | None:
        if not filing.primary_doc:
            return None
        html = await self._get_text(filing.doc_url)
        if html is None:
            return None
        return html_text(html) or None
