from keenbench.agentic_rare.rare_entity import (
    filter_rows,
    hard_words_for,
    is_eligible,
    is_english,
    length_bucket,
    words_for,
)

VOCAB = {
    "how",
    "to",
    "fix",
    "red",
    "dead",
    "redemption",
    "the",
    "best",
    "tea",
    "in",
    "zone",
    "number",
}


def fake_tokenize(word: str) -> list[str]:
    if word in VOCAB:
        return [word]
    if word.isdigit():
        return [word[0], *(f"##{c}" for c in word[1:])]
    return ["[UNK]"]


def fake_lid_en(text: str) -> tuple[str, float]:
    return "en", 0.9


def fake_lid_de(text: str) -> tuple[str, float]:
    return "de", 0.95


def fake_lid_unsure(text: str) -> tuple[str, float]:
    return "fr", 0.2


def test_is_eligible_rejects_non_latin_and_identifiers():
    assert is_eligible("how to fix a sink")
    assert not is_eligible("медаль за боевые заслуги")
    assert not is_eligible("東京 天気")
    assert is_eligible("site:example.gov budget report")
    assert is_eligible('"exact phrase" search')
    assert not is_eligible("carfax 1HGCM82633A004352 history")
    assert not is_eligible("d41d8cd98f00b204e9800998ecf8427e checksum")
    assert not is_eligible("0x742d35Cc6634C0532925a3b844Bc454e4438f44e balance")
    assert not is_eligible("wallet 7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj balance")


def test_words_for_strips_punctuation_and_lowercases():
    assert words_for("Foo, Bar-Baz!") == ["foo", "bar", "baz"]


def test_hard_words_flags_unk_and_long_splits():
    hard = hard_words_for(words_for("how to fix kdeplasma"), fake_tokenize)
    assert [h["word"] for h in hard] == ["kdeplasma"]
    assert hard[0]["subwords"] == ["[UNK]"]
    assert hard_words_for(words_for("how to fix red"), fake_tokenize) == []
    assert hard_words_for(words_for("number 123456"), fake_tokenize) == []
    assert hard_words_for(words_for("51.504444,0.426876"), fake_tokenize) == []
    hard = hard_words_for(words_for("the fa507nur"), fake_tokenize)
    assert [h["word"] for h in hard] == ["fa507nur"]


def test_is_english_tiers():
    assert is_english("red dead redemption kdeplasma", ["red", "dead", "redemption"], fake_lid_en)
    assert not is_english("die optimale kiste", ["die", "optimale", "kiste"], fake_lid_de)
    assert is_english("best tea in zone frobnicat", ["best", "tea", "in", "zone"], fake_lid_unsure)
    assert not is_english("asintoto funzione", ["asintoto", "funzione"], fake_lid_unsure)
    assert is_english("a15 fa507nur", ["a15", "fa507nur"], fake_lid_unsure)


def test_length_bucket():
    assert length_bucket(2) == "short"
    assert length_bucket(5) == "medium"
    assert length_bucket(6) == "long"


def test_filter_rows_end_to_end():
    rows = [
        {"query": "how to fix kdeplasma", "providers": ["mojeek.com"]},
        {"query": "red dead redemption", "providers": ["mojeek.com"]},
        {"query": "kdeplasma", "providers": ["mojeek.com"]},
        {"query": "the best frobnicator tea in zone eight today", "providers": ["mojeek.com"]},
        {"query": "check www.example.com kdeplasma", "providers": ["mojeek.com"]},
    ]
    kept, stats = filter_rows(rows, tokenize=fake_tokenize, lid=fake_lid_en)
    queries = {r["query"] for r in kept}
    assert queries == {"how to fix kdeplasma", "the best frobnicator tea in zone eight today"}
    by_query = {r["query"]: r for r in kept}
    assert by_query["how to fix kdeplasma"]["length_bucket"] == "medium"
    assert by_query["the best frobnicator tea in zone eight today"]["length_bucket"] == "long"
    assert by_query["how to fix kdeplasma"]["hard_words"][0]["word"] == "kdeplasma"
    assert stats == {"no_rare_word": 1, "too_few_words": 1, "urlish": 1, "ngram_dup": 0}


def test_dedup_by_ngrams_collapses_templated_prefixes():
    from keenbench.agentic_rare.rare_entity import dedup_by_ngrams

    rows = [
        {"query": "regional europe united kingdom scotland aaa"},
        {"query": "regional europe united kingdom scotland bbb"},
        {"query": "regional europe united kingdom scotland ccc"},
        {"query": "how to make sourdough bread"},
    ]
    kept = dedup_by_ngrams(rows, n=4, max_per_gram=2)
    templated = [r for r in kept if r["query"].startswith("regional")]
    assert len(templated) == 2
    assert any("sourdough" in r["query"] for r in kept)


def test_filter_rows_drops_overlong_single_word():
    long_garbage = "a" + "mansaidwatt" * 6
    rows = [
        {"query": f"the {long_garbage} thing", "providers": []},
        {"query": "the fa507nur part", "providers": []},
    ]
    kept, stats = filter_rows(rows, tokenize=fake_tokenize, lid=None, max_word_len=40)
    assert [r["query"] for r in kept] == ["the fa507nur part"]
    assert stats["long_word"] == 1


def test_filter_rows_honors_custom_query_field():
    rows = [
        {"query_text": "how to fix kdeplasma", "source": "x"},
        {"query_text": "red dead redemption", "source": "x"},
    ]
    kept, _ = filter_rows(rows, tokenize=fake_tokenize, lid=None, query_field="query_text")
    assert [r["query_text"] for r in kept] == ["how to fix kdeplasma"]
    assert kept[0]["source"] == "x"
    assert kept[0]["hard_words"][0]["word"] == "kdeplasma"


def test_filter_rows_skips_lid_when_disabled():
    rows = [{"query": "die optimale kiste kdeplasma", "providers": []}]
    kept, _ = filter_rows(rows, tokenize=fake_tokenize, lid=None)
    assert len(kept) == 1
