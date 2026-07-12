import json
from datetime import UTC, datetime

from keenbench.findallmcp.models import Entity, Task, build_task_row, serialize_row
from keenbench.findallmcp.sources import (
    github_tasks,
    hn_tasks,
    launch_entities,
    launches_tasks,
    wikidata_tasks,
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


class FakeLaunches:
    def __init__(self, hits):
        self._hits = hits

    async def launches(self, *, since, until):
        return self._hits


class FakeWikidata:
    def __init__(self, people):
        self._people = people

    async def deaths(self, *, since, until, min_links):
        return [p for p in self._people if p["links"] >= min_links]


class FakeGithub:
    def __init__(self, repos):
        self._repos = repos

    async def repos(self, *, since, until, min_stars, per_page=100):
        matched = [r for r in self._repos if r["stars"] >= min_stars]
        return len(matched), matched[:per_page]


def test_launch_entities_split_and_alias():
    ents = launch_entities(
        [
            {"id": "1", "name": "Falcon 9 Block 5 | Transporter 17 (Dedicated SSO Rideshare)"},
            {"id": "2", "name": "Ariane 64 | Amazon Leo (LE-03)"},
            {"id": "3", "name": "Ariane 64 | Amazon Leo (LA-08)"},
        ]
    )
    assert ents[0].name == "Transporter 17 (Dedicated SSO Rideshare)"
    assert "Transporter 17" in ents[0].aliases
    assert all("Amazon Leo" not in e.aliases for e in ents[1:])


async def test_launches_tasks_gold_band_and_falcon_fraction():
    hits = [
        {
            "id": str(i),
            "name": f"Falcon 9 Block 5 | Starlink Group {i}"
            if i < 5
            else f"Rocket {i} | Mission {i}",
        }
        for i in range(20)
    ]
    tasks = await launches_tasks(FakeLaunches(hits), now=NOW)
    enum = [t for t in tasks if t.bucket == "enumerate"]
    assert len(enum) == 1
    assert len(enum[0].entities) == 20
    frac = next(t for t in tasks if "fraction" in t.prompt)
    assert frac.stat_value == 0.25
    count = next(t for t in tasks if "How many" in t.prompt)
    assert count.stat_value == 20.0


async def test_wikidata_tasks_pick_sitelink_threshold_in_gold_band():
    people = [
        {"qid": f"Q{i}", "name": f"Person Number {i}", "links": 45 if i < 3 else 22}
        for i in range(30)
    ]
    tasks = await wikidata_tasks(FakeWikidata(people), now=NOW)
    assert len(tasks) == 1
    assert len(tasks[0].entities) == 30
    assert "at least 20 languages" in tasks[0].prompt


async def test_wikidata_tasks_skip_when_out_of_band():
    people = [{"qid": f"Q{i}", "name": f"Person Number {i}", "links": 15} for i in range(100)]
    assert await wikidata_tasks(FakeWikidata(people), now=NOW) == []


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
