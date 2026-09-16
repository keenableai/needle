import os

import httpx

DEFAULT_DATASET = "keenable-ai/needle-results"


def dataset_name(dataset: str | None) -> str:
    return dataset or os.environ.get("HF_DATASET", DEFAULT_DATASET)


def resolve_base(dataset: str | None) -> str:
    return f"https://huggingface.co/datasets/{dataset_name(dataset)}/resolve/main"


def fetch_report(client: httpx.Client, runs_base: str, run_id: str, artifact: str) -> dict:
    def get(path: str) -> dict:
        resp = client.get(f"{runs_base}/{run_id}/{path}")
        resp.raise_for_status()
        return resp.json()

    report = get(artifact)
    stem = artifact.removesuffix(".json")
    for name, e in report["engines"].items():
        if "per_query" not in e:
            e.update(get(f"{stem}/{name}.json"))
    return report
