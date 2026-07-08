"""WhatsApp provider service (port 8025).

Proxies to the Baileys Node sidecar (baileys-service/, run separately — it
holds the actual logged-in WhatsApp session). Degrades to exists=None
(HTTP 200) when the sidecar is down or hasn't been connected yet.
"""
import logging

from fastapi import FastAPI
from pydantic import BaseModel

from shared.cors import add_cors
from shared.evidence import capture_provenance
from shared.schemas import ServiceResponse

from .provider import check_number

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Argus — WhatsApp Provider",
    version="0.1.0",
    description="Checks whether a phone number is registered on WhatsApp, via a Baileys sidecar.",
)

add_cors(app)


class WhatsAppCheckRequest(BaseModel):
    number: str


@app.post("/providers/whatsapp/check", response_model=ServiceResponse, tags=["provider"])
async def whatsapp_check(request: WhatsAppCheckRequest) -> ServiceResponse:
    result = await check_number(request.number)
    return ServiceResponse(
        results=[result],
        provenance=capture_provenance("whatsapp_provider"),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "whatsapp_provider"}
