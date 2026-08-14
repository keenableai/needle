import json
from collections import Counter
from datetime import UTC, date, datetime

from keenbench.legal.generate import run_generate
from keenbench.legal.models import Case
from keenbench.legal.sources import month_windows, parse_search_case, walk_structure_sections
from keenbench.shared.io import serialize_row

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
HOUR = NOW.replace(minute=0)


PARTIES = [
    "Alvarez",
    "Brennan",
    "Calloway",
    "Dunmore",
    "Espinoza",
    "Fairbanks",
    "Galloway",
    "Hutchins",
    "Ibarra",
    "Jankowski",
    "Kowalski",
    "Lindqvist",
]


def _case(n: int, court: str = "ca9") -> Case:
    return Case(
        court_id=court,
        case_name=f"{PARTIES[(n - 1) % len(PARTIES)]} v. Riverbend Holdings",
        docket=f"25-{1000 + n}",
        citations=(f"{n} F.4th {n}",),
        date_filed=date(2026, 5, 1),
        cluster_id=n,
        absolute_url=f"/opinion/{n}/x/",
    )


class FakeCourtListener:
    def __init__(self, cases_by_court):
        self._by_court = cases_by_court

    async def opinions(self, court, *, filed_after, filed_before):
        return list(self._by_court.get(court, []))


class FakeEcfr:
    def __init__(self, sections, texts):
        self._sections = sections
        self._texts = texts

    async def sections(self, title_num, *, n, seed):
        return list(self._sections.get(title_num, []))[:n]

    async def section(self, title_num, part, identifier, heading):
        return self._texts.get((title_num, identifier))


class FakeLLM:
    def __init__(self, reply):
        self._reply = reply

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        return self._reply, None


async def test_caselaw_rows_cycle_syntaxes_and_dedupe():
    cases = [_case(n) for n in range(1, 13)]
    rows, stats = await run_generate(
        courtlistener=FakeCourtListener({"ca9": cases + cases}),
        ecfr=None,
        llm=None,
        hour_ts=HOUR,
        now=NOW,
        courts=("ca9",),
        per_court=12,
        months_back=1,
        titles=(),
        per_title=0,
        seed=0,
    )
    assert stats.caselaw_rows == 12
    syntaxes = Counter(json.loads(serialize_row(r)["query_origin"])["syntax"] for r in rows)
    assert syntaxes["plain"] == 6
    assert syntaxes["quoted"] == syntaxes["site"] == syntaxes["date"] == 2
    golds = [r["gold"] for r in rows]
    assert all(g["ids"]["cluster"] for g in golds)
    assert all(g["party_tokens"] for g in golds)


async def test_caselaw_selection_varies_with_seed():
    cases = [_case(n) for n in range(1, 13)]

    async def picked(seed):
        rows, _ = await run_generate(
            courtlistener=FakeCourtListener({"ca9": cases}),
            ecfr=None,
            llm=None,
            hour_ts=HOUR,
            now=NOW,
            courts=("ca9",),
            per_court=4,
            months_back=1,
            titles=(),
            per_title=0,
            seed=seed,
        )
        return {r["gold"]["case_key"] for r in rows}

    assert await picked(1) != await picked(2)


async def test_code_rows_project_and_gate():
    from keenbench.legal.models import CodeSection

    section = CodeSection(
        title_num=17,
        part="240",
        section="240.10b-5",
        heading="Employment of manipulative and deceptive devices.",
        text="It shall be unlawful to employ any device scheme or artifice to defraud investors.",
    )
    rows, stats = await run_generate(
        courtlistener=None,
        ecfr=FakeEcfr({17: [("240", "240.10b-5", "x")]}, {(17, "240.10b-5"): section}),
        llm=FakeLLM('securities fraud "artifice to defraud" liability'),
        hour_ts=HOUR,
        now=NOW,
        courts=(),
        per_court=0,
        months_back=1,
        titles=(17,),
        per_title=1,
        seed=0,
    )
    assert stats.code_rows == 1
    assert rows[0]["gold"]["ids"]["cfr"] == "17:240.10b-5"
    assert rows[0]["query_origin"]["bucket"] == "code"


async def test_code_rows_drop_leaky_queries():
    from keenbench.legal.models import CodeSection

    section = CodeSection(
        title_num=17,
        part="240",
        section="240.10b-5",
        heading="h",
        text="Some regulation text here about devices.",
    )
    rows, stats = await run_generate(
        courtlistener=None,
        ecfr=FakeEcfr({17: [("240", "240.10b-5", "x")]}, {(17, "240.10b-5"): section}),
        llm=FakeLLM('rule 10b-5 "devices" securities'),
        hour_ts=HOUR,
        now=NOW,
        courts=(),
        per_court=0,
        months_back=1,
        titles=(17,),
        per_title=1,
        seed=0,
    )
    assert stats.code_rows == 0
    assert stats.code_rejected == 1


def test_month_windows_are_contiguous():
    wins = month_windows(now=NOW, months_back=3)
    assert wins[0] == (date(2026, 6, 1), date(2026, 7, 1))
    assert wins[2] == (date(2026, 4, 1), date(2026, 5, 1))


def test_parse_search_case_requires_identity():
    rec = {
        "caseName": "A v. B",
        "docketNumber": "",
        "citation": [],
        "dateFiled": "2026-05-01",
        "cluster_id": 5,
        "court_id": "ca9",
        "absolute_url": "/opinion/5/a-v-b/",
    }
    assert parse_search_case(rec) is None
    rec["docketNumber"] = "25-123"
    case = parse_search_case(rec)
    assert case is not None and case.docket == "25-123"


def test_walk_structure_sections_skips_reserved():
    tree = {
        "type": "title",
        "children": [
            {
                "type": "part",
                "identifier": "240",
                "children": [
                    {
                        "type": "section",
                        "identifier": "240.10b-5",
                        "label_description": "Manipulative devices",
                    },
                    {"type": "section", "identifier": "240.10b-6", "reserved": True},
                ],
            }
        ],
    }
    assert walk_structure_sections(tree) == [("240", "240.10b-5", "Manipulative devices")]


async def test_code_llm_errors_counted_with_sample():
    from keenbench.legal.models import CodeSection

    class ErrLLM:
        async def complete(self, prompt, *, max_tokens, reasoning_effort):
            return None, {"error_type": "truncated", "error_message": "hit max_tokens"}

    section = CodeSection(
        title_num=17,
        part="240",
        section="240.10b-5",
        heading="Employment of manipulative and deceptive devices.",
        text="It shall be unlawful to employ any device scheme or artifice to defraud investors.",
    )
    rows, stats = await run_generate(
        courtlistener=None,
        ecfr=FakeEcfr({17: [("240", "240.10b-5", "x")]}, {(17, "240.10b-5"): section}),
        llm=ErrLLM(),
        hour_ts=HOUR,
        now=NOW,
        courts=(),
        per_court=0,
        months_back=1,
        titles=(17,),
        per_title=1,
        seed=0,
    )
    assert stats.code_rows == 0
    assert stats.llm_errors == 1
    assert stats.llm_error_sample == "truncated: hit max_tokens"
