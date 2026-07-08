import importlib.util

import pytest

from services.analyzers.content_profiler.profiler import (
    analyze_sentiment,
    extract_hashtags,
    extract_keywords,
)

_HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None
_HAS_VADER = importlib.util.find_spec("vaderSentiment") is not None

POSTS = [
    "Loving the new #python release, so much faster! #coding",
    "Another great day writing #python code. Highly recommend it!",
    "The weather is terrible today, feeling awful and sad.",
]


def test_extract_hashtags_counts():
    tags = dict(extract_hashtags(POSTS))
    assert tags["python"] == 2
    assert tags["coding"] == 1


def test_extract_hashtags_empty():
    assert extract_hashtags([]) == []


@pytest.mark.skipif(not _HAS_SKLEARN, reason="scikit-learn not installed")
def test_extract_keywords_returns_terms():
    keywords = extract_keywords(POSTS, top_n=5)
    assert isinstance(keywords, list)
    assert len(keywords) > 0
    assert all(isinstance(k, str) for k in keywords)


@pytest.mark.skipif(not _HAS_VADER, reason="vaderSentiment not installed")
def test_sentiment_detects_polarity():
    positive = analyze_sentiment(["I love this, it's amazing and wonderful!"])
    negative = analyze_sentiment(["I hate this, it's awful and terrible."])
    assert positive["compound"] > negative["compound"]


def test_sentiment_empty_is_neutral():
    result = analyze_sentiment([])
    assert result["neutral"] == 1.0
    assert result["compound"] == 0.0
