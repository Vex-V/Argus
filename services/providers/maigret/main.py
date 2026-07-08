"""Maigret provider service (port 8020).

On-demand username enumeration. Stateless: returns discovered accounts, does
not persist. Degrades to an empty result set (HTTP 200) when the maigret CLI
is not installed.
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
    title="Argus — Maigret Provider",
    version="0.1.0",
    description="Username enumeration across many sites via the maigret CLI.",
)

add_cors(app)


class MaigretSearchRequest(BaseModel):
    username: str
    # Overrides settings.maigret_top_sites for this request only. Maigret
    # ranks its site list by popularity, so higher = broader coverage but a
    # longer scan (3000+ = full scan).
    top_sites: int | None = None


@app.post("/providers/maigret/search", response_model=ServiceResponse, tags=["provider"])
async def maigret_search(request: MaigretSearchRequest) -> ServiceResponse:
    accounts = await search(request.username, request.top_sites)
    return ServiceResponse(
        results=[a.model_dump(mode="json") for a in accounts],
        provenance=capture_provenance("maigret_provider"),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "maigret_provider"}
