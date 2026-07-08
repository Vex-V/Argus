# Argus

A slim SOCMINT (Social Media Intelligence) toolkit: a set of **collection
providers** and **matching analyzers**, each a small independent FastAPI
service. There is no orchestrator, no data store, and no UI — you call the
provider/analyzer endpoints directly and consume the JSON they return.

Providers fetch and return records; analyzers score inputs and return a
result. Almost every service is **stateless** and persists nothing. The two
exceptions are the **facial** and **image_similarity** analyzers, which use
PostgreSQL + pgvector as their own search index (`/face/embed` and
`/image/search` upsert embeddings/hashes into the `images` table so later
`/face/search` / `/image/search` calls can match against them) — see
[ENDPOINTS.md](ENDPOINTS.md) for exact request/response shapes. PostgreSQL
runs in Docker for this purpose.

## Layout

```
services/
  providers/     on-demand collection (each its own service)
    maigret/     :8020  username enumeration        — maigret CLI (subprocess)
    moriarty/    :8021  phone OSINT                  — Moriarty-Project (in-process)
    telegram/    :8022  fetch public channel messages— Telethon
    reddit/      :8023  subreddit/user posts+comments — RedScrapsLib + browser cookies
    holehe/      :8024  email registration checks     — holehe clone (in-process)
    whatsapp/    :8025  WhatsApp registration check    — Baileys sidecar (Node, HTTP proxy)
    yandeximage/ :8026  reverse image search           — Yandex Images (headless Chromium)
  analyzers/     matching/scoring (each its own service; facial + image_similarity use Postgres as a search index)
    username/    :8010  Jaro-Winkler + leet          — jellyfish
    facial/      :8011  face-embedding similarity    — facenet-pytorch (lazy)
    text/        :8012  stylometry + semantic        — sentence-transformers (lazy)
    timing/      :8013  posting-time histograms      — pure Python
    contacts/    :8014  follower/contact overlap     — pure Python
    content_profiler/ :8015  keywords/sentiment/tone — TF-IDF + VADER (+ Ollama)
    image_similarity/ :8016  perceptual hash (pHash) — ImageHash
    face_pipeline/     :8017  detect+crop a face, reverse-search it via Yandex,
                              score facial similarity per result — chains facial + yandeximage in-process
shared/          schemas, ORM models, db, config, evidence, cors
migrations/      Alembic schema + pgvector (standby infra)
Moriarty-Project/ local clone (not tracked; see Setup) whose Investigation/ modules the moriarty provider imports
holehe/          local clone (not tracked; see Setup) whose modules/ site-checkers the holehe provider imports
services/providers/whatsapp/baileys-service/  Node/TS sidecar holding the Baileys WhatsApp session
tests/           offline provider + analyzer tests
requirements-ml.txt  optional heavy ML deps for the facial/text analyzers
```

## Endpoints

| Service | Endpoint | Body |
|---|---|---|
| Maigret | `POST /providers/maigret/search` | `{"username": "..."}` |
| Moriarty | `POST /providers/moriarty/lookup` | `{"phone": "+91..."}` |
| Telegram | `POST /providers/telegram/fetch` | `{"channels": ["..."]}` |
| Reddit | `POST /providers/reddit/subreddit` | `{"subreddits": ["..."]}` |
| Reddit | `POST /providers/reddit/user/posts` | `{"usernames": ["..."]}` |
| Reddit | `POST /providers/reddit/user/comments` | `{"usernames": ["..."]}` |
| Reddit | `POST /providers/reddit/comments` | `{"posts": [{"subreddit": "...", "post_id": "..."}]}` |
| Holehe | `POST /providers/holehe/search` | `{"email": "..."}` |
| WhatsApp | `POST /providers/whatsapp/check` | `{"number": "..."}` |
| Yandex Image | `POST /providers/yandeximage/search` | multipart `file` + query `top_n` |
| Username | `POST /analyze/username` | `{"username_a": "...", "username_b": "..."}` |
| Facial | `POST /face/compare`, `/face/detect`, `/face/embed`†, `/face/search`† | `{"image_a": "<b64>", "image_b": "<b64>"}` (compare) |
| Text | `POST /analyze/text-similarity` | `{"texts_a": [...], "texts_b": [...]}` |
| Timing | `POST /analyze/timing` | `{"timestamps_a": [...], "timestamps_b": [...]}` |
| Contacts | `POST /analyze/contacts` | `{"contacts_a": [...], "contacts_b": [...]}` |
| Content profiler | `POST /analyze/profile-content` | `{"posts": [...], "platform": "..."}` |
| Image similarity | `POST /image/compare`, `/image/search`† | multipart image file(s) |
| Face Pipeline | `POST /analyze/face-pipeline`‡ | multipart `file` + query `top_n` |

