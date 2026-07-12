import json
from datetime import UTC, datetime

from keenbench.findallmcp.models import Entity, Task, build_task_row, serialize_row
from keenbench.findallmcp.sources import (
    awards_tasks,
    cpsc_tasks,
    github_tasks,
    hn_tasks,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
HOUR = NOW.replace(minute=0)


class FakeHn:
    def __init__(self, posts):
        self._posts = posts

    async def show_hn(self, *, since, until):
        return self._posts


def _hit(n, points, title=None):
    return {
        "id": str(n),
        "title": title or f"Show HN: Tool number {n} for developers",
        "url": f"https://example{n}.com",
        "points": points,
    }


async def test_hn_tasks_pick_threshold_in_gold_band():
    hits = [_hit(i, 600 if i < 10 else 120) for i in range(40)]
    tasks = await hn_tasks(FakeHn(hits), now=NOW)
    enum = [t for t in tasks if t.bucket == "enumerate"]
    assert len(enum) == 1
    assert len(enum[0].entities) == 10
    stats = [t for t in tasks if t.bucket == "stat"]
    assert len(stats) == 2
    frac = next(t for t in stats if "fraction" in t.prompt)
    assert frac.stat_value == 1.0
    count = next(t for t in stats if "How many" in t.prompt)
    assert count.stat_value == 40.0


async def test_hn_tasks_skip_when_population_too_small():
    tasks = await hn_tasks(FakeHn([_hit(1, 900)]), now=NOW)
    assert tasks == []


class FakeCpsc:
    def __init__(self, recalls):
        self._recalls = recalls

    async def recalls(self, *, since, until):
        return [r for r in self._recalls if r["date"] >= since.isoformat()]


class FakeUsaspending:
    def __init__(self, awards):
        self._awards = awards

    async def awards(self, *, since, until, min_amount, limit=100):
        return [a for a in self._awards if a["amount"] >= min_amount][:limit]


class FakeGithub:
    def __init__(self, repos):
        self._repos = repos

    async def repos(self, *, since, until, min_stars, per_page=100):
        matched = [r for r in self._repos if r["stars"] >= min_stars]
        return len(matched), matched[:per_page]


def _recall(n, date, products=None):
    return {
        "number": str(n),
        "title": f"Acme Corp Recalls Widget Model {n} Due to Hazard",
        "date": date,
        "products": products if products is not None else [f"Acme Widget Model {n}"],
    }


async def test_cpsc_tasks_shrink_window_into_gold_band():
    recalls = [_recall(i, "2026-07-01") for i in range(30)] + [
        _recall(100 + i, "2026-06-10") for i in range(30)
    ]
    tasks = await cpsc_tasks(FakeCpsc(recalls), now=NOW)
    enum = [t for t in tasks if t.bucket == "enumerate"]
    assert len(enum) == 1
    assert len(enum[0].entities) == 30
    assert "between 2026-06-13" in enum[0].prompt
    assert enum[0].entities[0].name == "Acme Widget Model 0"
    assert enum[0].entities[0].aliases == ("Acme Corp Recalls Widget Model 0 Due to Hazard",)
    stat = next(t for t in tasks if t.bucket == "stat")
    assert stat.stat_value == 60.0


async def test_cpsc_tasks_skip_when_population_too_small():
    tasks = await cpsc_tasks(FakeCpsc([_recall(1, "2026-07-01")]), now=NOW)
    assert tasks == []


async def test_awards_tasks_descend_amount_ladder_and_dedupe_recipients():
    awards = [
        {
            "id": f"A{i}",
            "name": "Mega Contractor LLC" if i < 2 else f"Vendor {i} Inc",
            "amount": 2_500_000_000,
        }
        for i in range(3)
    ] + [{"id": f"B{i}", "name": f"Builder {i} Corp", "amount": 600_000_000} for i in range(9)]
    tasks = await awards_tasks(FakeUsaspending(awards), now=NOW)
    assert [t.bucket for t in tasks] == ["enumerate"]
    assert "at least $500 million" in tasks[0].prompt
    assert len(tasks[0].entities) == 11


async def test_github_tasks_descend_past_underfilled_thresholds():
    repos = [
        {
            "full_name": f"owner/project-{i}",
            "name": f"project-{i}",
            "stars": 6000 if i < 3 else 4000 if i < 20 else 400,
        }
        for i in range(80)
    ]
    tasks = await github_tasks(FakeGithub(repos), now=NOW)
    enum = [t for t in tasks if t.bucket == "enumerate"]
    assert len(enum) == 1
    assert len(enum[0].entities) == 20
    assert "at least 3000 stars" in enum[0].prompt
    stat = next(t for t in tasks if t.bucket == "stat")
    assert stat.stat_value == 80.0


def test_build_task_row_roundtrips_gold():
    task = Task(
        suite="hn",
        bucket="enumerate",
        prompt="Find ALL things",
        entities=(Entity(key="1", name="Thing One", aliases=("https://one.com",)),),
    )
    row = build_task_row(task, hour_ts=HOUR)
    assert row["gold"]["kind"] == "set"
    assert row["gold"]["entities"][0]["name"] == "Thing One"
    serialized = serialize_row(row)
    assert json.loads(serialized["gold"])["kind"] == "set"

    stat = Task(suite="hn", bucket="stat", prompt="How many", stat_value=42.0, stat_rel_tol=0.2)
    stat_row = build_task_row(stat, hour_ts=HOUR)
    assert stat_row["gold"] == {"kind": "stat", "value": 42.0, "rel_tol": 0.2}
