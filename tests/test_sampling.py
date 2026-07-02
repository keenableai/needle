from datetime import UTC, datetime

from keenbench.shared.sampling import (
    sample_stratified,
    sample_uniform,
    seed_from_hour_ts,
    shuffle_indices,
)


def test_shuffle_is_deterministic_and_a_permutation():
    a = shuffle_indices(50, seed=123)
    b = shuffle_indices(50, seed=123)
    assert a == b
    assert sorted(a) == list(range(50))
    assert shuffle_indices(50, seed=124) != a


def test_sample_uniform_size_and_determinism():
    recs = [{"i": i} for i in range(20)]
    picked = sample_uniform(recs, 5, seed=7)
    assert len(picked) == 5
    assert sample_uniform(recs, 5, seed=7) == picked
    assert sample_uniform(recs, 100, seed=7) == sample_uniform(recs, 20, seed=7)


def test_sample_stratified_covers_every_domain_before_seconds():
    recs = (
        [{"topical_domain": "tech", "i": i} for i in range(10)]
        + [{"topical_domain": "sports", "i": i} for i in range(10)]
        + [{"topical_domain": "finance", "i": i} for i in range(2)]
    )
    picked = sample_stratified(recs, 3, seed=42)
    domains = {r["topical_domain"] for r in picked}
    assert domains == {"tech", "sports", "finance"}


def test_sample_stratified_custom_key():
    recs = [{"kind": "a"}, {"kind": "a"}, {"kind": "b"}]
    picked = sample_stratified(recs, 2, seed=1, key="kind")
    assert {r["kind"] for r in picked} == {"a", "b"}


def test_sample_stratified_tolerates_missing_key():
    recs = [{"topical_domain": "tech", "i": 0}, {"i": 1}]
    picked = sample_stratified(recs, 2, seed=1)
    assert len(picked) == 2


def test_seed_from_hour_ts_deterministic():
    ts = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    assert seed_from_hour_ts(ts) == seed_from_hour_ts(ts)
