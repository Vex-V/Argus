import importlib.util

import numpy as np
import pytest

from services.analyzers.facial import analyzer
from services.analyzers.facial.analyzer import cosine_similarity, get_face_embedding

_HAS_FACENET = importlib.util.find_spec("facenet_pytorch") is not None


def test_cosine_identical_is_one():
    v = np.array([1.0, 2.0, 3.0, 4.0])
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-9


def test_cosine_orthogonal_is_zero():
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert abs(cosine_similarity(a, b)) < 1e-9


def test_cosine_handles_zero_vector():
    assert cosine_similarity(np.zeros(4), np.ones(4)) == 0.0


@pytest.mark.skipif(_HAS_FACENET, reason="facenet-pytorch installed — model path exercised elsewhere")
def test_embedding_none_without_model():
    # With facenet-pytorch absent the model can't load, so embedding is None.
    assert get_face_embedding(b"not-an-image") is None


def test_detect_face_returns_none_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(analyzer, "get_model", lambda: (None, None))
    assert analyzer.detect_face(b"not-an-image") is None
