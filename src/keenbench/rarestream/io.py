import json
from collections.abc import Iterator

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from keenbench.shared.io import write_jsonl


def resolve_dataset(queries: str | None, dataset: str, path: str) -> str:
    """A local --queries path if given, else the dataset file downloaded from HF."""
    if queries is not None:
        return queries
    return hf_hub_download(dataset, path, repo_type="dataset")


def iter_rows(path: str) -> Iterator[dict]:
    if path.endswith(".parquet"):
        # stream in batches so a multi-million-row source isn't fully materialized
        for batch in pq.ParquetFile(path).iter_batches():
            yield from batch.to_pylist()
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _cell(v: object) -> object:
    # parquet can't infer list/dict columns cleanly, so serialize non-scalars
    if v is None or isinstance(v, str | int | float | bool):
        return v
    return json.dumps(v, ensure_ascii=False)


def write_rows(rows: list[dict], out: str) -> None:
    if not out.endswith(".parquet"):
        write_jsonl(rows, out)
        return
    keys = list(rows[0].keys()) if rows else []
    columns = {k: [_cell(r.get(k)) for r in rows] for k in keys}
    pq.write_table(pa.table(columns), out, compression="zstd")
