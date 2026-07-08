# Argus — Build Status

_Last updated: 2026-07-04. Slimmed to **providers + analyzers** only._

Argus was slimmed from an 18-service SOCMINT platform down to two service
groups: on-demand **collection providers** and mostly-stateless **analyzers**.
The orchestration/persistence/UI layer (driver, store, auth, scrapers, breach,
translation, event-correlation, report, infiltrator, audit, React frontend)
was removed. PostgreSQL still runs in Docker; every provider and 5 of the 7
analyzers are fully stateless, but **facial** and **image_similarity** use
Postgres + pgvector as their own search index (`/face/embed`, `/image/search`
write to the `images` table). See [ENDPOINTS.md](ENDPOINTS.md) for exact
request/response shapes of every route.

## Legend
- ✅ **Live** — exercised end-to-end in this environment.
- 🧪 **Test-only** — covered by pytest (pure-logic / offline paths).
- 🟡 **Degrades** — wired; external dependency absent, returns empty/fallback by design.
- ⏸️ **Not tested** — implemented, needs a credential/human step to verify live.

## Summary
- **pytest: 67 passed, 2 skipped** (skips = optional heavy-ML branches).
- **15 service apps import + serve** (`/health` = 200); `python scripts/health_check.py`.
- **Layout:** `services/providers/` (7) + `services/analyzers/` (8).
- **`gateway.py`** merges all 22 functional routes onto one `0.0.0.0`-bound port (8000) for LAN access — see routes.md.

## Providers — `services/providers/` (each its own FastAPI service)
| Provider | Port | Endpoint | Engine | Status |
|---|---|---|---|---|
| Maigret | 8020 | `POST /providers/maigret/search {username}` | maigret CLI (subprocess) | ✅ Live (empty if CLI absent) |
| Moriarty | 8021 | `POST /providers/moriarty/lookup {phone}` | Moriarty-Project (in-process) | ✅ Live geo/spam/links/comments |
| Telegram | 8022 | `POST /providers/telegram/fetch {channels}` | Telethon | ⏸️ Needs one-time SMS login |
| Reddit | 8023 | 4 routes: `/subreddit` `/user/posts` `/user/comments` `/comments` | RedScrapsLib + browser cookies | ✅ Live (all 4 verified with real data) |
| Holehe | 8024 | `POST /providers/holehe/search {email}` | holehe clone (in-process, trio) | ✅ Live (verified real hits) |
| WhatsApp | 8025 | `POST /providers/whatsapp/check {number}` | Baileys sidecar (Node, HTTP proxy) | ✅ Live (QR-linked, verified real check) |
| Yandex Image | 8026 | `POST /providers/yandeximage/search` (multipart + top_n) | headless Chromium (Playwright) + Yandex Images | ✅ Live (verified real results) |
| Moriarty FindOwner (Truecaller) | — | (part of moriarty lookup) | Playwright + Google login | ⏸️ Credential-gated (burner account) |

All providers are **stateless** and return a `ServiceResponse`; each degrades to
an empty/`error` result (HTTP 200) when its tool/credentials are missing.

## Analyzers — `services/analyzers/` (each its own FastAPI service)
| Analyzer | Port | Engine | Status |
|---|---|---|---|
| Username | 8010 | jellyfish (Jaro-Winkler + leet) | ✅ Live |
| Facial | 8011 | facenet-pytorch (lazy) | ✅ Live / 🟡 without model — `/face/embed`,`/face/search` write/read Postgres; `/face/detect` (bbox+crop) verified live against imgs/images132.jpg |
| Text | 8012 | stylometry + sentence-transformers (lazy) | ✅ Live (stylometry) / 🟡 semantic |
| Timing | 8013 | pure-Python temporal overlap | ✅ Live |
| Contacts | 8014 | Jaccard + weighted overlap | ✅ Live |
| Content profiler | 8015 | TF-IDF + VADER (+ Ollama tone) | ✅ Live / 🟡 tone without Ollama |
| Image similarity | 8016 | ImageHash (pHash) | ✅ Live — `/image/search` writes/reads Postgres |
| Face Pipeline | 8017 | facial (in-process) + yandeximage (in-process) | ✅ Live — verified end-to-end (standalone + via gateway.py); returns plain text + saves matched images, not JSON |

## Removed in the slim-down
Driver, store, auth, active/passive scrapers, breach, translation, event
correlation, report, infiltrator, audit services; the React/Vite frontend;
the enrichment providers behindtheemail / facecheck / fingerprint.to /
igdetective / whatsapp / playwright; Redis + OpenSearch from Docker; and the
`shared.{auth,audit,search}` modules.

## Known gaps / human steps
- **Telegram** — one-time interactive Telethon login (phone + SMS) to create a session file.
- **Reddit** — log into reddit.com in the browser named by `REDDIT_COOKIE_BROWSER` first.
  Known upstream quirk (verified live): RedScrapsLib's `get_comments` (the
  `/providers/reddit/comments` route) reports `CommentID`/`ParentID` equal to
  the post's own ID for every comment in the thread — don't rely on
  `raw_data.comment_id` there to identify a specific comment; `hash_id` is
  keyed on thread position instead and is safe to dedupe on.
- **Maigret** — installed separately (`pip install maigret`), pins many deps.
- **Holehe** — local clone at `holehe/`, imported in-process (not pip-installed);
  a full scan takes ~20-60s (~120 site checks concurrently, capped at 60s wall-clock).
- **WhatsApp** — needs its Node sidecar (`services/providers/whatsapp/baileys-service/`)
  started and QR-linked once (see README); the Python provider on :8025 is just
  a proxy and degrades to `exists: null` if the sidecar is down or not yet
  connected. Verified end-to-end live: QR-linked a real device, sidecar reported
  `connected: true`, and a real check through the HTTP endpoint returned a real
  `exists`/`jid` result. Note: an earlier, heavier whatsapp provider existed
  pre-slim-down (see "Removed in the slim-down" above) — this is a fresh,
  narrowly-scoped reimplementation (existence-check only, via Baileys, no messaging).
- **Yandex Image** — needs `playwright install chromium` (playwright itself is
  already a dependency for Moriarty's FindOwner). Originally scoped for Google
  reverse image search; swapped to Yandex after confirming live that Google's
  Lens backend serves an immediate CAPTCHA to headless automation (persisted
  even headed + with basic anti-detection JS). Extracts results from Yandex's
  own embedded React hydration state rather than scraping rendered DOM, which
  should be more resilient to frontend redesigns than CSS-selector scraping.
- **Moriarty FindOwner** — needs a burner Google account in `.env`.
- **Optional heavy deps** for richer analyzer signals: `sentence-transformers`,
  `facenet-pytorch`, a running **Ollama** (content-profiler tone). See `requirements-ml.txt`.

## Run it
```bash
docker compose up -d              # PostgreSQL only
alembic upgrade head              # needed for facial/image_similarity's DB-backed search endpoints
bash scripts/start_all.sh         # or `make dev`
python scripts/health_check.py    # expect 15/15
```
