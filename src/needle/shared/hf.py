import os
from concurrent.futures import ThreadPoolExecutor

import httpx

DEFAULT_DATASET = "keenable-ai/needle-results"


def dataset_name(dataset: str | None) -> str:
    return dataset or os.environ.get("HF_DATASET", DEFAULT_DATASET)


def resolve_base(dataset: str | None) -> str:
    return f"https://huggingface.co/datasets/{dataset_name(dataset)}/resolve/main"


def fetch_report(
    client: httpx.Client, runs_base: str, run_id: str, artifact: str, limit: int | None = None
) -> dict:
    def get(path: str) -> dict:
        resp = client.get(f"{runs_base}/{run_id}/{path}")
        resp.raise_for_status()
        return resp.json()

    report = get(artifact)
    engines = report["engines"]
    split = [n for n in list(engines)[:limit] if "per_query_path" in engines[n]]
    with ThreadPoolExecutor(8) as pool:
        fetched = pool.map(lambda n: get(engines[n]["per_query_path"]), split)
        for name, e in zip(split, fetched, strict=True):
            engines[name] = e
    return report
