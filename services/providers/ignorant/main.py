"""Ignorant provider service (port 8028).

On-demand phone-number registration checks across several sites via the local
ignorant clone (external/ignorant/). Stateless: returns discovered
registrations, does not persist. Degrades to an empty result set (HTTP 200)
when the clone is missing or the number can't be parsed.
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
    title="Argus — Ignorant Provider",
    version="0.1.0",
    description="Phone-number registration checks across several sites via the ignorant clone.",
)

add_cors(app)


class IgnorantCheckRequest(BaseModel):
    # `phone` may be a full international number (+919876543210) — country_code
    # is then optional and parsed out of it. Or pass the national number in
    # `phone` and the calling code separately in `country_code` ("91").
    phone: str
    country_code: str | None = None


@app.post("/providers/ignorant/check", response_model=ServiceResponse, tags=["provider"])
async def ignorant_check(request: IgnorantCheckRequest) -> ServiceResponse:
    hits = await search(request.phone, request.country_code)
    return ServiceResponse(
        results=hits,
        provenance=capture_provenance("ignorant_provider"),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "ignorant_provider"}
