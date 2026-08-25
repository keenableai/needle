import json
from datetime import UTC, datetime

from needle.agentic_rare.cli import query_row
from needle.shared.identity import query_hash

HOUR_TS = datetime(2026, 8, 6, 7, tzinfo=UTC)


def test_query_row_identity_fields():
    row = {
        "query_text": "Marmnamarz video game language",
        "source": "deepresearchgym",
        "metadata": '{"session_id": "abc"}',
        "length_bucket": "long",
        "hard_words": '[{"word": "marmnamarz", "subwords": ["[UNK]"]}]',
    }
    out = query_row(row, hour_ts=HOUR_TS)
    assert out["query_text"] == "Marmnamarz video game language"
    assert out["query_hash"] == query_hash("Marmnamarz video game language")
    assert out["query_id"] == f"{out['query_hash']}_2026-08-06T07"
    assert out["query_source"] == "agentic_rare"
    assert out["hour_ts"] == "2026-08-06T07:00:00+00:00"
    assert out["query_produced_at"] == out["hour_ts"]
    origin = json.loads(out["query_origin"])
    assert origin["bucket"] == "agentic_rare"
    assert origin["subcategory"] == "rare_long"
    assert origin["provenance"]["producer"] == "agentic_rare"
    assert origin["provenance"]["source"] == "deepresearchgym"
    assert origin["provenance"]["metadata"] == {"session_id": "abc"}
    assert origin["provenance"]["hard_words"] == [{"word": "marmnamarz", "subwords": ["[UNK]"]}]


def test_query_row_sparse_source_row():
    out = query_row({"query": "x y z"}, hour_ts=HOUR_TS)
    assert out["query_text"] == "x y z"
    origin = json.loads(out["query_origin"])
    assert origin["subcategory"] == "rare_unknown"
    assert origin["provenance"]["source"] is None
    assert origin["provenance"]["metadata"] is None
