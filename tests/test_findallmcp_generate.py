import json
from datetime import UTC, datetime

from keenbench.findallmcp.models import Entity, Task, build_task_row, serialize_row
from keenbench.findallmcp.sources import hn_tasks

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
