"""Moriarty provider service (port 8021).

On-demand phone-number OSINT via the local Moriarty-Project clone. Stateless:
returns an enrichment dict, does not persist. Degrades gracefully (error field
in the result) when Moriarty-Project or credentials are missing.
"""
import logging

from fastapi import FastAPI
from pydantic import BaseModel

from shared.cors import add_cors
from shared.evidence import capture_provenance
from shared.schemas import ServiceResponse

from .provider import moriarty_lookup

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Argus — Moriarty Provider",
    version="0.1.0",
    description="Phone-number OSINT (geo, spam, mentions, Truecaller) via Moriarty-Project.",
)

add_cors(app)


class MoriartyLookupRequest(BaseModel):
    phone: str


@app.post("/providers/moriarty/lookup", response_model=ServiceResponse, tags=["provider"])
async def moriarty_lookup_route(request: MoriartyLookupRequest) -> ServiceResponse:
    result = await moriarty_lookup(request.phone)
    return ServiceResponse(
        results=[result],
        provenance=capture_provenance("moriarty_provider"),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "moriarty_provider"}
