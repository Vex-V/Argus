"""GHunt provider service (port 8030).

On-demand Google account OSINT from an email address via the local GHunt clone
(external/GHunt/), imported in-process. Stateless: returns what it finds, does
not persist. Degrades to a partial/empty result set (HTTP 200) when the clone
is missing, no GHunt session is configured, or the target isn't found — the
per-call `errors` list explains any degradation.
"""
import logging

from fastapi import FastAPI
from pydantic import BaseModel

from shared.cors import add_cors
from shared.evidence import capture_provenance
from shared.schemas import ServiceResponse

from .provider import lookup_gaia, maps_contributions, maps_reviews, search

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Argus — GHunt Provider",
    version="0.1.0",
    description="Google account OSINT from an email address via the GHunt clone.",
)

add_cors(app)


class GHuntEmailRequest(BaseModel):
    email: str


class GHuntGaiaRequest(BaseModel):
    gaia_id: str


class GHuntMapsContribRequest(BaseModel):
    gaia_id: str
    max_items: int = 50


@app.post("/providers/ghunt/email", response_model=ServiceResponse, tags=["provider"])
async def ghunt_email(request: GHuntEmailRequest) -> ServiceResponse:
    results, errors = await search(request.email)
    return ServiceResponse(
        results=results,
        provenance=capture_provenance("ghunt_provider"),
        errors=errors,
    )


@app.post("/providers/ghunt/gaia", response_model=ServiceResponse, tags=["provider"])
async def ghunt_gaia(request: GHuntGaiaRequest) -> ServiceResponse:
    """Reverse lookup: a Gaia ID → the public Google Account profile."""
    results, errors = await lookup_gaia(request.gaia_id)
    return ServiceResponse(
        results=results,
        provenance=capture_provenance("ghunt_provider"),
        errors=errors,
    )


@app.post("/providers/ghunt/maps-reviews", response_model=ServiceResponse, tags=["provider"])
async def ghunt_maps_reviews(request: GHuntGaiaRequest) -> ServiceResponse:
    """A Gaia ID → their Google Maps contribution statistics + contributor page."""
    results, errors = await maps_reviews(request.gaia_id)
    return ServiceResponse(
        results=results,
        provenance=capture_provenance("ghunt_provider"),
        errors=errors,
    )


@app.post("/providers/ghunt/maps-contributions", response_model=ServiceResponse, tags=["provider"])
async def ghunt_maps_contributions(request: GHuntMapsContribRequest) -> ServiceResponse:
    """A Gaia ID → their actual public Maps reviews/ratings (headless-scraped)."""
    results, errors = await maps_contributions(request.gaia_id, request.max_items)
    return ServiceResponse(
        results=results,
        provenance=capture_provenance("ghunt_provider"),
        errors=errors,
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "ghunt_provider"}
