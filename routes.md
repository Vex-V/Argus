# Argus — Route Index

Quick reference only — full request/response shapes in [ENDPOINTS.md](ENDPOINTS.md).
Every service also has `GET /health` and `/docs` (omitted below).

## Gateway — run everything on one port

`python gateway.py` merges every route below onto a single port (**8000**),
bound to `0.0.0.0` so other devices on the same network can reach it —
`http://<your-lan-ip>:8000/...` — instead of starting 14 separate processes
each bound to localhost. Every route keeps its exact path from the tables
below (e.g. `POST /providers/maigret/search` is still `POST /providers/maigret/search`
on the gateway); the one difference is `/health`, since every service defines
its own at that same path — those are namespaced as `GET /health/<service>`
(service names: `maigret`, `moriarty`, `telegram`, `reddit`, `holehe`,
`whatsapp`, `yandeximage`, `username`, `facial`, `text`, `timing`, `contacts`,
`content_profiler`, `image_similarity`, `face_pipeline`), and plain `GET /health` aggregates
all of them into one response. Interactive docs at `http://<host>:8000/docs`
list every route across every service in one place.

It's a pure aggregation layer — it imports each service's already-defined
FastAPI app and re-registers its routes, so there's still exactly one
implementation per endpoint; running services individually (the port table
below) still works exactly as before.

## Providers — `services/providers/`
| Port | Route | Input |
|---|---|---|
| 8020 | `POST /providers/maigret/search` | `{username, top_sites?}` |
| 8021 | `POST /providers/moriarty/lookup` | `{phone}` |
| 8022 | `POST /providers/telegram/fetch` | `{channels: [...]}` |
| 8023 | `POST /providers/reddit/subreddit` | `{subreddits: [...]}` |
| 8023 | `POST /providers/reddit/user/posts` | `{usernames: [...]}` |
| 8023 | `POST /providers/reddit/user/comments` | `{usernames: [...]}` |
| 8023 | `POST /providers/reddit/comments` | `{posts: [{subreddit, post_id}]}` |
| 8024 | `POST /providers/holehe/search` | `{email}` |
| 8025 | `POST /providers/whatsapp/check` | `{number}` (needs Baileys sidecar logged in — see README) |
| 8026 | `POST /providers/yandeximage/search` | multipart: `file`; query: `top_n?` (default 10) |

## Analyzers — `services/analyzers/`
| Port | Route | Input |
|---|---|---|
| 8010 | `POST /analyze/username` | `{username_a, username_b}` |
| 8011 | `POST /face/embed` | multipart: `file`, `source_url?`, `source_entity_id?`, `image_type?` |
| 8011 | `POST /face/compare` | `{image_a, image_b}` (base64) |
| 8011 | `POST /face/detect` | multipart: `file` |
| 8011 | `POST /face/search` | multipart: `file`; query: `limit?` |
| 8012 | `POST /analyze/text-similarity` | `{texts_a: [...], texts_b: [...]}` |
| 8013 | `POST /analyze/timing` | `{timestamps_a: [...], timestamps_b: [...]}` (unix seconds, 5+ each) |
| 8014 | `POST /analyze/contacts` | `{contacts_a: [{id, weight?}], contacts_b: [...]}` |
| 8015 | `POST /analyze/profile-content` | `{posts: [...], platform}` |
| 8016 | `POST /image/compare` | multipart: `image_a`, `image_b` |
| 8016 | `POST /image/search` | multipart: `file`; query: `limit?` |
| 8017 | `POST /analyze/face-pipeline` | multipart: `file`; query: `top_n?` (default 10) — returns plain text, not JSON |
| 8017 | `GET /analyze/face-pipeline/files/<run_id>/<filename>` | static file download (source crop / matched images) |
