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
[routes.md](routes.md) for exact request/response shapes. PostgreSQL
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
    whatsmyname/ :8027  username enumeration           — WhatsMyName wmn-data.json dataset
    ignorant/    :8028  phone registration checks      — ignorant clone (in-process)
    socialanalyzer/ :8029 profile discovery (900+ sites) — social-analyzer clone (in-process)
    ghunt/       :8030  Google account OSINT (email)   — GHunt clone (in-process, async)
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
    metadata/    :8018  image EXIF/IPTC/XMP + GPS extraction — PyExifTool (exiftool CLI)
shared/          schemas, ORM models, db, config, evidence, cors
migrations/      Alembic schema + pgvector (standby infra)
external/Moriarty-Project/ local clone (not tracked; see Setup) whose Investigation/ modules the moriarty provider imports
external/holehe/            local clone (not tracked; see Setup) whose modules/ site-checkers the holehe provider imports
external/WhatsMyName/       local clone (not tracked; see Setup) whose wmn-data.json the whatsmyname provider reads
external/ignorant/          local clone (not tracked; see Setup) whose modules/ site-checkers the ignorant provider imports
external/social-analyzer/   local clone (not tracked; see Setup) whose app.py the socialanalyzer provider imports
external/GHunt/             local clone (not tracked; see Setup) whose ghunt/ package the ghunt provider imports
services/providers/whatsapp/baileys-service/  Node/TS sidecar holding the Baileys WhatsApp session
tests/           offline provider + analyzer tests
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
| WhatsMyName | `POST /providers/whatsmyname/search` | `{"username": "..."}` |
| Ignorant | `POST /providers/ignorant/check` | `{"phone": "+CC...", "country_code"?: "..."}` |
| Social Analyzer | `POST /providers/socialanalyzer/search` | `{"username": "...", "top"?: N, "websites"?: "..."}` |
| GHunt | `POST /providers/ghunt/email` | `{"email": "..."}` |
| GHunt | `POST /providers/ghunt/gaia` | `{"gaia_id": "..."}` |
| GHunt | `POST /providers/ghunt/maps-reviews` | `{"gaia_id": "..."}` |
| GHunt | `POST /providers/ghunt/maps-contributions` | `{"gaia_id": "...", "max_items"?: N}` |
| Username | `POST /analyze/username` | `{"username_a": "...", "username_b": "..."}` |
| Facial | `POST /face/compare`, `/face/detect`, `/face/embed`†, `/face/search`† | `{"image_a": "<b64>", "image_b": "<b64>"}` (compare) |
| Text | `POST /analyze/text-similarity` | `{"texts_a": [...], "texts_b": [...]}` |
| Timing | `POST /analyze/timing` | `{"timestamps_a": [...], "timestamps_b": [...]}` |
| Contacts | `POST /analyze/contacts` | `{"contacts_a": [...], "contacts_b": [...]}` |
| Content profiler | `POST /analyze/profile-content` | `{"posts": [...], "platform": "..."}` |
| Image similarity | `POST /image/compare`, `/image/search`† | multipart image file(s) |
| Face Pipeline | `POST /analyze/face-pipeline`‡ | multipart `file` + query `top_n` |
| Image metadata | `POST /analyze/metadata` | multipart `file` (image) |

† writes to / reads from PostgreSQL (the `images` table) — every other
endpoint is stateless. ‡ returns a plain-text summary instead of JSON, with
download links for the matched images (see below). Full request/response
shapes for every route, including these multipart/DB-backed/plain-text ones,
are in **[routes.md](routes.md)**.

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

`bash scripts/start_all.sh` launches all 19. It doesn't start the
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
uvicorn services.providers.whatsmyname.main:app      --port 8027 --reload
uvicorn services.providers.ignorant.main:app         --port 8028 --reload
uvicorn services.providers.socialanalyzer.main:app   --port 8029 --reload
uvicorn services.providers.ghunt.main:app            --port 8030 --reload
uvicorn services.analyzers.username.main:app         --port 8010 --reload
uvicorn services.analyzers.facial.main:app           --port 8011 --reload
uvicorn services.analyzers.text.main:app             --port 8012 --reload
uvicorn services.analyzers.timing.main:app           --port 8013 --reload
uvicorn services.analyzers.contacts.main:app         --port 8014 --reload
uvicorn services.analyzers.content_profiler.main:app --port 8015 --reload
uvicorn services.analyzers.image_similarity.main:app --port 8016 --reload
uvicorn services.analyzers.face_pipeline.main:app    --port 8017 --reload
uvicorn services.analyzers.metadata.main:app         --port 8018 --reload
```

`python scripts/health_check.py` confirms all 19 are up (expect 19/19; this
doesn't check the WhatsApp sidecar itself, only the Python proxy in front of it).

**Or run everything on one network-reachable port:** `python gateway.py`
merges every route above into a single process bound to
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
   into `external/` (not tracked here — see `.gitignore`). The provider
   imports its `Investigation/` modules in-process; no install needed.
   `MORIARTY_PROJECT_PATH` overrides the default location. FindOwner
   (Truecaller via Google login) is optional and credential-gated — set
   `MORIARTY_GOOGLE_EMAIL/PASSWORD` to a disposable/burner account and
   `playwright install firefox`.
5. **Holehe** — clone `git clone https://github.com/megadose/holehe` into
   `external/` (not tracked here — see `.gitignore`). The provider imports its
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
8. **WhatsMyName** — clone `git clone https://github.com/WebBreacher/WhatsMyName`
   into `external/` (not tracked here — see `.gitignore`). The provider reads
   its `wmn-data.json` detection dataset directly (no install, no extra deps —
   it checks sites with the `httpx` already in `requirements.txt`).
   `WHATSMYNAME_PROJECT_PATH` overrides the default location. Pull the clone
   periodically to pick up the community's site-rule updates.