† writes to / reads from PostgreSQL (the `images` table) — every other
endpoint is stateless. ‡ returns a plain-text summary instead of JSON, with
download links for the matched images (see below). Full request/response
shapes for every route, including these multipart/DB-backed/plain-text ones,
are in **[ENDPOINTS.md](ENDPOINTS.md)**.

Every service also exposes `GET /health` and interactive docs at `/docs`.
Providers return a `ServiceResponse` (`results`, `provenance`, `errors`) and
degrade to an empty/`error` result (HTTP 200) when their tool or credentials
are absent — nothing crashes offline.

## Prerequisites

- Docker + Docker Compose (for PostgreSQL only)
- Python 3.11–3.13 (verified on 3.13 / Windows)
- Node.js 20+ (only for the WhatsApp provider's Baileys sidecar)

## Setup

```bash
# 1. Start infrastructure (PostgreSQL + pgvector — standby only)
docker compose up -d

# 2. Python environment
python -m venv .venv
# Windows:  .venv\Scripts\activate     |  POSIX:  source .venv/bin/activate
pip install -r requirements.txt

# 3. Config
cp .env.example .env          # fill in credentials you have

# 4. Create the DB schema — required only for the facial/image_similarity
#    analyzers' /face/search and /image/search (they use Postgres+pgvector as
#    a search index). Every other endpoint works without this.
alembic upgrade head
```

## Run the services

`bash scripts/start_all.sh` launches all 15 (or `make dev`). Neither starts the
WhatsApp Baileys sidecar (Node) — see [Provider setup](#provider-setup-human-tasks)
below, it needs an interactive terminal for the one-time QR-code login. On
Windows, run each in its own terminal:

```bash
uvicorn services.providers.maigret.main:app          --port 8020 --reload
uvicorn services.providers.moriarty.main:app         --port 8021 --reload
uvicorn services.providers.telegram.main:app         --port 8022 --reload
uvicorn services.providers.reddit.main:app           --port 8023 --reload
uvicorn services.providers.holehe.main:app           --port 8024 --reload
uvicorn services.providers.whatsapp.main:app         --port 8025 --reload
uvicorn services.providers.yandeximage.main:app      --port 8026 --reload
uvicorn services.analyzers.username.main:app         --port 8010 --reload
uvicorn services.analyzers.facial.main:app           --port 8011 --reload
uvicorn services.analyzers.text.main:app             --port 8012 --reload
uvicorn services.analyzers.timing.main:app           --port 8013 --reload
uvicorn services.analyzers.contacts.main:app         --port 8014 --reload
uvicorn services.analyzers.content_profiler.main:app --port 8015 --reload
uvicorn services.analyzers.image_similarity.main:app --port 8016 --reload
uvicorn services.analyzers.face_pipeline.main:app    --port 8017 --reload
```

`python scripts/health_check.py` confirms all 15 are up (expect 15/15; this
doesn't check the WhatsApp sidecar itself, only the Python proxy in front of it).

**Or run everything on one network-reachable port:** `python gateway.py` (or
`make gateway`) merges every route above into a single process bound to
`0.0.0.0:8000` — other devices on the same network can hit it at
`http://<your-lan-ip>:8000/...`, and `http://<host>:8000/docs` lists every
route in one place. See [routes.md](routes.md) for the exact path list and
how `/health` is namespaced per-service on the gateway.

## Provider setup (human tasks)

The services start and degrade gracefully without these; complete them to get
live results.

1. **Maigret** — `pip install maigret`, then verify `maigret testuser123
   --top-sites 50`. Installed separately from `requirements.txt` because it pins
   many transitive deps.
2. **Telegram** — create API creds at <https://my.telegram.org/apps>, set
   `TELEGRAM_API_ID/HASH` in `.env`. The first Telethon run prompts once for
   phone + SMS code and writes a session file.
3. **Reddit** — RedScrapsLib scrapes via a cookie-authenticated browser session
   (Reddit's official API key issuance is gated). Log into reddit.com in the
   browser named by `REDDIT_COOKIE_BROWSER` first. Its bundled .NET assembly
   needs the .NET runtime installed separately.
4. **Moriarty** — clone `git clone https://github.com/AzizKpln/Moriarty-Project`
   into the repo root (not tracked here — see `.gitignore`). The provider
   imports its `Investigation/` modules in-process; no install needed.
   `MORIARTY_PROJECT_PATH` overrides the default location. FindOwner
   (Truecaller via Google login) is optional and credential-gated — set
   `MORIARTY_GOOGLE_EMAIL/PASSWORD` to a disposable/burner account and
   `playwright install firefox`.
5. **Holehe** — clone `git clone https://github.com/megadose/holehe` into the
   repo root (not tracked here — see `.gitignore`). The provider imports its
   `modules/` site-checkers in-process; no install needed (its own runtime
   deps — trio, termcolor, tqdm, colorama — are in `requirements.txt`).
   `HOLEHE_PROJECT_PATH` overrides the default location.
6. **WhatsApp** — needs Node.js 20+ installed separately (not part of the
   Python env). The Python provider (`:8025`) is just a proxy; the actual
   WhatsApp connection lives in a Node sidecar that has to be started and
   logged in once:
   ```bash
   cd services/providers/whatsapp/baileys-service
   npm install
   npm start
   ```
   On first run there's no session yet, so a QR code prints straight to that
   terminal. Open WhatsApp on the phone you want the checks to run as →
   **Settings → Linked Devices → Link a Device** → scan it. This links a
   device to that account, same as WhatsApp Web/Desktop — it is *your*
   account doing the checking, not an anonymous one. Once scanned, session
   credentials are saved to `baileys-service/auth_state/` (gitignored — it's
   equivalent to a login token, treat it like one) so restarts reconnect
   without rescanning, until you unlink the device or delete that folder.

   The sidecar only ever calls Baileys' passive `onWhatsApp` lookup — nothing
   in it can send a message. That said, it's still real automation against
   WhatsApp's unofficial web protocol from your real account: keep request
   volume reasonable, since heavy automated use of a linked-device session is
   the kind of pattern WhatsApp's abuse detection can flag or restrict.
   `WHATSAPP_BAILEYS_URL` in `.env` overrides the sidecar's URL if you run it
   on a different port/host.
7. **Yandex Image** — no setup needed beyond `requirements.txt` (uses the
   `playwright` already installed for Moriarty's FindOwner) plus one browser
   binary: `playwright install chromium`. This provider was originally scoped
   for Google reverse image search, but Google's Lens backend serves an
   immediate CAPTCHA to headless automation (verified live, persisted even
   with a headed browser and basic anti-detection tweaks) — Yandex runs the
   same flow without that wall and is the OSINT community's standard
   substitute for exactly this reason.

## Analyzer setup (optional heavy ML)

The pure-Python analyzers (username, timing, contacts, content-profiler
keywords/sentiment, image similarity) work immediately. To enable the heavy
signals:

```bash
pip install -r requirements-ml.txt     # facenet-pytorch (facial), sentence-transformers (text)
ollama pull llama3.1:8b                 # optional: content-profiler LLM tone
```

Models download on first use. Every analyzer starts without them and the
lighter signals still score.

## Smoke test

```bash
# Username similarity (expect score ~0.95)
curl -sX POST localhost:8010/analyze/username -H 'content-type: application/json' \
  -d '{"username_a":"fox_99","username_b":"f0x99"}'

# Face detect: bounding box + extracted crop (needs requirements-ml.txt)
curl -sX POST localhost:8011/face/detect -F "file=@imgs/images132.jpg;type=image/jpeg"

# Face pipeline: detect+crop, reverse-search via Yandex, score similarity
# (needs requirements-ml.txt + playwright install chromium) — returns plain
# text with download links, not JSON
curl -sX POST "localhost:8017/analyze/face-pipeline?top_n=5" -F "file=@imgs/images132.jpg;type=image/jpeg"

# Maigret username enumeration (needs maigret installed for real results)
curl -sX POST localhost:8020/providers/maigret/search -H 'content-type: application/json' \
  -d '{"username":"some_real_username"}'

# Moriarty phone OSINT
curl -sX POST localhost:8021/providers/moriarty/lookup -H 'content-type: application/json' \
  -d '{"phone":"+91XXXXXXXXXX"}'

# Reddit fetch (needs a logged-in browser session for best results)
curl -sX POST localhost:8023/providers/reddit/subreddit -H 'content-type: application/json' \
  -d '{"subreddits":["python"]}'

# Holehe email registration check (takes ~20-60s — scans ~120 sites)
curl -sX POST localhost:8024/providers/holehe/search -H 'content-type: application/json' \
  -d '{"email":"target@example.com"}'

# WhatsApp registration check (needs the Baileys sidecar running + logged in)
curl -sX POST localhost:8025/providers/whatsapp/check -H 'content-type: application/json' \
  -d '{"number":"+91XXXXXXXXXX"}'

# Yandex reverse image search (top_n defaults to 10)
curl -sX POST "localhost:8026/providers/yandeximage/search?top_n=5" \
  -F "file=@/path/to/image.jpg;type=image/jpeg"
```

## Tests

```bash
pytest tests/ -v
```

Tests exercise the provider normalization + graceful-degradation paths and the
analyzer logic in-process. They are self-contained and do **not** require the
Dockerized PostgreSQL.
