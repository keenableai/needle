import json
from collections import Counter
from collections.abc import Iterator

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from keenbench.rarestream.rare_entity import filter_rows, load_lid, load_tokenizer
from keenbench.shared.io import write_jsonl

DEFAULT_DATASET = "keenable-ai/keenbench-results"
DEFAULT_STREAM_PATH = "aql/queries.jsonl"


def _iter_rows(path: str) -> Iterator[dict]:
    if path.endswith(".parquet"):
        yield from pq.read_table(path).to_pylist()
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _write_rows(rows: list[dict], out: str) -> None:
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


class Rarestream:
    def filter(
        self,
        out: str = "aql_rare_entity.jsonl",
        queries: str | None = None,
        dataset: str = DEFAULT_DATASET,
        stream_path: str = DEFAULT_STREAM_PATH,
        query_field: str = "query",
        min_words: int = 3,
        max_query_len: int = 200,
        max_word_len: int = 40,
        subword_threshold: int = 5,
        dedup_ngram: int = 3,
        dedup_max: int = 2,
        any_language: bool = False,
        vocab: str | None = None,
        lid_model: str | None = None,
    ) -> None:
        if queries is None:
            queries = hf_hub_download(dataset, stream_path, repo_type="dataset")
        tokenize = load_tokenizer(vocab)
        lid = None if any_language else load_lid(lid_model)
        kept, stats = filter_rows(
            _iter_rows(queries),
            tokenize=tokenize,
            lid=lid,
            min_words=min_words,
            max_query_len=max_query_len,
            max_word_len=max_word_len,
            subword_threshold=subword_threshold,
            dedup_ngram=dedup_ngram,
            dedup_max=dedup_max,
            query_field=query_field,
        )
        _write_rows(kept, out)
        buckets = Counter(r["length_bucket"] for r in kept)
        print(f"input: {sum(stats.values()) + len(kept)} queries")
        print(f"rejected: {dict(stats)}")
        print(f"kept: {len(kept)} {dict(buckets)} -> {out}")
