from services.analyzers.contacts.analyzer import (
    analyze_contacts,
    jaccard_similarity,
    weighted_overlap,
)


def _c(ids, weight=1.0):
    return [{"id": i, "weight": weight} for i in ids]


def test_jaccard_basic():
    assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0
    assert jaccard_similarity({"a", "b", "c", "d"}, {"a", "b"}) == 0.5


def test_zero_overlap_scores_zero():
    result = analyze_contacts(_c(["a", "b", "c"]), _c(["x", "y", "z"]))
    assert result["combined_score"] == 0.0
    assert result["mutual_contacts"] == []


def test_overlap_is_proportional():
    partial = analyze_contacts(_c(["a", "b", "c", "d"]), _c(["a", "b", "x", "y"]))
    full = analyze_contacts(_c(["a", "b", "c"]), _c(["a", "b", "c"]))
    assert 0 < partial["combined_score"] < full["combined_score"]
    assert set(partial["mutual_contacts"]) == {"a", "b"}


def test_weighted_overlap_rewards_strong_interactions():
    # Same shared ids, but higher interaction weights -> higher weighted overlap.
    light = weighted_overlap(_c(["a", "b"], 1.0), _c(["a", "b"], 1.0))
    # With all weights equal the two accounts are identical -> 1.0
    assert light == 1.0
    mixed = weighted_overlap(
        [{"id": "a", "weight": 5.0}, {"id": "b", "weight": 1.0}],
        [{"id": "a", "weight": 5.0}, {"id": "c", "weight": 1.0}],
    )
    assert 0.0 < mixed < 1.0
