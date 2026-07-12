from datetime import UTC, datetime, timedelta

import pytest

from keenbench.scholar.generate import (
    ARXIV_DOMAINS,
    MAX_SUBWINDOWS,
    _subwindow_count,
    _subwindows,
    run_generate,
)
from keenbench.scholar.models import Paper


def test_subwindow_count_capped_by_bucket_span_days():
    assert _subwindow_count("7d", 21) == 7


def test_subwindow_count_one_window_per_candidate():
    assert _subwindow_count("1y", 21) == 21


def test_subwindow_count_capped_at_max_subwindows():
    assert _subwindow_count("1y", 40) == MAX_SUBWINDOWS


def test_subwindows_span_the_bucket_range():
    now = datetime(2026, 7, 2, tzinfo=UTC)
    wins = _subwindows("1y", now=now, count=6)
    assert len(wins) == 6
    for fr, to in wins:
        assert fr < to
    assert min(w[0] for w in wins) == (now - timedelta(days=364)).date().isoformat()
    assert max(w[1] for w in wins) == (now - timedelta(days=31)).date().isoformat()


def test_subwindows_contiguous_newest_first():
    wins = _subwindows("1y", now=datetime(2026, 7, 2, tzinfo=UTC), count=6)
    for newer, older in zip(wins, wins[1:], strict=False):
        assert newer[0] == older[1]


NOW = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
HOUR = NOW.replace(minute=0)


def _paper(n: int, domain: str, published: datetime) -> Paper:
    return Paper(
        suite="arxiv",
        title=f"Sparse Quantization Techniques for Transformer Number {n}",
        abstract="We study quantization of transformer weights for efficiency.",
        published=published,
        url=f"https://arxiv.org/abs/2607.{n:05d}",
        domain=domain,
        arxiv_id=f"2607.{n:05d}",
        doi=None,
    )


class FakeArxiv:
    def __init__(self, by_domain, bodies):
        self._by_domain = by_domain
        self._bodies = bodies
        self.body_calls = 0
        self.max_results_seen = []

    async def search_domain(self, domain, *, from_date, to_date, max_results):
        self.max_results_seen.append(max_results)
        return list(self._by_domain.get(domain, []))

    async def body(self, arxiv_id):
        self.body_calls += 1
        return self._bodies.get(arxiv_id)


class FakeLLM:
    def __init__(self, reply_for):
        self._reply_for = reply_for

    async def complete(self, prompt, *, max_tokens, reasoning_effort):
        for key, reply in self._reply_for.items():
            if key in prompt:
                if isinstance(reply, Exception):
                    raise reply
                return reply, None
        return "NO_DISTINCT_QUERY", None


async def _run(fake_arxiv, llm, *, age_buckets=("7d",), per_cell=2, seed=0):
    return await run_generate(
        arxiv=fake_arxiv,
        europepmc=None,
        llm=llm,
        hour_ts=HOUR,
        now=NOW,
        age_buckets=age_buckets,
        per_cell=per_cell,
        seed=seed,
    )


async def test_paired_rows_are_50_50():
    papers = [_paper(i, "computer science", datetime(2026, 7, 1, tzinfo=UTC)) for i in range(4)]
    bodies = {p.arxiv_id: f"body {p.arxiv_id}" for p in papers}
    arxiv = FakeArxiv({"computer science": papers}, bodies)
    llm = FakeLLM({p.arxiv_id: f"distinct anchor beta {p.arxiv_id}" for p in papers})
    rows, stats = await _run(arxiv, llm, per_cell=2)
    assert stats.title_rows == stats.body_rows == 2
    assert stats.papers == 2
    buckets = [r["query_origin"]["bucket"] for r in rows]
    assert buckets.count("title") == buckets.count("body") == 2
    keys_title = {r["gold"]["paper_key"] for r in rows if r["query_origin"]["bucket"] == "title"}
    keys_body = {r["gold"]["paper_key"] for r in rows if r["query_origin"]["bucket"] == "body"}
    assert keys_title == keys_body


