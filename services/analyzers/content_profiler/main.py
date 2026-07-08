"""C10 — Content Profiler service (port 8015)."""
import logging

from fastapi import FastAPI

from shared.cors import add_cors

from shared.evidence import capture_provenance
from shared.schemas import ContentProfileRequest, ServiceResponse

from .profiler import profile_content

logging.basicConfig(level=logging.INFO)
app = FastAPI(
    title="Argus — Content Profiler",
    version="0.1.0",
    description="C10: per-account keywords, hashtags, sentiment, and tone.",
)


add_cors(app)

@app.post("/analyze/profile-content", response_model=ServiceResponse, tags=["analyzer"])
async def profile(request: ContentProfileRequest) -> ServiceResponse:
    result = await profile_content(request.posts, request.platform)
    return ServiceResponse(results=[result], provenance=capture_provenance("content_profiler"))


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "content_profiler"}
