from datetime import date
from html.parser import HTMLParser

from keenbench.companyfill.registries import RegistryClient
from keenbench.finance.models import Filing, QuarterFact

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh_nodash}/{doc}"

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

SKIP_TAGS = {"script", "style", "svg", "noscript", "head", "title"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data)


def html_text(html: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
        extractor.close()
    except Exception:
        pass
    return " ".join(" ".join(extractor.parts).split())


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
        out = []
        for i, adsh in enumerate(accessions):
            form = (recent.get("form") or [""] * len(accessions))[i]
            if form not in forms:
                continue
            out.append(
                {
                    "adsh": adsh,
                    "form": form,
                    "filed": (recent.get("filingDate") or [""] * len(accessions))[i],
                    "primary_doc": (recent.get("primaryDocument") or [""] * len(accessions))[i],
                }
            )
            if len(out) >= limit:
                break
        return out

    async def document_text(self, filing: Filing) -> str | None:
        if not filing.primary_doc:
            return None
        url = SEC_DOC_URL.format(
            cik=filing.cik, adsh_nodash=filing.adsh_nodash, doc=filing.primary_doc
        )
        try:
            async with self._sem:
                resp = await self._http().request(
                    "GET", url, headers={"User-Agent": self.user_agent}, follow_redirects=True
                )
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        text = html_text(resp.text)
        return text or None
