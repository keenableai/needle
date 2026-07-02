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


def write_json(obj: Any, out: str) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if out == "-":
        print(text)
    else:
        Path(out).write_text(text + "\n", encoding="utf-8")
