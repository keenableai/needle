import hashlib
import re
import unicodedata
from datetime import UTC, datetime


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
    # The hour label drops the offset, so normalize to UTC first; naive datetimes
    # are assumed to already be UTC.
    if hour_ts.tzinfo is not None:
        hour_ts = hour_ts.astimezone(UTC)
    return f"{query_hash(text)}_{hour_ts:%Y-%m-%dT%H}"
