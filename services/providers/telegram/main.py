"""Telegram provider service (port 8022).

On-demand fetch of recent messages from public channels. Stateless: returns
Account + Post records, does not persist. Returns an empty result set
(HTTP 200) when Telegram credentials are not configured.
"""
import logging

from fastapi import FastAPI
from pydantic import BaseModel, Field

from shared.cors import add_cors
from shared.evidence import capture_provenance
from shared.schemas import ServiceResponse

from .provider import fetch

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Argus — Telegram Provider",
    version="0.1.0",
    description="On-demand fetch of recent messages from public Telegram channels.",
)

add_cors(app)


class TelegramFetchRequest(BaseModel):
    channels: list[str] = Field(default_factory=list)


@app.post("/providers/telegram/fetch", response_model=ServiceResponse, tags=["provider"])
async def telegram_fetch(request: TelegramFetchRequest) -> ServiceResponse:
    records = await fetch(request.channels)
    return ServiceResponse(
        results=[r.model_dump(mode="json") for r in records],
        provenance=capture_provenance("telegram_provider"),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "telegram_provider"}
