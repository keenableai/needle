import json
from collections import Counter
from pathlib import Path

from keenbench.rarestream.rare_entity import filter_rows, load_lid, load_tokenizer
from keenbench.shared.io import write_jsonl

DEFAULT_DATASET = "keenable-ai/keenbench-results"
DEFAULT_STREAM_PATH = "aql/queries.jsonl"


def _load_rows(path: str) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


class Rarestream:
    def filter(
        self,
        out: str = "aql_rare_entity.jsonl",
        queries: str | None = None,
        dataset: str = DEFAULT_DATASET,
        stream_path: str = DEFAULT_STREAM_PATH,
        min_words: int = 3,
        max_query_len: int = 200,
        any_language: bool = False,
        vocab: str | None = None,
        lid_model: str | None = None,
    ) -> None:
        if queries is None:
            from huggingface_hub import hf_hub_download

            queries = hf_hub_download(dataset, stream_path, repo_type="dataset")
        rows = _load_rows(queries)
        tokenize = load_tokenizer(vocab)
        lid = None if any_language else load_lid(lid_model)
        kept, stats = filter_rows(
            rows,
            tokenize=tokenize,
            lid=lid,
            min_words=min_words,
            max_query_len=max_query_len,
        )
        write_jsonl(kept, out)
        buckets = Counter(r["length_bucket"] for r in kept)
        print(f"input: {len(rows)} queries")
        print(f"rejected: {dict(stats)}")
        print(f"kept: {len(kept)} {dict(buckets)} -> {out}")
