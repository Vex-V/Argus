"""Facial similarity core (C6).

Extracts 512-dim FaceNet embeddings via facenet-pytorch — MTCNN detects and
aligns the face (defaulting to the largest one when several are present),
InceptionResnetV1 (pretrained on VGGFace2) embeds it. Both load lazily on
first use so the service starts even before the pretrained weights (~110MB)
are downloaded, or if torch / facenet-pytorch aren't installed.

Replaces InsightFace: insightface's onnxruntime/numpy pins have no Python
3.13 wheel and it tends to need a from-source build on Windows. torch and
facenet-pytorch's own code both work fine on 3.13; only facenet-pytorch's
*declared* dependency pins (numpy<2, torch<2.3) are stale, so it's installed
with --no-deps against a modern torch/torchvision/numpy stack instead — see
requirements-ml.txt.
"""
import base64
import io
import logging
from pathlib import Path

import numpy as np

from shared.evidence import hash_content

log = logging.getLogger("analyzer.facial")

# Extracted face crops from /face/detect are saved here, named by content hash
# of the *source* image so repeat detections on the same image overwrite
# rather than pile up. Gitignored — this is local scratch output, not tracked.
EXTRACTED_FACES_DIR = Path(__file__).resolve().parent / "extracted_faces"

_mtcnn = None
_resnet = None
_load_error: str | None = None


def get_model():
    """Lazily construct the MTCNN detector + InceptionResnetV1 embedder (once)."""
    global _mtcnn, _resnet, _load_error
    if _resnet is not None:
        return _mtcnn, _resnet
    if _load_error is not None:
        return None, None
    try:
        import torch
        from facenet_pytorch import MTCNN, InceptionResnetV1

        device = "cuda" if torch.cuda.is_available() else "cpu"
        mtcnn = MTCNN(image_size=160, margin=0, select_largest=True, device=device)
        resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)
        _mtcnn, _resnet = mtcnn, resnet
        log.info("facenet-pytorch (MTCNN + InceptionResnetV1/vggface2) loaded on %s", device)
        return _mtcnn, _resnet
    except Exception as exc:  # noqa: BLE001 - model/deps may be unavailable
        _load_error = str(exc)
        log.warning("facenet-pytorch unavailable: %s", exc)
        return None, None


def model_available() -> bool:
    """Whether the model can be used (triggers a lazy load on first call)."""
    return get_model()[1] is not None


def is_loaded() -> bool:
    """Cheap check for /health — does NOT trigger a model load."""
    return _resnet is not None


def get_face_embedding(image_bytes: bytes) -> np.ndarray | None:
    """Return the 512-dim embedding of the largest face, or None if no face."""
    mtcnn, resnet = get_model()
    if resnet is None:
        return None
    import torch
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    try:
        face = mtcnn(img)
    except ValueError:
        # MTCNN's internal image pyramid raises instead of returning None for
        # degenerate input (e.g. images smaller than min_face_size) — treat
        # that the same as "no face detected" rather than a 500.
        face = None
    if face is None:
        return None
    with torch.no_grad():
        embedding = resnet(face.unsqueeze(0))
    return embedding.squeeze(0).cpu().numpy()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def detect_face(image_bytes: bytes, margin: int = 20) -> dict | None:
    """Detect the largest face, draw a bounding box, and extract the face crop.

    Reuses the same MTCNN instance get_face_embedding() uses (select_largest=True,
    so the first box back from .detect() is already the largest). Returns None if
    the model isn't available or no face is found — never raises.
    """
    mtcnn, _ = get_model()
    if mtcnn is None:
        return None

    from PIL import Image, ImageDraw

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    try:
        boxes, probs = mtcnn.detect(img)
    except ValueError:
        # Same degenerate-input quirk as get_face_embedding (e.g. image smaller
        # than min_face_size) — treat as "no face detected", not a crash.
        boxes, probs = None, None

    if boxes is None or len(boxes) == 0:
        return None

    x1, y1, x2, y2 = boxes[0].tolist()
    confidence = float(probs[0])

    annotated = img.copy()
    ImageDraw.Draw(annotated).rectangle([x1, y1, x2, y2], outline=(0, 255, 0), width=3)

    crop_box = (
        max(int(x1) - margin, 0),
        max(int(y1) - margin, 0),
        min(int(x2) + margin, img.width),
        min(int(y2) + margin, img.height),
    )
    extracted = img.crop(crop_box)

    EXTRACTED_FACES_DIR.mkdir(parents=True, exist_ok=True)
    extracted_path = EXTRACTED_FACES_DIR / f"{hash_content(image_bytes)}.png"
    extracted.save(extracted_path, format="PNG")

    return {
        "face_detected": True,
        "confidence": round(confidence, 4),
        "box": {"x1": round(x1, 1), "y1": round(y1, 1), "x2": round(x2, 1), "y2": round(y2, 1)},
        "annotated_image_base64": _encode_png(annotated),
        "extracted_face_base64": _encode_png(extracted),
        "extracted_face_path": str(extracted_path),
    }


def _encode_png(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
