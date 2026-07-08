"""C7 — Non-face Image Similarity service (port 8016).

Perceptual-hash (pHash) matching to find reused/duplicate images across the
system's image database — profile banners, memes, re-posted photos — that a
face matcher would miss. /image/compare diffs two uploaded images directly;
/image/search hashes one image and finds the closest stored images by Hamming
distance. Degrades gracefully (clear error, no crash) when imagehash/Pillow
aren't installed or an image can't be read.
"""
import logging

from fastapi import FastAPI, File, UploadFile
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.cors import add_cors
from shared.db import SessionLocal
from shared.evidence import capture_provenance, hash_content, now_utc
from shared.models import Image
from shared.schemas import ServiceResponse

from .analyzer import (
    MATCH_THRESHOLD,
    compare_images,
    compute_phash,
    hamming_distance,
)

logging.basicConfig(level=logging.INFO)
app = FastAPI(
    title="Argus — Image Similarity",
    version="0.1.0",
    description="C7: perceptual-hash (pHash) matching for non-face image reuse.",
)
add_cors(app)


@app.post("/image/compare", response_model=ServiceResponse, tags=["image"])
async def compare(
    image_a: UploadFile = File(...), image_b: UploadFile = File(...)
) -> ServiceResponse:
    bytes_a = await image_a.read()
    bytes_b = await image_b.read()
    result = compare_images(bytes_a, bytes_b)
    return ServiceResponse(results=[result], provenance=capture_provenance("image_similarity"))


@app.post("/image/search", response_model=ServiceResponse, tags=["image"])
async def search(file: UploadFile = File(...), limit: int = 10) -> ServiceResponse:
    image_bytes = await file.read()
    query_hash = compute_phash(image_bytes)
    if query_hash is None:
        return ServiceResponse(
            results=[],
            provenance=capture_provenance("image_similarity"),
            errors=["could not hash query image (unreadable or imagehash unavailable)"],
        )

    # Store/refresh this image's phash so future searches can match it too.
    hash_id = hash_content(image_bytes)
    db = SessionLocal()
    try:
        stmt = pg_insert(Image).values(
            hash_id=hash_id,
            image_type="query",
            face_detected=False,
            phash=query_hash,
            captured_at=now_utc(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Image.hash_id], set_={"phash": stmt.excluded.phash}
        )
        db.execute(stmt)
        db.commit()

        rows = db.execute(
            select(Image.hash_id, Image.source_entity_id, Image.source_url, Image.phash)
            .where(Image.phash.is_not(None))
            .where(Image.hash_id != hash_id)
        ).all()
    finally:
        db.close()

    scored = []
    for r in rows:
        distance = hamming_distance(query_hash, r.phash)
        if distance is None:
            continue
        scored.append(
            {
                "hash_id": r.hash_id,
                "source_entity_id": r.source_entity_id,
                "source_url": r.source_url,
                "phash_distance": distance,
                "similarity": round(1.0 - (distance / 64), 4),
                "likely_match": distance <= MATCH_THRESHOLD,
            }
        )
    scored.sort(key=lambda x: x["phash_distance"])
    return ServiceResponse(results=scored[:limit], provenance=capture_provenance("image_similarity"))


@app.get("/health", tags=["meta"])
def health() -> dict:
    from .analyzer import _hashes_available

    return {"status": "ok", "service": "image_similarity", "phash_available": _hashes_available()}
