"""Evidence utilities — deterministic hashing and provenance capture.

Every artifact stored by Argus carries a SHA-256 content hash and a
capture timestamp so the chain of custody is verifiable later.
"""
import hashlib
from datetime import datetime, timezone


def hash_content(content: str | bytes) -> str:
    """SHA-256 hash of any content, returned as a hex string."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def entity_hash(platform: str, identifier: str) -> str:
    """Deterministic hash id for an entity (platform + identifier)."""
    return hash_content(f"{platform}:{identifier}")


def capture_provenance(source_service: str, raw_response: dict | None = None) -> dict:
    """Standard provenance block attached to every record."""
    return {
        "source_service": source_service,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": hash_content(str(raw_response)) if raw_response else None,
    }


def now_utc() -> datetime:
    """Timezone-aware current UTC timestamp."""
    return datetime.now(timezone.utc)
