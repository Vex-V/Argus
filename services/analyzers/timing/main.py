"""C11 — Timing Analyzer service (port 8013)."""
from fastapi import FastAPI

from shared.cors import add_cors

from shared.evidence import capture_provenance
from shared.schemas import ServiceResponse, TimingRequest

from .analyzer import analyze_timing

app = FastAPI(
    title="Argus — Timing Analyzer",
    version="0.1.0",
    description="C11: compares posting-time distributions via Bhattacharyya coefficient.",
)


add_cors(app)

@app.post("/analyze/timing", response_model=ServiceResponse, tags=["analyzer"])
def timing(request: TimingRequest) -> ServiceResponse:
    result = analyze_timing(request.timestamps_a, request.timestamps_b)
    return ServiceResponse(results=[result], provenance=capture_provenance("timing_analyzer"))


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "timing_analyzer"}
