from datetime import UTC, datetime, timedelta, timezone

from needle.shared.identity import canonicalize, query_hash, query_id


def test_canonicalize_collapses_and_lowercases():
    assert canonicalize("  Lakers   Trade  Deadline ") == "lakers trade deadline"


def test_query_hash_stable_and_case_insensitive():
    assert query_hash("Lakers trade") == query_hash("lakers  trade")
    assert len(query_hash("x")) == 16


def test_query_id_format():
    ts = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    qid = query_id("lakers trade deadline", hour_ts=ts)
    assert qid == f"{query_hash('lakers trade deadline')}_2026-07-01T14"


def test_query_id_normalizes_timezone():
    utc = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    same_instant = utc.astimezone(timezone(timedelta(hours=2)))
    assert query_id("q", hour_ts=same_instant) == query_id("q", hour_ts=utc)
    naive_utc = datetime(2026, 7, 1, 14, 0)
    assert query_id("q", hour_ts=naive_utc) == query_id("q", hour_ts=utc)
