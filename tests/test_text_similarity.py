import importlib.util

import pytest

from services.analyzers.text.analyzer import (
    analyze_text_similarity,
    stylometric_features,
    stylometric_similarity,
)

_HAS_ST = importlib.util.find_spec("sentence_transformers") is not None

SIMILAR_A = [
    "Hey everyone!! Big news coming soon, stay tuned!!!",
    "Wow what a day!! Can't wait to share more!!!",
]
SIMILAR_B = [
    "Hi folks!! Huge update on the way, keep watching!!!",
    "Amazing times!! So excited to tell you all!!!",
]
DIFFERENT = [
    "The quarterly financial report indicates a modest decline in revenue.",
    "Pursuant to regulatory requirements, the committee convened on Tuesday.",
]


def test_stylometric_features_has_expected_keys():
    feats = stylometric_features(SIMILAR_A)
    for key in ("avg_word_length", "avg_sentence_length", "caps_ratio", "emoji_per_post"):
        assert key in feats


def test_identical_style_scores_one():
    feats = stylometric_features(SIMILAR_A)
    assert abs(stylometric_similarity(feats, feats) - 1.0) < 1e-9


def test_similar_style_beats_different_style():
    sim = stylometric_similarity(
        stylometric_features(SIMILAR_A), stylometric_features(SIMILAR_B)
    )
    diff = stylometric_similarity(
        stylometric_features(SIMILAR_A), stylometric_features(DIFFERENT)
    )
    assert sim > diff


def test_analyze_returns_full_structure():
    result = analyze_text_similarity(SIMILAR_A, SIMILAR_B)
    assert set(result) >= {
        "semantic_similarity",
        "stylometric_similarity",
        "combined_score",
        "evidence",
    }
    assert 0.0 <= result["combined_score"] <= 1.0


def test_empty_inputs_are_safe():
    result = analyze_text_similarity([], [])
    assert result["combined_score"] == 0.0


@pytest.mark.skipif(not _HAS_ST, reason="sentence-transformers not installed")
def test_semantic_similar_beats_different_when_model_available():
    # Runs only when the heavy semantic model is installed (downloads on first use).
    sim = analyze_text_similarity(SIMILAR_A, SIMILAR_B)["combined_score"]
    diff = analyze_text_similarity(SIMILAR_A, DIFFERENT)["combined_score"]
    assert sim > diff
