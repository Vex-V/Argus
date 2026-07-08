"""C6 — Facial Similarity service (port 8011).

Internal face matching over the system's own image database. Embeds faces
with facenet-pytorch and searches pgvector for nearest neighbours. Degrades
gracefully (face_detected=false / clear error) when the model isn't loaded.
"""
import base64
import logging

from fastapi import FastAPI, File, Form, UploadFile

from shared.cors import add_cors
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.db import SessionLocal
from shared.evidence import capture_provenance, hash_content, now_utc
from shared.models import Image
from shared.schemas import FaceCompareRequest, ServiceResponse

from .analyzer import (
    cosine_similarity,
    detect_face,
    get_face_embedding,
    is_loaded,
    model_available,
)

logging.basicConfig(level=logging.INFO)
app = FastAPI(
    title="Argus — Facial Similarity",
    version="0.1.0",
    description="C6: ArcFace embeddings + pgvector nearest-neighbour face search.",
)


def _vec_literal(embedding) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in embedding) + "]"


add_cors(app)

@app.post("/face/embed", response_model=dict, tags=["facial"])
async def embed(
    file: UploadFile = File(...),
    source_url: str | None = Form(default=None),
    source_entity_id: str | None = Form(default=None),
    image_type: str = Form(default="avatar"),
) -> dict:
    image_bytes = await file.read()
    hash_id = hash_content(image_bytes)
    embedding = get_face_embedding(image_bytes)

    if embedding is None:
        return {"hash_id": hash_id, "face_detected": False, "embedding_stored": False}

    db = SessionLocal()
    try:
        values = {
            "hash_id": hash_id,
            "source_url": source_url,
            "source_entity_id": source_entity_id,
            "image_type": image_type,
            "face_detected": True,
            "face_embedding": embedding.tolist(),
            "captured_at": now_utc(),
        }
        stmt = pg_insert(Image).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Image.hash_id],
            set_={
                "face_embedding": stmt.excluded.face_embedding,
                "face_detected": stmt.excluded.face_detected,
                "source_url": stmt.excluded.source_url,
                "source_entity_id": stmt.excluded.source_entity_id,
            },
        )
        db.execute(stmt)
        db.commit()
    finally:
        db.close()

    return {"hash_id": hash_id, "face_detected": True, "embedding_stored": True}


@app.post("/face/compare", response_model=ServiceResponse, tags=["facial"])
def compare(request: FaceCompareRequest) -> ServiceResponse:
    if not model_available():
        return ServiceResponse(
            results=[{"score": 0.0, "evidence": ["face_model_unavailable"]}],
            provenance=capture_provenance("facial_analyzer"),
            errors=["facenet-pytorch model not loaded on this host."],
        )

    emb_a = get_face_embedding(base64.b64decode(request.image_a))
    emb_b = get_face_embedding(base64.b64decode(request.image_b))

    if emb_a is None or emb_b is None:
        which = []
        if emb_a is None:
            which.append("no_face_in_image_a")
        if emb_b is None:
            which.append("no_face_in_image_b")
        return ServiceResponse(
            results=[{"score": 0.0, "evidence": which}],
            provenance=capture_provenance("facial_analyzer"),
        )

    cos = cosine_similarity(emb_a, emb_b)
    score = round(max(0.0, cos), 4)  # clamp negatives to 0
    return ServiceResponse(
        results=[{"score": score, "evidence": [f"cosine_similarity: {cos:.3f}"]}],
        provenance=capture_provenance("facial_analyzer"),
    )


@app.post("/face/detect", response_model=ServiceResponse, tags=["facial"])
async def detect(file: UploadFile = File(...)) -> ServiceResponse:
    image_bytes = await file.read()

    if not model_available():
        return ServiceResponse(
            results=[{"face_detected": False}],
            provenance=capture_provenance("facial_analyzer"),
            errors=["face_model_unavailable"],
        )

    result = detect_face(image_bytes)
    if result is None:
        return ServiceResponse(
            results=[{"face_detected": False}],
            provenance=capture_provenance("facial_analyzer"),
            errors=["no_face_detected"],
        )

    return ServiceResponse(results=[result], provenance=capture_provenance("facial_analyzer"))


@app.post("/face/search", response_model=ServiceResponse, tags=["facial"])
async def search(file: UploadFile = File(...), limit: int = 10) -> ServiceResponse:
    image_bytes = await file.read()
    embedding = get_face_embedding(image_bytes)
    if embedding is None:
        return ServiceResponse(
            results=[],
            provenance=capture_provenance("facial_analyzer"),
            errors=["no face detected in query image"],
        )

    vec = _vec_literal(embedding)
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT hash_id, source_entity_id, "
                "1 - (face_embedding <=> (:vec)::vector) AS similarity "
                "FROM images WHERE face_detected = true "
                "ORDER BY face_embedding <=> (:vec)::vector LIMIT :k"
            ),
            {"vec": vec, "k": limit},
        ).mappings().all()
    finally:
        db.close()

    results = [
        {
            "hash_id": r["hash_id"],
            "source_entity_id": r["source_entity_id"],
            "similarity": round(float(r["similarity"]), 4),
        }
        for r in rows
    ]
    return ServiceResponse(results=results, provenance=capture_provenance("facial_analyzer"))


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "facial_analyzer", "model_loaded": is_loaded()}
