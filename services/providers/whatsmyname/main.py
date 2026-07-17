"""WhatsMyName provider service (port 8027).

On-demand username enumeration across ~700 sites via the WhatsMyName
community JSON dataset (external/WhatsMyName/). Stateless: returns discovered
accounts, does not persist. Degrades to an empty result set (HTTP 200) when
the dataset clone is missing.
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
    title="Argus — WhatsMyName Provider",
    version="0.1.0",
    description="Username enumeration across ~700 sites via the WhatsMyName JSON dataset.",
)

add_cors(app)


class WhatsMyNameSearchRequest(BaseModel):
    username: str


@app.post("/providers/whatsmyname/search", response_model=ServiceResponse, tags=["provider"])
async def whatsmyname_search(request: WhatsMyNameSearchRequest) -> ServiceResponse:
    accounts = await search(request.username)
    return ServiceResponse(
        results=[a.model_dump(mode="json") for a in accounts],
        provenance=capture_provenance("whatsmyname_provider"),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "whatsmyname_provider"}
