import json
from collections.abc import Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from keenbench.shared.io import write_jsonl


def iter_rows(path: str) -> Iterator[dict]:
    if path.endswith(".parquet"):
        yield from pq.read_table(path).to_pylist()
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_rows(rows: list[dict], out: str) -> None:
    if not out.endswith(".parquet"):
        write_jsonl(rows, out)
        return
    keys = list(rows[0].keys()) if rows else []
    columns: dict[str, list] = {k: [] for k in keys}
    for r in rows:
        for k in keys:
            v = r.get(k)
            columns[k].append(json.dumps(v, ensure_ascii=False) if k == "hard_words" else v)
    pq.write_table(pa.table(columns), out, compression="zstd")
