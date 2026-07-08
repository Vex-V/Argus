"""WhatsApp provider — checks if a phone number is registered on WhatsApp.

There's no way to do this from Python directly. Baileys (Node/TS) can, via a
real WhatsApp Web multi-device session, but that session has to be
established once (QR-code scan) and kept alive — it can't be spun up fresh
per request the way the maigret/holehe providers shell out or import
in-process. So the actual work happens in a standalone Node sidecar
(baileys-service/, run separately — see its module docstring and the README
for the QR-login setup) that holds the logged-in socket; this provider is a
thin HTTP proxy to it.

The sidecar only ever calls Baileys' `onWhatsApp` (a passive lookup) — no
message is ever sent to the checked number.
"""
import logging

import httpx

from shared.config import settings

log = logging.getLogger("providers.whatsapp")


async def check_number(number: str) -> dict:
    """Ask the Baileys sidecar whether `number` is registered on WhatsApp."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{settings.whatsapp_baileys_url}/check", json={"number": number})
    except httpx.HTTPError as exc:
        log.warning("whatsapp sidecar unreachable at %s: %s", settings.whatsapp_baileys_url, exc)
        return {"number": number, "exists": None, "error": "whatsapp sidecar unreachable"}

    if resp.status_code == 503:
        log.warning("whatsapp sidecar not connected yet (QR not scanned?)")
        return {"number": number, "exists": None, "error": "whatsapp sidecar not connected"}

    resp.raise_for_status()
    return resp.json()
