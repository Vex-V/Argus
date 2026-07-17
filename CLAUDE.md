# Argus — repo guide

Slim SOCMINT toolkit: independent FastAPI micro-services, no orchestrator, no
UI, no shared datastore. Two kinds of service — **providers** (collect records)
and **analyzers** (score/match inputs). You call each endpoint directly and
consume its JSON. Almost everything is stateless; the only exceptions are the
`facial` and `image_similarity` analyzers, which use Postgres + pgvector as a
search index.

## Layout

```
services/
  providers/<name>/    on-demand collection, one service each (ports 8020–8030)
  analyzers/<name>/    matching/scoring, one service each (ports 8010–8018)
shared/                schemas, config, evidence (hashing/provenance), cors, db, models
external/<Tool>/       local clones of upstream OSINT tools (gitignored) imported in-process
tests/                 offline provider + analyzer tests (no network, no DB)
gateway.py             merges every service's routes onto one port (8000)
scripts/               start_all.sh (launch all), health_check.py
routes.md              full request/response shapes for every route
README.md              setup + per-provider "human tasks" (creds, clones)
```

## Service anatomy (every provider/analyzer is the same 3 files)

- `__init__.py` — empty package marker.
- `provider.py` (or analyzer logic) — the real work + **normalization** into the
  shared schema. Pure/testable; no FastAPI here.
- `main.py` — FastAPI `app`, the route(s), and a `GET /health`. Thin: parse
  request → call provider fn → wrap in `ServiceResponse`.

## Conventions that matter

- **Wire envelope**: providers return `ServiceResponse` (`results: list[dict]`,
  `provenance`, `errors`) from `shared/schemas.py`. Build provenance with
  `capture_provenance("<service>_provider")` from `shared/evidence.py`.
- **Graceful degradation, always HTTP 200**: if a tool/clone/credential is
  missing, log it, put a note in `errors`, and return an empty/partial result —
  never raise, never crash. Services must start and respond offline.
- **In-process upstream clones**: tools like holehe/ignorant/moriarty/
  social-analyzer/**GHunt** are `git clone`d into `external/` (not tracked) and
  imported by adding their root to `sys.path` — not pip-installed. Each has a
  `<tool>_project_path` setting (default `external/<Tool>`) in `shared/config.py`.
  trio-based tools (holehe/ignorant) run on a background thread; async tools
  (GHunt) are awaited directly.
- **Config**: one pydantic-settings `Settings` singleton in `shared/config.py`,
  read from `.env` (see `.env.example`). Every service URL/port + per-tool paths
  and credentials live there.
- **Adding a service** means touching, in order: `services/.../` (the 3 files),
  `shared/config.py` (URL + any paths), `gateway.py` (`SERVICES` list),
  `scripts/start_all.sh` + `scripts/health_check.py`, `requirements.txt`,
  `README.md` + `routes.md` + `.env.example`, and a test in `tests/`.
- **Two run modes**: each service standalone on its own port
  (`uvicorn services.providers.<name>.main:app --port <port>`), or all of them
  merged via `python gateway.py` on `:8000` (paths unchanged; `/health` becomes
  `/health/<service>`).

## Environment

- Windows + Python 3.13, venv at `.venv/`. Run tools with
  `./.venv/Scripts/python.exe`, not a bare `python`/`uvicorn`.
- Some upstream clones print emoji banners that crash on the cp1252 codepage —
  prefix `PYTHONUTF8=1` when running them.
- `pytest tests/ -v` is fully offline (no Docker/Postgres needed).

## Ports

Providers 8020 maigret · 8021 moriarty · 8022 telegram · 8023 reddit ·
8024 holehe · 8025 whatsapp · 8026 yandeximage · 8027 whatsmyname ·
8028 ignorant · 8029 socialanalyzer · 8030 ghunt.
Analyzers 8010 username · 8011 facial · 8012 text · 8013 timing ·
8014 contacts · 8015 content_profiler · 8016 image_similarity · 8017 face_pipeline ·
8018 metadata.
