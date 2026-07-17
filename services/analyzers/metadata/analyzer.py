"""Image metadata (EXIF) extraction core (C11).

Pulls the embedded metadata out of an image — camera make/model, capture
timestamps, GPS coordinates, editing software, thumbnails, etc. — using
`PyExifTool`, a thin Python wrapper around Phil Harvey's `exiftool` CLI.
exiftool understands far more tags and formats (EXIF, IPTC, XMP, MakerNotes,
HEIC/RAW/video) than Pillow's EXIF reader, which is why it's the workhorse
here.

PyExifTool shells out to the `exiftool` binary, so it has to be on PATH
(`exiftool` — a Perl program, installed separately; see README). Both the
Python package and the binary are checked lazily, and everything degrades
gracefully: a missing package/binary or an unreadable image yields an empty
result with a clear error note, never a crash — matching the other analyzers.

The GPS block is called out on its own because, for SOCMINT, a geotagged
photo is often the single most operationally useful field an image carries.
"""
import logging
import os
import shutil
import tempfile

log = logging.getLogger("analyzer.metadata")

# exiftool group-qualified keys look like "EXIF:Make", "Composite:GPSLatitude".
# We match on either the full key or its bare tag name (the part after ":").


def exiftool_available() -> bool:
    """True only if both the PyExifTool package and the `exiftool` binary exist.

    PyExifTool is a wrapper — without the CLI on PATH it can't do anything, so
    the health endpoint reports the combined state.
    """
    try:
        import exiftool  # noqa: F401
    except ImportError:
        return False
    return shutil.which("exiftool") is not None


def _tag(tags: dict, *names: str):
    """First present value among `names`, matching full key or bare tag name."""
    for name in names:
        for key, val in tags.items():
            if key == name or key.split(":")[-1] == name:
                if val not in (None, ""):
                    return val
    return None


def _extract_gps(tags: dict) -> dict | None:
    """Decimal-degree GPS block, or None when the image isn't geotagged.

    We request numeric output (`-n`) so latitude/longitude come back as signed
    floats (south/west negative) rather than "12 deg 34' 56\" N" strings.
    """
    lat = _tag(tags, "Composite:GPSLatitude", "EXIF:GPSLatitude", "GPSLatitude")
    lng = _tag(tags, "Composite:GPSLongitude", "EXIF:GPSLongitude", "GPSLongitude")
    if lat is None or lng is None:
        return None
    try:
        block = {"latitude": round(float(lat), 6), "longitude": round(float(lng), 6)}
    except (TypeError, ValueError):
        return None
    alt = _tag(tags, "Composite:GPSAltitude", "EXIF:GPSAltitude", "GPSAltitude")
    if alt is not None:
        try:
            block["altitude_m"] = round(float(alt), 2)
        except (TypeError, ValueError):
            pass
    ts = _tag(tags, "Composite:GPSDateTime", "EXIF:GPSDateStamp", "GPSDateTime")
    if ts is not None:
        block["timestamp"] = str(ts)
    return block


def _normalize(tags: dict) -> dict:
    """Fold exiftool's flat tag dump into the analyzer's structured result."""
    make = _tag(tags, "EXIF:Make", "Make")
    model = _tag(tags, "EXIF:Model", "Model")
    camera = " ".join(str(x) for x in (make, model) if x) or None

    gps = _extract_gps(tags)

    result = {
        "file_type": _tag(tags, "File:FileType", "FileType"),
        "mime_type": _tag(tags, "File:MIMEType", "MIMEType"),
        "dimensions": {
            "width": _tag(tags, "File:ImageWidth", "EXIF:ExifImageWidth", "ImageWidth"),
            "height": _tag(tags, "File:ImageHeight", "EXIF:ExifImageHeight", "ImageHeight"),
        },
        "camera": {
            "make": make,
            "model": model,
            "lens": _tag(tags, "EXIF:LensModel", "Composite:LensID", "LensModel"),
            "software": _tag(tags, "EXIF:Software", "XMP:CreatorTool", "Software"),
        },
        "timestamps": {
            "created": _tag(tags, "EXIF:DateTimeOriginal", "EXIF:CreateDate", "DateTimeOriginal"),
            "modified": _tag(tags, "EXIF:ModifyDate", "File:FileModifyDate", "ModifyDate"),
        },
        "gps": gps,
        "has_gps": gps is not None,
        "tag_count": len(tags),
        "tags": tags,  # full flat dump for callers that want everything
    }

    evidence = [f"tags_extracted: {len(tags)}"]
    if camera:
        evidence.append(f"camera: {camera}")
    if result["timestamps"]["created"]:
        evidence.append(f"captured_at: {result['timestamps']['created']}")
    if result["camera"]["software"]:
        evidence.append(f"software: {result['camera']['software']}")
    if gps:
        # Geolocation is privacy-sensitive — flag it prominently.
        evidence.append(f"GPS PRESENT: {gps['latitude']}, {gps['longitude']}")
    result["evidence"] = evidence
    return result


def extract_metadata(image_bytes: bytes, filename: str | None = None) -> dict:
    """Extract embedded metadata from raw image bytes.

    Writes the bytes to a short-lived temp file (exiftool reads paths, and on
    Windows a NamedTemporaryFile can't be reopened while held), runs exiftool
    with numeric + group-qualified output, then normalizes. Returns an
    ``evidence``-bearing dict; on any failure returns an empty result carrying
    an ``error`` key rather than raising.
    """
    if not exiftool_available():
        return {
            "tags": {},
            "tag_count": 0,
            "has_gps": False,
            "evidence": ["exiftool_unavailable"],
            "error": "PyExifTool or the exiftool binary is not installed on this host.",
        }

    from exiftool import ExifToolHelper

    suffix = os.path.splitext(filename)[1] if filename else ""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(image_bytes)
        tmp.close()
        with ExifToolHelper() as et:
            # -n: numeric values (signed GPS floats); -G: group-qualified keys.
            metadata = et.get_metadata(tmp.name, params=["-n", "-G"])
        tags = metadata[0] if metadata else {}
        # SourceFile is just the temp path we fed in — drop it, it's noise.
        tags.pop("SourceFile", None)
        return _normalize(tags)
    except Exception as exc:  # noqa: BLE001 - corrupt image / exiftool failure
        log.warning("metadata extraction failed: %s", exc)
        return {
            "tags": {},
            "tag_count": 0,
            "has_gps": False,
            "evidence": ["extraction_failed"],
            "error": str(exc),
        }
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass
