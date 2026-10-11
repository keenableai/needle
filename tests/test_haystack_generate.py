import json
from dataclasses import dataclass
from datetime import UTC, datetime

from needle.haystack.generate import run_generate
from needle.haystack.projection import HEAD_CHARS
from needle.shared.io import serialize_row

HOUR = datetime(2026, 10, 1, 12, tzinfo=UTC)

DEEP_FACT = "the keelhauler sonar array ran without fault for nine seasons "
LONG_TEXT = "intro filler words here " * 200 + "x " * (HEAD_CHARS // 2) + DEEP_FACT * 600
REPLY = (
    "entity || keelhauler sonar array || "
    "which instrument did the acme expedition rely on to chart the deep ocean floor"
)


class FakeLLM:
    def __init__(self, reply=REPLY):
        self._reply = reply
        self.calls = 0

    async def complete(self, prompt, **kwargs):
        self.calls += 1
        return self._reply.replace("deep ocean floor", f"deep ocean floor zone {self.calls}"), None


class FakeFR:
    def __init__(self, n=12, text=LONG_TEXT):
        self._text = text
        self.rules_list = [
            {
                "title": f"Rule {i}",
                "document_number": f"2026-0{i:04d}",
                "publication_date": "2026-09-01",
                "html_url": f"https://www.federalregister.gov/d/{i}",
                "raw_text_url": f"https://www.federalregister.gov/raw/{i}",
                "agency_names": ["EPA"],
            }
            for i in range(n)
        ]

    async def rules(self, **kwargs):
        return self.rules_list

    async def document_text(self, raw_text_url):
        return self._text


class FakeWiki:
    def __init__(self, n=12, text=LONG_TEXT):
        self._text = text
        self.titles = [f"Article {i}" for i in range(n)]

    async def featured_titles(self, **kwargs):
        return self.titles

    async def extract(self, title):
        return title, self._text


class FakeSec:
    def __init__(self, n=12):
        self._rows = [
            {"cik": 1000 + i, "ticker": f"T{i}", "title": f"Company {i}"} for i in range(n)
        ]

    async def tickers(self, _):
        return self._rows


class FakeEdgar:
    def __init__(self, text=LONG_TEXT):
        self._text = text

    async def filings(self, cik, *, forms, limit=40):
        return [
            {
                "adsh": f"{cik:010d}-26-000001",
                "form": "10-K",
                "filed": "2026-03-01",
                "primary_doc": "x.htm",
            }
        ]

    async def document_text(self, filing):
        return self._text


@dataclass(frozen=True)
class FakePaper:
    arxiv_id: str
    title: str
    url: str
    published: datetime
    domain: str


class FakeArxiv:
    def __init__(self, per_domain=3, text=LONG_TEXT):
        self._per_domain = per_domain
        self._text = text

    async def search_domain(self, domain, *, from_date, to_date, max_results=100):
        return [
            FakePaper(
                arxiv_id=f"2610.{hash(domain) % 10000:05d}{i}"[:10],
                title=f"{domain} paper {i}",
                url=f"https://arxiv.org/abs/2610.0{i}{abs(hash(domain)) % 100:02d}",
                published=datetime(2026, 9, 20, tzinfo=UTC),
                domain=domain,
            )
            for i in range(self._per_domain)
        ]

    async def body(self, arxiv_id):
        return self._text


async def _generate(**kwargs):
    defaults = {
        "fr": None,
        "wiki": None,
        "sec": None,
        "edgar": None,
        "arxiv": None,
        "llm": FakeLLM(),
        "suites": ("gov",),
        "hour_ts": HOUR,
        "now": HOUR,
        "per_suite": 4,
        "oversample": 3,
        "seed": 0,
        "doc_concurrency": 4,
    }
    defaults.update(kwargs)
    return await run_generate(**defaults)


async def test_gov_rows_shape_and_syntax_cycle():
    rows, stats = await _generate(fr=FakeFR())
    assert stats.by_suite == {"gov": 4}
    assert stats.candidates == 12
    assert stats.surplus == 8
    assert [r["query_origin"]["syntax"] for r in rows] == ["plain", "site", "plain", "date"]
    r = rows[0]
    assert r["query_source"] == "haystack"
    assert r["query_origin"]["bucket"] == "gov"
    assert r["gold"]["field"] == "haystack"
    assert r["gold"]["field_type"] == "entity"
    assert r["gold"]["value"] == "keelhauler sonar array"
    prov = r["query_origin"]["provenance"]
    assert prov["depth_pct"] >= 55
    assert prov["document_number"].startswith("2026-")
    assert "site:federalregister.gov" in rows[1]["query_text"]
    assert "after:" in rows[3]["query_text"]
    json.loads(serialize_row(r, fields=("query_origin",))["query_origin"])


async def test_all_suites_and_provenance_keys():
    rows, stats = await _generate(
        fr=FakeFR(),
        wiki=FakeWiki(),
        sec=FakeSec(),
        edgar=FakeEdgar(),
        arxiv=FakeArxiv(),
        suites=("gov", "sec", "wiki", "arxiv"),
        per_suite=2,
    )
    assert stats.by_suite == {"gov": 2, "sec": 2, "wiki": 2, "arxiv": 2}
    by_bucket = {r["query_origin"]["bucket"]: r for r in rows}
    assert by_bucket["sec"]["query_origin"]["provenance"]["form"] == "10-K"
    assert by_bucket["wiki"]["query_origin"]["provenance"]["wiki_title"].startswith("Article")
    assert by_bucket["arxiv"]["query_origin"]["provenance"]["arxiv_id"]
    assert "site:" not in " ".join(
        r["query_text"]
        for r in rows
        if r["query_origin"]["bucket"] == "wiki" and r["query_origin"]["syntax"] == "plain"
    )


async def test_suite_subsetting_skips_missing_clients():
    rows, stats = await _generate(fr=FakeFR(), suites=("gov", "wiki"))
    assert stats.by_suite == {"gov": 4}
    assert all(r["query_origin"]["bucket"] == "gov" for r in rows)


async def test_drop_stats_counted():
    class ThinFR(FakeFR):
        async def document_text(self, raw_text_url):
            return "too short"

    rows, stats = await _generate(fr=ThinFR())
    assert rows == []
    assert stats.thin == 12

    class FailFR(FakeFR):
        async def document_text(self, raw_text_url):
            return None

    rows, stats = await _generate(fr=FailFR())
    assert rows == [] and stats.fetch_fail == 12

    rows, stats = await _generate(fr=FakeFR(), llm=FakeLLM("NO_DEEP_FACT"))
    assert rows == [] and stats.no_question == 12

    rows, stats = await _generate(
        fr=FakeFR(), llm=FakeLLM("entity || not in excerpt || " + "w " * 8)
    )
    assert rows == [] and stats.rejected == 12

    class BoomLLM(FakeLLM):
        async def complete(self, prompt, **kwargs):
            return None, {"error_type": "http_error", "error_message": "500"}

    rows, stats = await _generate(fr=FakeFR(), llm=BoomLLM())
    assert rows == [] and stats.llm_errors == 12


async def test_rows_deduped_by_query_id():
    fr = FakeFR()
    for rule in fr.rules_list:
        rule["raw_text_url"] = fr.rules_list[0]["raw_text_url"]
        rule["html_url"] = fr.rules_list[0]["html_url"]
    rows, _ = await _generate(fr=fr)
    assert len(rows) == len({r["query_id"] for r in rows})


async def test_seed_changes_candidate_pick():
    fr = FakeFR(n=40)
    rows_a, _ = await _generate(fr=fr, per_suite=2, oversample=1, seed=1)
    rows_b, _ = await _generate(fr=fr, per_suite=2, oversample=1, seed=2)
    a = {r["query_origin"]["provenance"]["source_url"] for r in rows_a}
    b = {r["query_origin"]["provenance"]["source_url"] for r in rows_b}
    assert a != b
