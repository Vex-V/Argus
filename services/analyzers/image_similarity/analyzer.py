"""Non-face image similarity core (C7).

Perceptual hashing (pHash) to tell whether two images are the same picture —
useful for matching a reused profile banner, a shared meme, or a re-posted
photo across accounts, independent of any face. pHash is robust to resizing,
mild compression, and small edits; the Hamming distance between two hashes is
the number of differing bits (0 = identical, 64 = maximally different for a
64-bit hash).

Pillow/imagehash are imported lazily so the service boots even if they aren't
installed, matching the other analyzers. A distance <= MATCH_THRESHOLD is
treated as "likely the same image".
"""
import io
import logging

log = logging.getLogger("analyzer.image_similarity")

HASH_BITS = 64          # phash is 8x8 = 64 bits
MATCH_THRESHOLD = 10    # <= 10 differing bits → very likely the same image


def _hashes_available() -> bool:
    try:
        import imagehash  # noqa: F401
        from PIL import Image  # noqa: F401

        return True
    except ImportError:
        return False


def compute_phash(image_bytes: bytes) -> str | None:
    """Perceptual hash of an image as a hex string, or None if it can't be read."""
    try:
        import imagehash
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        return str(imagehash.phash(img))
    except ImportError:
        log.warning("imagehash/Pillow not installed — phash unavailable")
        return None
    except Exception as exc:  # noqa: BLE001 - corrupt/unsupported image
        log.warning("could not compute phash: %s", exc)
        return None


def compute_dhash(image_bytes: bytes) -> str | None:
    """Difference hash of an image as a hex string, or None if it can't be read."""
    try:
        import imagehash
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        return str(imagehash.dhash(img))
    except ImportError:
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("could not compute dhash: %s", exc)
        return None


def hamming_distance(hash_a: str, hash_b: str) -> int | None:
    """Bit distance between two hex-encoded perceptual hashes.

    imagehash subtraction yields a numpy int; cast to a native int so the
    value serializes cleanly through pydantic/JSON.
    """
    try:
        import imagehash

        return int(imagehash.hex_to_hash(hash_a) - imagehash.hex_to_hash(hash_b))
    except (ImportError, ValueError) as exc:
        log.warning("could not diff hashes: %s", exc)
        return None


def _distance_to_result(distance: int) -> dict:
    distance = int(distance)
    similarity = round(1.0 - (distance / HASH_BITS), 4)
    match = bool(distance <= MATCH_THRESHOLD)
    return {
        "phash_distance": distance,
        "similarity": similarity,
        "likely_match": match,
        "evidence": [
            f"phash_hamming_distance: {distance}",
            f"threshold: {'MATCH' if match else 'NO_MATCH'} (cutoff={MATCH_THRESHOLD})",
        ],
    }


def compare_images(image_a_bytes: bytes, image_b_bytes: bytes) -> dict:
    """Compare two images via perceptual hashing. Returns similarity + evidence.

    Degrades to a 0.0 score with an error note when either image can't be
    hashed (unreadable image, or imagehash/Pillow not installed) rather than
    raising, so callers never crash.
    """
    hash_a = compute_phash(image_a_bytes)
    hash_b = compute_phash(image_b_bytes)
    if hash_a is None or hash_b is None:
        which = []
        if hash_a is None:
            which.append("could_not_hash_image_a")
        if hash_b is None:
            which.append("could_not_hash_image_b")
        return {"similarity": 0.0, "likely_match": False, "evidence": which}

    distance = hamming_distance(hash_a, hash_b)
    if distance is None:
        return {"similarity": 0.0, "likely_match": False, "evidence": ["hash_diff_failed"]}

    result = _distance_to_result(distance)
    result["phash_a"] = hash_a
    result["phash_b"] = hash_b
    return result
