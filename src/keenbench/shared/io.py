import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, TextIO

Record = Mapping[str, Any]


def _write(records: Iterable[Record], fh: TextIO) -> None:
    for record in records:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_jsonl(records: Iterable[Record], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        _write(records, fh)


def write_stdout(records: Iterable[Record]) -> None:
    _write(records, sys.stdout)
