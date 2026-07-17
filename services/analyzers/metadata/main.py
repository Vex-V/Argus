"""C11 — Image Metadata (EXIF) service (port 8018).

Extracts embedded metadata from an uploaded image via PyExifTool: camera
make/model, capture timestamps, GPS coordinates, editing software, and the
full flat tag dump. Degrades gracefully (clear error, no crash) when the
exiftool binary/PyExifTool aren't installed or an image can't be parsed.
"""
import logging

from fastapi import FastAPI, File, UploadFile

from shared.cors import add_cors
from shared.evidence import capture_provenance
from shared.schemas import ServiceResponse

from .analyzer import exiftool_available, extract_metadata

logging.basicConfig(level=logging.INFO)
app = FastAPI(
    title="Argus — Image Metadata",
    version="0.1.0",
    description="C11: EXIF/IPTC/XMP metadata + GPS extraction via PyExifTool.",
)
add_cors(app)


@app.post("/analyze/metadata", response_model=ServiceResponse, tags=["analyzer"])
async def metadata(file: UploadFile = File(...)) -> ServiceResponse:
    image_bytes = await file.read()
    result = extract_metadata(image_bytes, file.filename)
    errors = [result["error"]] if "error" in result else []
    return ServiceResponse(
        results=[result],
        provenance=capture_provenance("metadata_analyzer"),
        errors=errors,
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "metadata_analyzer", "exiftool_available": exiftool_available()}
