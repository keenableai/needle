import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any


def canonicalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def query_hash(text: str) -> str:
    canonical = canonicalize(text)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def query_id(text: str, *, hour_ts: datetime) -> str:
    if hour_ts.tzinfo is not None:
        hour_ts = hour_ts.astimezone(UTC)
    return f"{query_hash(text)}_{hour_ts:%Y-%m-%dT%H}"


def serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["query_origin"] = json.dumps(row["query_origin"], sort_keys=True)
    out["gold"] = json.dumps(row["gold"], sort_keys=True)
    return out
