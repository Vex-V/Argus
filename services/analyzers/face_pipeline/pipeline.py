"""Face reverse-search pipeline — detect a face, reverse-image-search it via
Yandex, then score facial similarity between the source crop and each result.

Chains two other pieces in-process rather than reimplementing them: the
facial analyzer's MTCNN detect/embed functions, and the yandeximage
provider's Playwright-driven Yandex search. These are plain Python imports,
not HTTP calls to those services, so this works identically whether it runs
as its own standalone service or merged into gateway.py — but it does mean
this service needs the same dependencies as both of those (facenet-pytorch
model + Playwright/chromium) to get real (non-empty) results.

Matched images are saved to disk rather than returned inline (they were
briefly base64-encoded into the JSON response — swapped for saving + a
relative path once it was clear the API caller wants a downloadable file, not
a multi-megabyte JSON blob per request).
"""
import base64
import logging
from pathlib import Path

import httpx

from services.analyzers.facial.analyzer import cosine_similarity, detect_face, get_face_embedding
from services.providers.yandeximage.provider import reverse_image_search
from shared.evidence import hash_content

log = logging.getLogger("analyzer.face_pipeline")

# Each run's source crop + ranked matches are saved here under a subfolder
# named by content hash of the source image, so re-running on the same image
# overwrites rather than piling up (same convention as facial/extracted_faces/).
OUTPUT_DIR = Path(__file__).resolve().parent / "output"


async def run_pipeline(image_bytes: bytes, top_n: int = 10) -> dict:
    """Detect the source face, reverse-search it, and score each candidate.

    Never raises — degrades to a dict describing what stage stopped it
    (no face detected, no embedding, no search results) so the endpoint can
    always return HTTP 200 with a clear reason. `matches[i]["relative_path"]`
    and `source_face_relative_path` are paths under OUTPUT_DIR/<run_id>/ —
    the caller (main.py) turns those into real download URLs, since only it
    knows the request's actual host.
    """
    detection = detect_face(image_bytes)
    if detection is None:
        return {"face_detected": False, "matches": []}

    crop_bytes = base64.b64decode(detection["extracted_face_base64"])

    source_embedding = get_face_embedding(crop_bytes)
    if source_embedding is None:
        return {
            "face_detected": True,
            "confidence": detection["confidence"],
            "matches": [],
            "error": "could not embed source face crop",
        }

    results = await reverse_image_search(crop_bytes, top_n=top_n, filename="face.png", content_type="image/png")

    run_id = hash_content(image_bytes)
    run_dir = OUTPUT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "00_source_face.png").write_bytes(crop_bytes)

    scored = await _score_candidates(results, source_embedding)
    scored.sort(key=lambda pair: pair[0]["similarity_pct"], reverse=True)
    matches = _save_ranked(scored, run_dir, run_id)

    return {
        "face_detected": True,
        "confidence": detection["confidence"],
        "run_id": run_id,
        "source_face_relative_path": f"{run_id}/00_source_face.png",
        "results_returned": len(results),
        "matches": matches,
    }


async def _score_candidates(results: list[dict], source_embedding) -> list[tuple[dict, bytes]]:
    """Return (match metadata, raw image bytes) pairs — bytes kept out of the
    metadata dict itself so nothing accidentally serializes a huge blob."""
    scored: list[tuple[dict, bytes]] = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for r in results:
            thumb_url = r.get("thumbnail_url")
            if not thumb_url:
                continue
            try:
                resp = await client.get(thumb_url)
                resp.raise_for_status()
                candidate_bytes = resp.content
            except Exception as exc:  # noqa: BLE001
                log.warning("could not fetch thumbnail for %s: %s", r.get("domain"), exc)
                continue

            candidate_embedding = get_face_embedding(candidate_bytes)
            if candidate_embedding is None:
                continue

            similarity = max(0.0, cosine_similarity(source_embedding, candidate_embedding))
            match = {
                "similarity_pct": round(similarity * 100, 1),
                "title": r.get("title"),
                "domain": r.get("domain"),
                "url": r.get("url"),
            }
            scored.append((match, candidate_bytes))
    return scored


def _save_ranked(scored: list[tuple[dict, bytes]], run_dir: Path, run_id: str) -> list[dict]:
    matches = []
    for rank, (match, candidate_bytes) in enumerate(scored, start=1):
        safe_domain = "".join(c if c.isalnum() or c in ".-_" else "_" for c in (match["domain"] or "unknown"))
        filename = f"{rank:02d}_{match['similarity_pct']:05.1f}pct_{safe_domain}.jpg"
        (run_dir / filename).write_bytes(candidate_bytes)
        match["relative_path"] = f"{run_id}/{filename}"
        matches.append(match)
    return matches
