"""Offline tests for the image metadata (EXIF) analyzer.

Exercise the pure normalization/GPS-parsing paths directly (no exiftool
needed) plus the graceful-degradation contract when the exiftool binary /
PyExifTool aren't installed.
"""
import io
import struct

import pytest

from services.analyzers.metadata.analyzer import (
    _extract_gps,
    _normalize,
    _tag,
    exiftool_available,
    extract_metadata,
)


# --- _tag: full-key and bare-tag matching ---------------------------------
def test_tag_matches_group_qualified_key():
    tags = {"EXIF:Make": "Apple", "EXIF:Model": "iPhone 12"}
    assert _tag(tags, "Make") == "Apple"
    assert _tag(tags, "EXIF:Model") == "iPhone 12"


def test_tag_skips_empty_values_and_returns_none():
    tags = {"EXIF:Make": "", "EXIF:Model": None}
    assert _tag(tags, "Make", "Model") is None


# --- GPS parsing ----------------------------------------------------------
def test_extract_gps_decimal_block():
    tags = {
        "Composite:GPSLatitude": 48.8583,
        "Composite:GPSLongitude": 2.2945,
        "Composite:GPSAltitude": 33.5,
    }
    gps = _extract_gps(tags)
    assert gps == {"latitude": 48.8583, "longitude": 2.2945, "altitude_m": 33.5}


def test_extract_gps_none_when_absent():
    assert _extract_gps({"EXIF:Make": "Apple"}) is None


def test_extract_gps_none_on_unparseable_coords():
    assert _extract_gps({"GPSLatitude": "N/A", "GPSLongitude": "N/A"}) is None


# --- normalization + evidence --------------------------------------------
def test_normalize_flags_gps_in_evidence():
    tags = {
        "EXIF:Make": "Apple",
        "EXIF:Model": "iPhone 12",
        "EXIF:DateTimeOriginal": "2024:01:02 03:04:05",
        "Composite:GPSLatitude": 48.8583,
        "Composite:GPSLongitude": 2.2945,
    }
    result = _normalize(tags)
    assert result["has_gps"] is True
    assert result["camera"]["make"] == "Apple"
    assert result["tag_count"] == 5
    assert any("GPS PRESENT" in e for e in result["evidence"])
    assert any("captured_at" in e for e in result["evidence"])


def test_normalize_without_gps():
    result = _normalize({"File:FileType": "PNG"})
    assert result["has_gps"] is False
    assert result["gps"] is None
    assert result["file_type"] == "PNG"


# --- graceful degradation -------------------------------------------------
def test_extract_metadata_degrades_without_exiftool():
    """When exiftool isn't installed, return an error result, never raise."""
    if exiftool_available():
        pytest.skip("exiftool is installed on this host; degradation path not exercised")
    result = extract_metadata(b"\x89PNG\r\n\x1a\n", "x.png")
    assert result["tag_count"] == 0
    assert result["has_gps"] is False
    assert "error" in result


@pytest.mark.skipif(not exiftool_available(), reason="exiftool binary not installed")
def test_extract_metadata_reads_a_real_png():
    """1x1 PNG: exiftool should at least report file type and dimensions."""
    png = _minimal_png()
    result = extract_metadata(png, "pixel.png")
    assert "error" not in result
    assert result["tag_count"] > 0
    assert result["file_type"] in ("PNG", None)


def _minimal_png() -> bytes:
    """A valid 1x1 opaque-black PNG, built by hand (no Pillow dependency)."""
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8-bit, truecolor
    raw = b"\x00\x00\x00\x00"  # one filtered scanline: filter 0 + RGB black
    idat = zlib.compress(raw)
    buf = io.BytesIO()
    buf.write(sig)
    buf.write(chunk(b"IHDR", ihdr))
    buf.write(chunk(b"IDAT", idat))
    buf.write(chunk(b"IEND", b""))
    return buf.getvalue()
