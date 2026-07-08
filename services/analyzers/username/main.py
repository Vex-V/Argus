"""C8 — Username Analyzer service (port 8010)."""
from fastapi import FastAPI

from shared.cors import add_cors

from shared.evidence import capture_provenance
from shared.schemas import ServiceResponse, UsernameCompareRequest

from .analyzer import analyze_username_similarity

app = FastAPI(
    title="Argus — Username Analyzer",
    version="0.1.0",
    description="C8: scores whether two usernames belong to the same person.",
)


add_cors(app)

@app.post("/analyze/username", response_model=ServiceResponse, tags=["analyzer"])
def compare_usernames(request: UsernameCompareRequest) -> ServiceResponse:
    result = analyze_username_similarity(request.username_a, request.username_b)
    return ServiceResponse(
        results=[result],
        provenance=capture_provenance("username_analyzer"),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "username_analyzer"}
