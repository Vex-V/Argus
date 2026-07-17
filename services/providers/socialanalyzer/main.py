"""Social Analyzer provider service (port 8029).

On-demand profile discovery across 900+ social sites via the local
social-analyzer clone (external/social-analyzer/), imported in-process.
Stateless: returns discovered accounts, does not persist. Degrades to an empty
result set (HTTP 200) when the clone or its dependencies are missing.
"""
import logging

from fastapi import FastAPI
from pydantic import BaseModel

from shared.cors import add_cors
from shared.evidence import capture_provenance
from shared.schemas import ServiceResponse

from .provider import search

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Argus — Social Analyzer Provider",
    version="0.1.0",
    description="Profile discovery across 900+ social sites via the social-analyzer clone.",
)

add_cors(app)


class SocialAnalyzerSearchRequest(BaseModel):
    username: str
    # top > 0 restricts the scan to the N highest-ranked sites (much faster
    # than all 900+); websites narrows to specific site name(s), space-separated.
    top: int = 0
    websites: str = "all"


@app.post("/providers/socialanalyzer/search", response_model=ServiceResponse, tags=["provider"])
async def socialanalyzer_search(request: SocialAnalyzerSearchRequest) -> ServiceResponse:
    accounts = await search(request.username, request.top, request.websites)
    return ServiceResponse(
        results=[a.model_dump(mode="json") for a in accounts],
        provenance=capture_provenance("socialanalyzer_provider"),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "socialanalyzer_provider"}
