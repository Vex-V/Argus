"""Yandex reverse image search provider service (port 8026).

On-demand reverse image search via a headless Chromium (Playwright) driving
Yandex Images — see provider.py's docstring for why Yandex instead of Google.
Stateless: returns discovered source pages, does not persist. Degrades to an
empty result set (HTTP 200) if the browser/Playwright isn't available or the
search fails for any reason (network, layout change upstream, etc.).
"""
import logging

from fastapi import FastAPI, File, UploadFile

from shared.cors import add_cors
from shared.evidence import capture_provenance
from shared.schemas import ServiceResponse

from .provider import reverse_image_search

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Argus — Yandex Reverse Image Search Provider",
    version="0.1.0",
    description="Finds pages containing a given image via Yandex Images (headless Chromium).",
)

add_cors(app)


@app.post("/providers/yandeximage/search", response_model=ServiceResponse, tags=["provider"])
async def yandeximage_search(file: UploadFile = File(...), top_n: int = 10) -> ServiceResponse:
    image_bytes = await file.read()
    results = await reverse_image_search(
        image_bytes,
        top_n=top_n,
        filename=file.filename or "image.jpg",
        content_type=file.content_type or "image/jpeg",
    )
    return ServiceResponse(
        results=results,
        provenance=capture_provenance("yandeximage_provider"),
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "yandeximage_provider"}
