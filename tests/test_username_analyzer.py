from services.analyzers.username.analyzer import (
    analyze_username_similarity,
    normalize_leet,
)


def test_exact_match_case_insensitive():
    result = analyze_username_similarity("fox_99", "FOX_99")
    assert result["score"] == 1.0
    assert "exact_match" in result["evidence"]


def test_leet_speak_match_scores_high():
    result = analyze_username_similarity("fox_99", "f0x99")
    # f0x99 -> fox99 ; fox_99 -> fox99  => leet-normalized exact match
    assert result["score"] >= 0.8


def test_similar_usernames_score_moderate_to_high():
    result = analyze_username_similarity("john_smith", "johnsmith")
    assert result["score"] >= 0.8


def test_different_usernames_score_low():
    result = analyze_username_similarity("fox_99", "totally_different")
    assert result["score"] < 0.6


def test_normalize_leet_strips_separators_and_leet():
    assert normalize_leet("f0x_99") == normalize_leet("fox99")
    assert normalize_leet("l33t.h@x0r") == "leethaxor"
