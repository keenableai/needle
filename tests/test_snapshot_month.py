import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from needle.shared.overlap import TS_FMT

SPEC = importlib.util.spec_from_file_location(
    "snapshot_month", Path(__file__).parents[1] / "scripts" / "snapshot_month.py"
)
assert SPEC and SPEC.loader
snapshot_month = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot_month)


def test_bench_timestamps_match_publish_bench():
    assert snapshot_month.TS_FMT == TS_FMT


def test_month_end_is_the_next_month_start():
    assert snapshot_month.month_end("2026-10") == datetime(2026, 11, 1, tzinfo=UTC)
    assert snapshot_month.month_end("2026-12") == datetime(2027, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "October"])
def test_month_end_rejects_bad_months(month):
    with pytest.raises(SystemExit):
        snapshot_month.month_end(month)


def test_end_of_month_state_keeps_fixes_made_before_the_next_month_runs():
    log = [
        ("h5", "h4", "history: 2026-10 snapshot"),
        ("h4", "h3", "bench: 2026-11-01T01:31Z"),
        ("h3", "h2", "bench: 2026-11-01T00:40Z"),
        ("h2", "h1", "data: drop Exa rows from an outage"),
        ("h1", "h0", "bench: 2026-10-31T23:43Z"),
        ("h0", "", "bench: 2026-10-31T22:46Z"),
    ]
    assert snapshot_month.end_of_month_commit(log, "2026-11-01T00:00Z") == "h2"


def test_end_of_month_state_is_head_without_later_runs():
    log = [("h1", "h0", "bench: 2026-10-31T23:43Z"), ("h0", "", "bench: 2026-10-31T22:46Z")]
    assert snapshot_month.end_of_month_commit(log, "2026-11-01T00:00Z") == "h1"


def test_end_of_month_state_needs_a_run_inside_the_month():
    log = [("h1", "h0", "bench: 2026-11-01T00:40Z"), ("h0", "", "data: seed")]
    with pytest.raises(SystemExit):
        snapshot_month.end_of_month_commit(log, "2026-11-01T00:00Z")


def _built(tmp_path: Path, text: str) -> Path:
    out = tmp_path / "built"
    for src in snapshot_month.FILES:
        (out / src).parent.mkdir(parents=True, exist_ok=True)
        (out / src).write_text(text)
    return out


def test_store_writes_every_file_under_the_month_name(tmp_path):
    out = _built(tmp_path, "october")
    snapshot_month.store(str(tmp_path / "site"), str(out), "2026-10")
    assert sorted(p.name for p in (tmp_path / "site" / "history").iterdir()) == [
        "needle-overall-2026-10.png",
        "needle-overall-2026-10.webp",
        "needle-results-2026-10.csv",
        "needle-results-2026-10.json",
        "needle-results-2026-10.md",
    ]


def test_store_never_overwrites_a_saved_month(tmp_path):
    site = tmp_path / "site"
    (site / "history").mkdir(parents=True)
    saved = site / "history" / "needle-results-2026-10.json"
    saved.write_text("first")
    snapshot_month.store(str(site), str(_built(tmp_path, "second")), "2026-10")
    assert saved.read_text() == "first"
    assert sorted(p.name for p in (site / "history").iterdir()) == ["needle-results-2026-10.json"]


def test_store_fails_on_an_incomplete_build(tmp_path):
    out = _built(tmp_path, "october")
    (out / "og" / "needle-overall.webp").unlink()
    with pytest.raises(SystemExit, match="needle-overall.webp"):
        snapshot_month.store(str(tmp_path / "site"), str(out), "2026-10")
    assert not (tmp_path / "site" / "history").exists()


def test_build_refuses_a_month_that_is_not_over(tmp_path):
    month = f"{datetime.now(UTC):%Y-%m}"
    with pytest.raises(SystemExit, match="not over"):
        snapshot_month.build(str(tmp_path), str(tmp_path / "out"), month)
