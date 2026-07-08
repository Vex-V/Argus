"""Holehe provider service (port 8024).

On-demand email registration checks across many sites via the local holehe
clone (holehe/). Stateless: returns discovered accounts, does not persist.
Degrades to an empty result set (HTTP 200) when the clone is missing.
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
    title="Argus — Holehe Provider",
    version="0.1.0",
    description="Email registration checks across many sites via the holehe clone.",
)

add_cors(app)


class HoleheSearchRequest(BaseModel):
    email: str


@app.post("/providers/holehe/search", response_model=ServiceResponse, tags=["provider"])
async def holehe_search(request: HoleheSearchRequest) -> ServiceResponse:
    hits = await search(request.email)
    return ServiceResponse(
        results=hits,
        provenance=capture_provenance("holehe_provider"),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "holehe_provider"}
