"""Text similarity core (C9).

Two signals, combined 60% semantic / 40% stylometric:
  * semantic  — cosine of sentence-transformer embeddings (paraphrase-
    multilingual-MiniLM). The model loads lazily on first use; if it or torch
    aren't installed, semantic similarity is reported as 0.0 and only the
    stylometric signal contributes.
  * stylometric — hand-computed writing-style features (word/sentence length,
    punctuation ratios, capitalization, emoji frequency), all pure-numpy.
"""
import logging
import re

import numpy as np

log = logging.getLogger("analyzer.text")

_model = None
_load_error: str | None = None

_SEMANTIC_WEIGHT = 0.6
_STYLOMETRIC_WEIGHT = 0.4
_MAX_POSTS = 20


def get_model():
    """Lazily load the sentence-transformer model (once)."""
    global _model, _load_error
    if _model is not None:
        return _model
    if _load_error is not None:
        return None
    try:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        log.info("sentence-transformer model loaded")
        return _model
    except Exception as exc:  # noqa: BLE001
        _load_error = str(exc)
        log.warning("sentence-transformers unavailable: %s", exc)
        return None


def is_loaded() -> bool:
    return _model is not None


def semantic_similarity(texts_a: list[str], texts_b: list[str]) -> float:
    if not texts_a or not texts_b:
        return 0.0
    model = get_model()
    if model is None:
        return 0.0
    emb_a = model.encode([" ".join(texts_a[:_MAX_POSTS])])
    emb_b = model.encode([" ".join(texts_b[:_MAX_POSTS])])
    denom = np.linalg.norm(emb_a[0]) * np.linalg.norm(emb_b[0])
    if denom == 0:
        return 0.0
    return float(np.dot(emb_a[0], emb_b[0]) / denom)


def stylometric_features(texts: list[str]) -> dict:
    if not texts:
        return {}
    all_text = " ".join(texts)
    words = all_text.split()
    sentences = [s for s in re.split(r"[.!?]+", all_text) if s.strip()]
    emoji_count = sum(1 for c in all_text if ord(c) > 0x1F000)

    return {
        "avg_word_length": float(np.mean([len(w) for w in words])) if words else 0.0,
        "avg_sentence_length": float(np.mean([len(s.split()) for s in sentences]))
        if sentences
        else 0.0,
        "exclamation_ratio": all_text.count("!") / max(len(all_text), 1),
        "question_ratio": all_text.count("?") / max(len(all_text), 1),
        "caps_ratio": sum(1 for c in all_text if c.isupper()) / max(len(all_text), 1),
        "emoji_per_post": emoji_count / max(len(texts), 1),
        "avg_post_length": float(np.mean([len(t) for t in texts])),
    }


def stylometric_similarity(features_a: dict, features_b: dict) -> float:
    if not features_a or not features_b:
        return 0.0
    keys = set(features_a) & set(features_b)
    if not keys:
        return 0.0
    diffs = []
    for k in keys:
        a, b = features_a[k], features_b[k]
        max_val = max(abs(a), abs(b), 0.001)
        diffs.append(1.0 - abs(a - b) / max_val)
    return float(np.mean(diffs))


def analyze_text_similarity(texts_a: list[str], texts_b: list[str]) -> dict:
    sem = semantic_similarity(texts_a, texts_b)
    feat_a = stylometric_features(texts_a)
    feat_b = stylometric_features(texts_b)
    style = stylometric_similarity(feat_a, feat_b)

    combined = _SEMANTIC_WEIGHT * sem + _STYLOMETRIC_WEIGHT * style
    return {
        "semantic_similarity": round(sem, 4),
        "stylometric_similarity": round(style, 4),
        "combined_score": round(combined, 4),
        "evidence": [
            f"semantic_similarity: {sem:.3f}",
            f"stylometric_similarity: {style:.3f}",
        ],
    }
