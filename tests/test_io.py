import json

from keenbench.shared.io import write_jsonl


def test_write_jsonl_one_object_per_line(tmp_path):
    records = [{"a": 1, "t": "café"}, {"a": 2}]
    out = tmp_path / "out.jsonl"
    write_jsonl(records, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"a": 1, "t": "café"}
    assert "café" in lines[0]