9. **Ignorant** — clone `git clone https://github.com/megadose/ignorant` into
   `external/` (not tracked here — see `.gitignore`). holehe's sibling for
   phone numbers; the provider imports its `modules/` site-checkers in-process,
   no install needed (its runtime deps — trio/httpx/bs4 — are already installed
   for holehe). `IGNORANT_PROJECT_PATH` overrides the default location.
10. **Social Analyzer** — clone `git clone https://github.com/qeeqbox/social-analyzer`
    into `external/` (not tracked here — see `.gitignore`). The provider imports
    its `app.py` in-process (via a file-spec loader, so nothing is added to
    `sys.path`). Needs three extra Python deps beyond the rest of the project —
    `tld`, `langdetect`, `galeodes` — which are in `requirements.txt` (galeodes
    pulls in selenium; the provider's fast mode doesn't drive a browser, but
    the import chain requires it present). `SOCIALANALYZER_PROJECT_PATH`
    overrides the default location. The `top` request field (scan only the N
    highest-ranked sites) is the practical way to keep a scan fast — a full
    900+-site run can take minutes.
11. **GHunt** — clone `git clone https://github.com/mxrch/GHunt` into
    `external/` (not tracked here — see `.gitignore`). mxrch's Google OSINT
    framework; the provider imports its `ghunt/` package in-process (added to
    `sys.path`, like holehe/ignorant), no install needed — its runtime deps
    (`h2`, `geopy`, `autoslot`, `humanize`, `inflection`, `jsonpickle`,
    `beautifultable`, `alive-progress`, `rich-argparse`, `dnspython`) are in
    `requirements.txt`. `GHUNT_PROJECT_PATH` overrides the default location.

    The email **registration check** (is any Google account tied to this email)
    needs no credentials and always runs. The **full profile** lookup (display
    name, Gaia ID, profile/cover photo, activated Google services, account
    type) needs a GHunt session generated once with `ghunt login` — install the
    GHunt Companion browser extension, run the login flow, and it writes a
    session to `~/.malfrats/ghunt/creds.m` (that's the default path GHunt and
    this provider both read; `GHUNT_CREDS_PATH` points at a session stored
    elsewhere). Use a disposable/burner Google account — this is real automation
    against Google's endpoints from that account. Without a valid session the
    provider still returns the registration result and notes the skipped
    profile lookup in the response `errors`.

## Analyzer setup (optional heavy ML)

The pure-Python analyzers (username, timing, contacts, content-profiler
keywords/sentiment, image similarity) work immediately without the heavy ML
block at the bottom of `requirements.txt` (sentence-transformers, torch,
facenet-pytorch, lingua-language-detector). To enable the heavy signals:

```bash
pip install -r requirements.txt        # includes facenet-pytorch (facial), sentence-transformers (text)
pip install facenet-pytorch --no-deps  # reinstall without deps — see the note in requirements.txt
ollama pull llama3.1:8b                 # optional: content-profiler LLM tone
```

Models download on first use. Every analyzer starts without them and the
lighter signals still score.

### Image metadata analyzer — install the `exiftool` binary

The metadata analyzer (`:8018`) uses `PyExifTool`, which is only a wrapper —
it shells out to Phil Harvey's **`exiftool`** CLI (a Perl program), so that
binary must be on PATH. `pip install -r requirements.txt` gets the wrapper but
not the CLI:

```bash
# Windows (choco) ..... choco install exiftool
# Windows (manual) .... download the standalone .exe from https://exiftool.org,
#                       rename exiftool(-k).exe -> exiftool.exe, put it on PATH
# macOS .............. brew install exiftool
# Debian/Ubuntu ...... sudo apt install libimage-exiftool-perl
```

Verify with `exiftool -ver`. Without it the service still starts and responds;
`GET /health` reports `exiftool_available: false` and requests return an
`exiftool_unavailable` error note instead of crashing.

## Smoke test

```bash
# Username similarity (expect score ~0.95)
curl -sX POST localhost:8010/analyze/username -H 'content-type: application/json' \
  -d '{"username_a":"fox_99","username_b":"f0x99"}'

# Face detect: bounding box + extracted crop (needs the heavy ML deps, see above)
curl -sX POST localhost:8011/face/detect -F "file=@imgs/images132.jpg;type=image/jpeg"

# Face pipeline: detect+crop, reverse-search via Yandex, score similarity
# (needs the heavy ML deps + playwright install chromium) — returns plain
# text with download links, not JSON
curl -sX POST "localhost:8017/analyze/face-pipeline?top_n=5" -F "file=@imgs/images132.jpg;type=image/jpeg"

# Image metadata: EXIF/GPS extraction (needs the exiftool binary, see above)
curl -sX POST localhost:8018/analyze/metadata -F "file=@imgs/images132.jpg;type=image/jpeg"

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
