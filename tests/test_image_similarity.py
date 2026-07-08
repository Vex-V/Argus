"""Tests for the non-face image similarity analyzer (C7, pHash)."""
import importlib.util
import io

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from services.analyzers.image_similarity.analyzer import (
    compare_images,
    compute_phash,
    hamming_distance,
)

_HAS_IMAGEHASH = (
    importlib.util.find_spec("imagehash") is not None
    and importlib.util.find_spec("PIL") is not None
)

pytestmark = pytest.mark.skipif(not _HAS_IMAGEHASH, reason="imagehash/Pillow not installed")


def _png(color, size=(64, 64)) -> bytes:
    from PIL import Image

    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _gradient_png(seed: int, size=(64, 64)) -> bytes:
    """A smooth diagonal gradient scaled to the image size, so the SAME seed
    produces a visually identical picture at any resolution (pHash-stable
    across resizes). `seed` shifts the pattern to produce distinct images."""
    from PIL import Image

    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for x in range(w):
        for y in range(h):
            fx = x / w
            fy = y / h
            r = int(255 * ((fx + seed * 0.13) % 1.0))
            g = int(255 * ((fy + seed * 0.07) % 1.0))
            b = int(255 * (((fx + fy) / 2 + seed * 0.19) % 1.0))
            px[x, y] = (r, g, b)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_identical_images_are_a_match():
    img = _gradient_png(0)
    result = compare_images(img, img)
    assert result["phash_distance"] == 0
    assert result["similarity"] == 1.0
    assert result["likely_match"] is True


def test_very_different_images_are_not_a_match():
    a = _gradient_png(0)
    b = _png((255, 255, 255))  # flat white — structurally very different
    result = compare_images(a, b)
    assert result["similarity"] < 1.0
    # a rich gradient vs a flat image should exceed the match threshold
    assert result["likely_match"] is False


def test_resized_copy_still_matches():
    # pHash is robust to scaling — a resized copy should stay under threshold.
    a = _gradient_png(7, size=(128, 128))
    b = _gradient_png(7, size=(64, 64))
    result = compare_images(a, b)
    assert result["likely_match"] is True


def test_compare_unreadable_image_degrades():
    result = compare_images(b"not-an-image", _gradient_png(1))
    assert result["similarity"] == 0.0
    assert result["likely_match"] is False
    assert "could_not_hash_image_a" in result["evidence"]


def test_compute_phash_and_distance_roundtrip():
    h1 = compute_phash(_gradient_png(0))
    h2 = compute_phash(_gradient_png(0))
    assert h1 is not None and h1 == h2
    assert hamming_distance(h1, h2) == 0


@pytest_asyncio.fixture
async def client():
    from services.analyzers.image_similarity.main import app

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://img.test") as c:
            yield c


async def test_compare_endpoint_identical(client):
    img = _gradient_png(3)
    resp = await client.post(
        "/image/compare",
        files={"image_a": ("a.png", img, "image/png"), "image_b": ("b.png", img, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["similarity"] == 1.0
    assert result["likely_match"] is True


async def test_health_reports_phash_available(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["phash_available"] is True
