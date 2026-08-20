import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, TextIO

Record = Mapping[str, Any]


def _write(records: Iterable[Record], fh: TextIO) -> None:
    for record in records:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_jsonl(records: Iterable[Record], out: str) -> None:
    if out == "-":
        _write(records, sys.stdout)
        return
    with open(out, "w", encoding="utf-8") as fh:
        _write(records, fh)


def append_jsonl(records: Iterable[Record], out: str) -> None:
    with open(out, "a", encoding="utf-8") as fh:
        _write(records, fh)


def serialize_row(
    row: dict[str, Any], fields: tuple[str, ...] = ("query_origin", "gold")
) -> dict[str, Any]:
    out = dict(row)
    for name in fields:
        out[name] = json.dumps(row[name], sort_keys=True)
    return out


def read_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    return read_jsonl(p.read_text(encoding="utf-8")) if p.exists() else []


def write_json(obj: Any, out: str) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if out == "-":
        print(text)
    else:
        Path(out).write_text(text + "\n", encoding="utf-8")
