import json

from keenbench.scholar.cli import _gold_ok, _gold_paper
from keenbench.shared.cli import load_gold_rows


def _load_gold_rows(path):
    return load_gold_rows(path, bench="scholar", gold_ok=_gold_ok)


def _row(**over):
    r = {
        "query_text": "q",
        "query_origin": json.dumps({"bucket": "title", "suite": "arxiv"}),
        "gold": json.dumps(
            {"ids": {"arxiv": "2606.1"}, "paper_key": "2606.1", "age_bucket": "7d", "domain": "cs"}
        ),
    }
    r.update(over)
    return r


def _write(tmp_path, rows):
    p = tmp_path / "gold.jsonl"
    p.write_text("\n".join(json.dumps(r) if isinstance(r, dict) else r for r in rows) + "\n")
    return str(p)


def test_load_gold_rows_valid(tmp_path):
    rows = _load_gold_rows(_write(tmp_path, [_row()]))
    assert len(rows) == 1
    assert rows[0]["gold"]["ids"] == {"arxiv": "2606.1"}
    assert rows[0]["query_origin"]["bucket"] == "title"
    gp = _gold_paper(rows[0])
    assert gp.ids == {"arxiv": "2606.1"}
    assert gp.bucket == "title"


def test_load_gold_rows_skips_malformed(tmp_path):
    rows = _load_gold_rows(
        _write(
            tmp_path,
            [
                _row(),
                "{not valid json",
                _row(gold="{bad json"),
                _row(gold=json.dumps({"ids": {}})),
                _row(gold=json.dumps({"ids": ["x"]})),
                _row(gold=json.dumps({"paper_key": "x"})),
            ],
        )
    )
    assert len(rows) == 1


def test_load_gold_rows_coerces_non_dict_origin(tmp_path):
    rows = _load_gold_rows(_write(tmp_path, [_row(query_origin=json.dumps(["not", "a", "dict"]))]))
    assert len(rows) == 1
    assert rows[0]["query_origin"] == {}
    assert _gold_paper(rows[0]).bucket == "unknown"


def test_load_gold_rows_accepts_nested_objects(tmp_path):
    row = {
        "query_text": "q",
        "query_origin": {"bucket": "body", "suite": "europepmc"},
        "gold": {"ids": {"pmid": "999"}, "paper_key": "999"},
    }
    rows = _load_gold_rows(_write(tmp_path, [row]))
    assert len(rows) == 1
    assert _gold_paper(rows[0]).ids == {"pmid": "999"}
