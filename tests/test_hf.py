import json

import httpx

from needle.shared.hf import fetch_report

RUNS = "https://hf.test/runs"


def _client(files: dict[str, dict]) -> tuple[httpx.Client, list[str]]:
    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/runs/r1/")
        hits.append(path)
        return httpx.Response(200, text=json.dumps(files[path]))

    return httpx.Client(transport=httpx.MockTransport(handler)), hits


def test_fetch_report_merges_split_engines():
    client, hits = _client(
        {
            "ndcg.json": {
                "engines": {
                    "a": {"mean_ndcg": 0.5, "per_query_path": "ndcg/a.json"},
                    "b": {"mean_ndcg": 0.2, "per_query_path": "ndcg/b.json"},
                }
            },
            "ndcg/a.json": {"mean_ndcg": 0.5, "per_query": [{"query": "q"}]},
            "ndcg/b.json": {"mean_ndcg": 0.2, "per_query": []},
        }
    )
    report = fetch_report(client, RUNS, "r1", "ndcg.json")
    assert report["engines"]["a"]["per_query"] == [{"query": "q"}]
    assert "per_query_path" not in report["engines"]["a"]
    assert sorted(hits) == ["ndcg.json", "ndcg/a.json", "ndcg/b.json"]


def test_fetch_report_limit_and_legacy_full_file():
    client, hits = _client(
        {
            "ndcg.json": {
                "engines": {
                    "a": {"per_query_path": "ndcg/a.json"},
                    "b": {"per_query_path": "ndcg/b.json"},
                    "legacy": {"per_query": []},
                }
            },
            "ndcg/a.json": {"per_query": []},
        }
    )
    fetch_report(client, RUNS, "r1", "ndcg.json", limit=1)
    assert hits == ["ndcg.json", "ndcg/a.json"]
    hits.clear()
    fetch_report(client, RUNS, "r1", "ndcg.json", limit=0)
    assert hits == ["ndcg.json"]
