"""Argus Gateway — every provider + analyzer route on one port, one process.

Normally each service under services/{providers,analyzers}/ is its own
standalone FastAPI app on its own port (see routes.md) — that's the default
for independent development/restarts. This module instead imports every
service's FastAPI app and merges their routes into a single app, bound to
0.0.0.0 so it's reachable from other machines on the same network, not just
localhost. Handy for handing one address to someone else to poke at the
whole toolkit without them starting 14 separate processes.

Run it:
    python gateway.py
    # or, equivalently:  uvicorn gateway:app --host 0.0.0.0 --port 8000

Every functional route keeps its original path (see routes.md) — e.g.
POST /providers/maigret/search, POST /analyze/username, POST /face/detect —
so existing curl examples work identically against the gateway or a
standalone service. The one exception is /health: every service defines its
own at the same path, so those are namespaced under /health/<service> here,
and GET /health aggregates all of them (calling each in-process — no HTTP
round trips needed since everything lives in one process now).

This is purely an aggregation layer — it imports and re-registers each
service's already-defined routes rather than reimplementing anything, so
there is exactly one source of truth (services/.../main.py) per endpoint.
"""
import importlib
import logging
import socket

import uvicorn
from fastapi import FastAPI

from shared.cors import add_cors

log = logging.getLogger("gateway")

# (name used for /health/<name>, module path exposing a FastAPI `app` + `health`)
SERVICES = [
    ("maigret", "services.providers.maigret.main"),
    ("moriarty", "services.providers.moriarty.main"),
    #("telegram", "services.providers.telegram.main"),
    ("reddit", "services.providers.reddit.main"),
    ("holehe", "services.providers.holehe.main"),
    ("whatsapp", "services.providers.whatsapp.main"),
    ("yandeximage", "services.providers.yandeximage.main"),
    ("username", "services.analyzers.username.main"),
    ("facial", "services.analyzers.facial.main"),
    ("text", "services.analyzers.text.main"),
    ("timing", "services.analyzers.timing.main"),
    ("contacts", "services.analyzers.contacts.main"),
    ("content_profiler", "services.analyzers.content_profiler.main"),
    ("image_similarity", "services.analyzers.image_similarity.main"),
    ("face_pipeline", "services.analyzers.face_pipeline.main"),
]

# Framework/per-service routes that legitimately repeat across every sub-app
# and shouldn't be transplanted as-is onto the gateway.
_SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/docs/oauth2-redirect"}

app = FastAPI(
    title="Argus Gateway",
    version="0.1.0",
    description="Every provider + analyzer route merged onto one port. See routes.md.",
)
add_cors(app)

_health_fns: dict[str, callable] = {}
_owners: dict[str, str] = {}  # "METHOD /path" -> owning service name, to catch real collisions


def _mount(name: str, module_path: str) -> None:
    module = importlib.import_module(module_path)
    sub_app = module.app
    _health_fns[name] = module.health

    for route in sub_app.routes:
        path = getattr(route, "path", None)
        if path in _SKIP_PATHS:
            continue
        for method in getattr(route, "methods", None) or ():
            key = f"{method} {path}"
            if key in _owners:
                raise RuntimeError(f"route collision: {key} claimed by both {_owners[key]!r} and {name!r}")
            _owners[key] = name
        app.router.routes.append(route)

    app.add_api_route(f"/health/{name}", module.health, methods=["GET"], tags=["meta"])


for _name, _module_path in SERVICES:
    _mount(_name, _module_path)


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Aggregate health of every mounted service (in-process, no HTTP calls)."""
    per_service = {name: fn() for name, fn in _health_fns.items()}
    all_ok = all(s.get("status") == "ok" for s in per_service.values())
    return {"status": "ok" if all_ok else "degraded", "services": per_service}


def _lan_ip() -> str:
    """Best-effort LAN IP (doesn't actually send traffic — just picks a route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    lan_ip = _lan_ip()
    print("Argus Gateway — all routes on one port (see routes.md for the full list)")
    print(f"  http://{lan_ip}:8000        <- reachable from other devices on this network")
    print("  http://localhost:8000      <- this machine")
    print("  http://localhost:8000/docs <- interactive API docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
