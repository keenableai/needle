import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def analysis(monkeypatch):
    directory = Path(__file__).parents[1] / "paper" / "analysis"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("scholar_paired", directory / "scholar_paired.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("common", None)


def test_collect_keeps_common_papers_and_service_failures(analysis, tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    queries = [
        {"query_text": f"{paper}-{bucket}", "gold": json.dumps({"paper_key": paper}),
         "query_origin": json.dumps({"bucket": bucket})}
        for paper in ("a", "b") for bucket in analysis.BUCKETS
    ]
    (run / "scholar.jsonl").write_text("".join(json.dumps(q) + "\n" for q in queries))
    report = {"engines": {e: {"per_query_path": f"{e}.json"} for e in analysis.ENGINES}}
    (run / "scholar.json").write_text(json.dumps(report))
    for engine in analysis.ENGINES:
        rows = [{"query": q["query_text"], "search_error": None, "hit_rank": 1} for q in queries]
        if engine == "exa":
            rows[0].update(search_error={"error_type": "http_error", "error_message": "401: Unauthorized"}, hit_rank=None)
            rows[5].update(search_error={"error_type": "http_error", "error_message": "503: overloaded"}, hit_rank=None)
        (run / f"{engine}.json").write_text(json.dumps({"per_query": rows}))
    result = analysis.collect(tmp_path)
    assert len(result) == 1
    assert result[0]["paper"] == "b"
    assert result[0]["hits"][3] == [1, 0, 1, 1]


def test_constant_paired_difference(analysis):
    rows = [{"run": str(i), "paper": str(i), "hits": [[1, 0, 1, 0]] * 5} for i in range(3)]
    result = analysis.summarize(rows, samples=20)
    assert result["runs"] == 3
    assert result["paper_runs"] == 3
    assert result["query_runs"] == 12
    assert result["contrasts"]["keenable:body-title"] == {"mean": -1, "lo": -1, "hi": -1}
    assert result["contrasts"]["keenable-exa:body"] == {"mean": 0, "lo": 0, "hi": 0}


def test_paired_mean_weights_papers_not_runs(analysis):
    rows = [
        {"run": "a", "paper": "1", "hits": [[1, 0, 0, 0]] * 5},
        {"run": "b", "paper": "2", "hits": [[1, 1, 1, 1]] * 5},
        {"run": "b", "paper": "3", "hits": [[1, 1, 1, 1]] * 5},
    ]
    result = analysis.summarize(rows, samples=20)
    assert result["contrasts"]["keenable:body-title"]["mean"] == pytest.approx(-1 / 3)
    assert result == analysis.summarize(rows, samples=20)
