from collections import Counter

import fire

from keenbench.agentic_rare.io import iter_rows, resolve_dataset, write_rows
from keenbench.agentic_rare.rare_entity import filter_rows, load_lid, load_tokenizer

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
    tokenize = load_tokenizer(vocab)
    lid = None if any_language else load_lid(lid_model)
    kept, stats = filter_rows(
        iter_rows(resolve_dataset(queries, dataset, stream_path)),
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
