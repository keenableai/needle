import os

DEFAULT_DATASET = "keenable-ai/needle-results"


def dataset_name(dataset: str | None) -> str:
    return dataset or os.environ.get("HF_DATASET", DEFAULT_DATASET)


def resolve_base(dataset: str | None) -> str:
    return f"https://huggingface.co/datasets/{dataset_name(dataset)}/resolve/main"
