from keenbench.findallmcp.score import (
    names_match,
    norm_name,
    parse_answer,
    score_set,
    score_stat,
)


def test_parse_answer_handles_fences_and_prose():
    assert parse_answer('{"value": 0.3}') == {"value": 0.3}
    assert parse_answer('```json\n{"value": 1}\n```') == {"value": 1}
    assert parse_answer('The answer is {"items": []} hope that helps') == {"items": []}
    assert parse_answer("no json here") is None
    assert parse_answer(None) is None


def test_norm_name_strips_show_hn_and_suffixes():
    assert norm_name("Show HN: Bramble – Local-first password manager") == norm_name(
        "Bramble Local first password manager"
    )
    assert norm_name("TreeHouse Foods, Inc.") == "treehouse foods"


def test_names_match_requires_substance():
    assert names_match("treehouse foods", "treehouse foods")
    assert names_match("bramble local first password manager", "bramble local first")
    assert not names_match("abc", "abcdef")
    assert not names_match("", "anything")


GOLD_ENTITIES = (
    {
        "key": "1",
        "name": "Show HN: Bramble – Local-first password manager",
        "aliases": ["https://bramble.app/download"],
    },
    {"key": "2", "name": "Show HN: ZeroFS – A log-structured filesystem for S3", "aliases": []},
)


def test_score_set_matches_by_name_or_url():
    answer = {
        "items": [
            {"name": "Bramble local-first password manager", "url": "https://x.com"},
            {"name": "totally unrelated", "url": "https://bramble.app/"},
            {"name": "nothing", "url": ""},
        ]
    }
    detail = score_set(answer, GOLD_ENTITIES)
    assert detail["n_matched"] == 1
    assert detail["recall"] == 0.5
    assert detail["precision"] == 2 / 3


def test_score_set_empty_answer():
    detail = score_set(None, GOLD_ENTITIES)
    assert detail["recall"] == 0.0 and detail["n_returned"] == 0


def test_score_stat_tolerance():
    assert score_stat({"value": 0.2}, value=0.217, rel_tol=0.25)["within_tol"]
    assert not score_stat({"value": 0.05}, value=0.217, rel_tol=0.25)["within_tol"]
    assert not score_stat({"value": "n/a"}, value=1.0, rel_tol=0.25)["within_tol"]
    assert score_stat({"value": 60}, value=60.0, rel_tol=0.2)["rel_err"] == 0.0
