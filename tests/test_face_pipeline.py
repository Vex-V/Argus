"""Offline tests for the face reverse-search pipeline analyzer.

Exercises the graceful-degradation paths only (no network, no real model) —
same convention as tests/test_facial.py.
"""
import pytest

from services.analyzers.face_pipeline import pipeline


@pytest.mark.asyncio
async def test_run_pipeline_returns_not_detected_when_no_face(monkeypatch):
    monkeypatch.setattr(pipeline, "detect_face", lambda image_bytes: None)
    result = await pipeline.run_pipeline(b"not-an-image")
    assert result == {"face_detected": False, "matches": []}


@pytest.mark.asyncio
async def test_run_pipeline_reports_error_when_source_face_cannot_be_embedded(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "detect_face",
        lambda image_bytes: {"confidence": 0.9, "extracted_face_base64": "AA=="},
    )
    monkeypatch.setattr(pipeline, "get_face_embedding", lambda crop_bytes: None)

    result = await pipeline.run_pipeline(b"not-an-image")

    assert result["face_detected"] is True
    assert result["confidence"] == 0.9
    assert result["matches"] == []
    assert result["error"] == "could not embed source face crop"
