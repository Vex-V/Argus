"""C9 — Text Similarity service (port 8012)."""
import logging

from fastapi import FastAPI

from shared.cors import add_cors

from shared.evidence import capture_provenance
from shared.schemas import ServiceResponse, TextSimilarityRequest

from .analyzer import analyze_text_similarity, is_loaded

logging.basicConfig(level=logging.INFO)
app = FastAPI(
    title="Argus — Text Similarity",
    version="0.1.0",
    description="C9: semantic (sentence-transformers) + stylometric writing comparison.",
)


add_cors(app)

@app.post("/analyze/text-similarity", response_model=ServiceResponse, tags=["analyzer"])
def text_similarity(request: TextSimilarityRequest) -> ServiceResponse:
    result = analyze_text_similarity(request.texts_a, request.texts_b)
    return ServiceResponse(results=[result], provenance=capture_provenance("text_analyzer"))


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "text_analyzer", "semantic_model_loaded": is_loaded()}