async def test_paper_dropped_when_body_fails():
    papers = [_paper(i, "computer science", datetime(2026, 7, 1, tzinfo=UTC)) for i in range(3)]
    bodies = {p.arxiv_id: f"body {p.arxiv_id}" for p in papers[:2]}
    arxiv = FakeArxiv({"computer science": papers}, bodies)
    llm = FakeLLM({p.arxiv_id: f"distinct anchor beta {p.arxiv_id}" for p in papers})
    rows, stats = await _run(arxiv, llm, per_cell=5)
    assert stats.papers == 2
    assert stats.body_fetch_fail == 1
    assert stats.title_rows == stats.body_rows == 2


async def test_leak_and_no_query_drop_the_paper():
    papers = [_paper(i, "computer science", datetime(2026, 7, 1, tzinfo=UTC)) for i in range(3)]
    bodies = {p.arxiv_id: f"body {p.arxiv_id}" for p in papers}
    arxiv = FakeArxiv({"computer science": papers}, bodies)
    query_of_title_tokens_only = "sparse quantization transformer"
    llm = FakeLLM(
        {
            "body 2607.00000": "distinct anchor beta gamma",
            "body 2607.00001": query_of_title_tokens_only,
            "body 2607.00002": "NO_DISTINCT_QUERY",
        }
    )
    rows, stats = await _run(arxiv, llm, per_cell=5)
    assert stats.papers == 1
    assert stats.body_leak_rejected == 1
    assert stats.body_no_query == 1


async def test_paper_without_matchable_ids_dropped():
    good = _paper(0, "computer science", datetime(2026, 7, 1, tzinfo=UTC))
    noids = Paper(
        suite="arxiv",
        title="A Perfectly Long Enough Title Without Any Identifiers",
        abstract="abstract text",
        published=datetime(2026, 7, 1, tzinfo=UTC),
        url="https://example.org/no-ids",
        domain="computer science",
    )
    arxiv = FakeArxiv({"computer science": [good, noids]}, {good.arxiv_id: f"body {good.arxiv_id}"})
    llm = FakeLLM({f"body {good.arxiv_id}": "distinct anchor beta gamma"})
    rows, stats = await _run(arxiv, llm, per_cell=5)
    assert stats.papers == 1
    assert all(r["gold"]["ids"] for r in rows)


async def test_window_selection_varies_with_seed():
    papers = [_paper(i, "computer science", datetime(2026, 7, 1, tzinfo=UTC)) for i in range(40)]
    bodies = {p.arxiv_id: f"body {p.arxiv_id}" for p in papers}
    llm = FakeLLM({p.arxiv_id: f"distinct anchor beta {p.arxiv_id}" for p in papers})

    async def keys(seed):
        arxiv = FakeArxiv({"computer science": papers}, bodies)
        rows, _ = await _run(arxiv, llm, per_cell=2, seed=seed)
        return {r["gold"]["paper_key"] for r in rows}

    assert await keys(1) != await keys(2)


async def test_arxiv_fetch_size_is_clamped():
    arxiv = FakeArxiv({}, {})
    llm = FakeLLM({})
    await _run(arxiv, llm, per_cell=200)
    assert arxiv.max_results_seen
    assert max(arxiv.max_results_seen) == 1000


async def test_short_cell_reported():
    papers = [_paper(0, "computer science", datetime(2026, 7, 1, tzinfo=UTC))]
    arxiv = FakeArxiv({"computer science": papers}, {"2607.00000": "body 2607.00000"})
    llm = FakeLLM({"body 2607.00000": "distinct anchor beta gamma"})
    _, stats = await _run(arxiv, llm, per_cell=5)
    assert stats.papers == 1
    assert stats.short_cells == len(ARXIV_DOMAINS)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
