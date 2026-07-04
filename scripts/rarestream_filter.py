"""Filter a query dataset down to English medium/long rare-entity queries.

Heavy producer step (bert-base-uncased WordPiece + fastText lid.176): reads a
jsonl or parquet dataset, keeps queries with at least one rare word, and writes
the filtered subset for publishing to the HF dataset. The keenbench CLI then
samples from that filtered artifact.

Usage: uv run python scripts/rarestream_filter.py --out rare_entity.parquet
           [--queries <local file>] [--stream-path agentic/queries.parquet]
           [--query-field query_text] [--subword-threshold 5] [--any-language]
"""

from collections import Counter

import fire
from huggingface_hub import hf_hub_download

from keenbench.rarestream.io import iter_rows, write_rows
from keenbench.rarestream.rare_entity import filter_rows, load_lid, load_tokenizer

DEFAULT_DATASET = "keenable-ai/keenbench-results"
DEFAULT_STREAM_PATH = "agentic/queries.parquet"
DEFAULT_QUERY_FIELD = "query_text"


def main(
    out: str = "rare_entity.parquet",
    queries: str | None = None,
    dataset: str = DEFAULT_DATASET,
    stream_path: str = DEFAULT_STREAM_PATH,
    query_field: str = DEFAULT_QUERY_FIELD,
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
        iter_rows(queries),
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
    write_rows(kept, out)
    buckets = Counter(r["length_bucket"] for r in kept)
    print(f"input: {sum(stats.values()) + len(kept)} queries")
    print(f"rejected: {dict(stats)}")
    print(f"kept: {len(kept)} {dict(buckets)} -> {out}")


if __name__ == "__main__":
    fire.Fire(main)
