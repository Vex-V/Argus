"""Face reverse-search pipeline service (port 8017).

Detects a face, reverse-image-searches it via Yandex (yandeximage provider),
and scores facial similarity against each result (facial analyzer) — both
called in-process. Needs the same dependencies as those two services
(facenet-pytorch model + Playwright/chromium) for real results; degrades to
a clear no-match reason (HTTP 200) otherwise.

Unlike every other endpoint in this project, this one does not return the
ServiceResponse JSON envelope: the useful output is a set of matched images,
which are saved to disk and served statically, and the endpoint responds
with a plain-text summary (title/domain/similarity/source-URL plus a
download URL) referencing them — a client downloads the images it actually
wants instead of receiving every match's bytes inline on every call.
"""
import logging

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from shared.cors import add_cors

from .pipeline import OUTPUT_DIR, run_pipeline

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Argus — Face Reverse-Search Pipeline",
    version="0.1.0",
    description="Detect a face, reverse-image-search it via Yandex, and score facial similarity against each result.",
)

add_cors(app)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FILES_PATH = "/analyze/face-pipeline/files"
app.mount(FILES_PATH, StaticFiles(directory=OUTPUT_DIR), name="face_pipeline_files")


@app.post("/analyze/face-pipeline", response_class=PlainTextResponse, tags=["analyzer"])
async def face_pipeline(request: Request, file: UploadFile = File(...), top_n: int = 10) -> PlainTextResponse:
    image_bytes = await file.read()
    result = await run_pipeline(image_bytes, top_n=top_n)

    if not result.get("face_detected"):
        return PlainTextResponse("No face detected in the uploaded image.\n")
    if result.get("error"):
        return PlainTextResponse(f"Face detected (confidence {result['confidence']}), but: {result['error']}\n")

    files_base = f"{str(request.base_url).rstrip('/')}{FILES_PATH}"

    lines = [
        f"Detected face confidence: {result['confidence']}",
        f"Source face crop: {files_base}/{result['source_face_relative_path']}",
        f"Yandex results returned: {result['results_returned']}  |  scored matches: {len(result['matches'])}",
        "",
    ]
    for rank, m in enumerate(result["matches"], start=1):
        lines.append(f"{rank}. {m['similarity_pct']}%  {m['title']}  ({m['domain']})")
        lines.append(f"   source page: {m['url']}")
        lines.append(f"   image:       {files_base}/{m['relative_path']}")
        lines.append("")

    summary_text = "\n".join(lines)
    (OUTPUT_DIR / result["run_id"] / "summary.txt").write_text(summary_text, encoding="utf-8")

    return PlainTextResponse(summary_text)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "face_pipeline_analyzer"}
