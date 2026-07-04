import sys

from huggingface_hub import hf_hub_download

from keenbench.rarestream.io import iter_rows, write_rows
from keenbench.shared.sampling import sample

DEFAULT_DATASET = "keenable-ai/keenbench-results"
DEFAULT_FILTERED_PATH = "agentic/rare_entity.parquet"


class Rarestream:
    def generate(
        self,
        out: str = "-",
        n: int = 100,
        queries: str | None = None,
        dataset: str = DEFAULT_DATASET,
        filtered_path: str = DEFAULT_FILTERED_PATH,
        seed: int = 0,
        strategy: str = "uniform",
        by: str = "length_bucket",
    ) -> None:
        if queries is None:
            queries = hf_hub_download(dataset, filtered_path, repo_type="dataset")
        rows = list(iter_rows(queries))
        picked = sample(rows, n, seed, strategy=strategy, key=by)
        write_rows(picked, out)
        print(
            f"rarestream: {len(picked)} queries sampled from {len(rows)} ({strategy})",
            file=sys.stderr,
        )
