# Argus — API Endpoints

Every service exposes `GET /health` plus interactive docs at `/docs`. All
`POST /providers/...` and most `/analyze/...` routes return the same envelope:

```jsonc
// ServiceResponse
{
  "results": [ /* list of result dicts — shape varies by endpoint, see below */ ],
  "provenance": {
    "source_service": "maigret_provider",
    "captured_at": "2026-07-04T12:00:00+00:00",
    "content_hash": null
  },
  "errors": [ /* list[str], usually empty */ ]
}
```

Two analyzers (**facial**, **image_similarity**) are an exception: some of
their routes accept/return raw dicts (multipart file uploads) rather than the
`ServiceResponse` envelope, and they are the only endpoints that **write to
PostgreSQL** (the `images` table) — every other endpoint in this project is
stateless and returns results without persisting anything. **face_pipeline**
is a further exception: it returns a plain-text summary rather than JSON at
all (see its section) and saves matched images to local disk, served over
its own static-file route.

---

## Providers — `services/providers/`

### Maigret — port 8020
Username enumeration across many sites via the `maigret` CLI (subprocess).
Degrades to an empty result set if the CLI isn't installed.

**`POST /providers/maigret/search`**
```jsonc
// Request — top_sites is optional, overrides settings.maigret_top_sites (default 100)
// for this call only. Maigret ranks its site list by popularity, so a higher
// value trades a longer scan for broader coverage (3000+ = full scan).
{ "username": "shadow_fox_99", "top_sites": 500 }
```
```jsonc
// Response — results: list[Account]
{
  "results": [
    {
      "hash_id": "sha256(platform:username)",
      "platform": "github",
      "username": "shadow_fox_99",
      "display_name": null,
      "bio": null,
      "avatar_url": null,
      "profile_url": "https://github.com/shadow_fox_99",
      "follower_count": null,
      "following_count": null,
      "email": null,
      "phone": null,
      "created_at": null,
      "last_scraped": "2026-07-04T12:00:00+00:00",
      "raw_data": { "site_name": "GitHub", "url": "...", "username": "...", "status": "Claimed" },
      "breach_history": []
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```

**`GET /health`** → `{"status": "ok", "service": "maigret_provider"}`

---

### Holehe — port 8024
Email registration checks across ~120 sites via the local `holehe` clone
(imported in-process, not pip-installed — see `services/providers/holehe/`).
Only sites where the email is found to exist are returned. Degrades to an
empty result set if the clone isn't present.

**`POST /providers/holehe/search`**
```jsonc
// Request
{ "email": "target@example.com" }
```
```jsonc
// Response — results: one entry per site the email is registered on.
// method/frequent_rate_limit are a confidence signal: some sites' checks are
// self-flagged by holehe as prone to false positives when silently rate-limited.
{
  "results": [
    {
      "platform": "spotify.com",
      "email": "target@example.com",
      "exists": true,
      "method": "register",
      "frequent_rate_limit": true,
      "email_recovery": null,
      "phone_number": null,
      "other_data": null
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```

**`GET /health`** → `{"status": "ok", "service": "holehe_provider"}`

---

### WhatsApp — port 8025
Checks whether a phone number is registered on WhatsApp. This provider is a
thin HTTP proxy — the real work happens in a Node/TypeScript sidecar
(`services/providers/whatsapp/baileys-service/`, run separately) that holds a
logged-in Baileys (WhatsApp Web) session; see the README's "Provider setup"
section for the one-time QR-code login. Only a passive lookup is ever made —
no message is ever sent to the checked number.

**`POST /providers/whatsapp/check`**
```jsonc
// Request — number can include +, spaces, dashes; normalized to digits only
{ "number": "+91 98765 43210" }
```
```jsonc
// Response — results: [dict] (single check result)
{
  "results": [
    { "number": "919876543210", "exists": true, "jid": "919876543210@s.whatsapp.net" }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```
Degrades to `{"number": "...", "exists": null, "error": "whatsapp sidecar unreachable"}`
if the sidecar isn't running, or `"error": "whatsapp sidecar not connected"` if
it's up but the QR code hasn't been scanned yet (or the session was logged out).

**`GET /health`** → `{"status": "ok", "service": "whatsapp_provider"}`
(the sidecar has its own `GET http://localhost:3025/health` →
`{"status": "ok", "service": "whatsapp_baileys_sidecar", "connected": true|false}`)

---

### Yandex Image — port 8026
Reverse image search: given an image, finds pages that contain it. Drives a
headless Chromium (Playwright) through Yandex Images' own upload flow, then
reads results out of the page's embedded state rather than scraping rendered
HTML. (Originally scoped for Google — its Lens backend serves an immediate
CAPTCHA to headless automation, verified live; Yandex doesn't, and is the
OSINT community's standard substitute for this reason.) Degrades to an empty
result set if the browser isn't available or the search fails for any reason.

**`POST /providers/yandeximage/search`** — `multipart/form-data`
| field | type | required |
|---|---|---|
| `file` | image file | yes |
| `top_n` | int, query param (default `10`) | no |

```jsonc
// Response — results: up to top_n source pages, most-relevant first
{
  "results": [
    {
      "title": "Some Page Title",
      "url": "https://example.com/page?utm_source=yandexsmartcamera",
      "domain": "example.com",
      "description": "Optional page description, or null",
      "thumbnail_url": "https://avatars.mds.yandex.net/i?id=..."
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```

**`GET /health`** → `{"status": "ok", "service": "yandeximage_provider"}`

---

### Moriarty — port 8021
Phone-number OSINT via the local `Moriarty-Project/` clone, imported in-process
(geo, spam reports, web mentions/links). Optional Truecaller name lookup
(`truecaller_owner`) is only attempted when `MORIARTY_GOOGLE_EMAIL/PASSWORD`
are set.

**`POST /providers/moriarty/lookup`**
```jsonc
// Request
{ "phone": "+919876543210" }
```
```jsonc
// Response — results: [dict] (single enrichment object)
{
  "results": [
    {
      "phone_number": "+919876543210",
      "geo": { "valid": true, "country": "IN", "operator": "...", "timezone": "...", "local_time": "..." },
      "spam": { "reports": "...", "risk_level": "...", "explanation": "...", "number_type": "..." },
      "search_links": ["https://..."],
      "comments": ["..."],
      "truecaller_owner": { "name": "...", "source": "truecaller" }   // only if Google creds configured
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```
If `Moriarty-Project/` isn't found, `results` instead contains
`{"error": "Moriarty-Project not found at <path>", "phone_number": "..."}`.

**`GET /health`** → `{"status": "ok", "service": "moriarty_provider"}`

---

### Telegram — port 8022
On-demand fetch of recent messages from public channels via Telethon. Returns
`[]` when credentials or channels are missing (no scheduler, no persistence).

**`POST /providers/telegram/fetch`**
```jsonc
// Request
{ "channels": ["some_public_channel"] }
```
```jsonc
// Response — results: list[Account | Post] (mixed, Account entries first per author)
{
  "results": [
    { "hash_id": "...", "platform": "telegram", "username": "alice", "display_name": null, "last_scraped": "..." },
    {
      "hash_id": "...", "platform": "telegram", "author_hash_id": "...",
      "content": "message text", "timestamp": "2026-07-04T12:00:00+00:00",
      "geo_lat": null, "geo_lng": null, "media_urls": [],
      "raw_data": { "channel": "some_public_channel", "message_id": 123, "forwarded_from": null }
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```

**`GET /health`** → `{"status": "ok", "service": "telegram_provider"}`

---

### Reddit — port 8023
Four on-demand fetches via RedScrapsLib (cookie-authenticated). Every route
returns `[]` when RedScrapsLib isn't installed or its input list is empty. Post
entries carry `raw_data.kind` of `"post"` or `"comment"`.

**`POST /providers/reddit/subreddit`** — recent posts from subreddits
```jsonc
// Request
{ "subreddits": ["python"] }
```
```jsonc
// Response — results: list[Account | Post] (mixed, Account entries first per author)
{
  "results": [
    { "hash_id": "...", "platform": "reddit", "username": "some_user", "profile_url": "https://reddit.com/user/some_user", "last_scraped": "..." },
    {
      "hash_id": "...", "platform": "reddit", "author_hash_id": "...",
      "content": "Post Title\n\nSelf text body", "timestamp": "2026-07-04T12:00:00+00:00",
      "engagement": {},
      "raw_data": { "kind": "post", "subreddit": "python", "post_id": "abc123", "link": "https://..." }
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```
Note: `get_home` doesn't report the original post time, so `timestamp` here
reflects collection time, not the true posting time.

**`POST /providers/reddit/user/posts`** — a user's own post submissions
```jsonc
// Request
{ "usernames": ["spez"] }
```
```jsonc
// Response — one Account per username, then their Post submissions
{
  "results": [
    { "hash_id": "...", "platform": "reddit", "username": "spez", "profile_url": "https://reddit.com/user/spez", "last_scraped": "..." },
    {
      "hash_id": "...", "platform": "reddit", "author_hash_id": "...",
      "content": "Post Title\n\nSelf text body", "timestamp": "2025-12-01T00:00:00+00:00",
      "engagement": { "upvotes": 789, "comment_count": 248 },
      "raw_data": { "kind": "post", "subreddit": "u_spez", "post_id": "1u7hraf", "link": "..." }
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```
`timestamp` here is the real `CreatedUtc` reported by RedScrapsLib.

**`POST /providers/reddit/user/comments`** — a user's own comments
```jsonc
// Request
{ "usernames": ["spez"] }
```
```jsonc
// Response — one Account per username, then their Post-shaped comments
{
  "results": [
    { "hash_id": "...", "platform": "reddit", "username": "spez", "...": "..." },
    {
      "hash_id": "...", "platform": "reddit", "author_hash_id": "...",
      "content": "comment body", "timestamp": "2025-12-01T00:00:00+00:00",
      "engagement": { "upvotes": 92 },
      "raw_data": {
        "kind": "comment", "subreddit": "u_spez", "post_id": "t3_1u7hraf",
        "post_title": "21 years of Reddit", "comment_id": "os0o1vi",
        "parent_id": "t1_os0cskg", "link": "..."
      }
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```
`comment_id`/`parent_id` are real, distinct reddit IDs here (unlike the
`/comments` route below).

**`POST /providers/reddit/comments`** — comments on specific posts
```jsonc
// Request
{ "posts": [{ "subreddit": "python", "post_id": "abc123" }] }
```
```jsonc
// Response — one Account per unique comment author, then their Post-shaped comments
{
  "results": [
    { "hash_id": "...", "platform": "reddit", "username": "some_commenter", "...": "..." },
    {
      "hash_id": "...", "platform": "reddit", "author_hash_id": "...",
      "content": "comment body", "timestamp": "2026-07-04T12:00:00+00:00",
      "raw_data": { "kind": "comment", "subreddit": "python", "post_id": "abc123", "comment_id": "abc123", "parent_id": "abc123" }
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```
Two caveats verified live against RedScrapsLib: `timestamp` reflects
collection time (this call reports no per-comment timestamp), and
`raw_data.comment_id`/`parent_id` are **not reliable** — RedScrapsLib's
`get_comments` reports them equal to the post's own ID for every comment in
the thread. `hash_id` is therefore keyed on thread position instead and is
safe to use for deduplication; don't rely on `raw_data.comment_id` to
identify a specific comment.

**`GET /health`** → `{"status": "ok", "service": "reddit_provider"}`

---

## Analyzers — `services/analyzers/`

### Username — port 8010
Jaro-Winkler + normalized Levenshtein + leet/separator normalization +
substring containment. Pure Python, no external dependency to degrade.

**`POST /analyze/username`**
```jsonc
// Request
{ "username_a": "fox_99", "username_b": "f0x99" }
```
```jsonc
// Response — results: [{"score": float, "evidence": list[str]}]
{
  "results": [
    { "score": 0.95, "evidence": ["jaro_winkler: 0.944", "leet_normalized_exact_match"] }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```

**`GET /health`** → `{"status": "ok", "service": "username_analyzer"}`

---

### Facial — port 8011
Face-embedding similarity via facenet-pytorch (lazy-loaded). **Writes to
PostgreSQL** (`images` table + pgvector) via `/face/embed` and reads it via
`/face/search`; `/face/compare` is stateless.

**`POST /face/embed`** — `multipart/form-data`
| field | type | required |
|---|---|---|
| `file` | image file | yes |
| `source_url` | string | no |
| `source_entity_id` | string | no |
| `image_type` | string (default `"avatar"`) | no |

```jsonc
// Response (plain dict, not ServiceResponse)
{ "hash_id": "sha256(bytes)", "face_detected": true, "embedding_stored": true }
```
Persists the 512-dim embedding to the `images` table (upsert by `hash_id`)
when a face is detected.

**`POST /face/compare`**
```jsonc
// Request — FaceCompareRequest
{ "image_a": "<base64 bytes>", "image_b": "<base64 bytes>" }
```
```jsonc
// Response
{
  "results": [ { "score": 0.87, "evidence": ["cosine_similarity: 0.874"] } ],
  "provenance": { "...": "..." },
  "errors": []
}
```
Degrades to `{"score": 0.0, "evidence": ["face_model_unavailable"]}` (with an
entry in `errors`) if the model isn't loaded, or
`["no_face_in_image_a"/"no_face_in_image_b"]` if no face is detected.

**`POST /face/detect`** — `multipart/form-data`: `file` (image)
Detects the largest face (same MTCNN instance `/face/embed`/`/face/compare`
use), draws a bounding box on a copy of the image, and extracts the face
region as its own image. Nothing written to Postgres, but the extracted crop
is saved to local disk at `services/analyzers/facial/extracted_faces/<sha256
of the source image>.png` (gitignored) — `extracted_face_path` is that file's
path, so a caller doesn't have to decode the base64 just to get a file on disk.
```jsonc
// Response
{
  "results": [
    {
      "face_detected": true,
      "confidence": 0.9993,
      "box": { "x1": 65.4, "y1": 78.0, "x2": 181.5, "y2": 230.8 },
      "annotated_image_base64": "<PNG bytes, base64>",
      "extracted_face_base64": "<PNG bytes, base64>",
      "extracted_face_path": "C:\\...\\services\\analyzers\\facial\\extracted_faces\\<hash>.png"
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```
Degrades to `{"face_detected": false}` (with `"face_model_unavailable"` or
`"no_face_detected"` in `errors`) if the model isn't loaded or no face is found.

**`POST /face/search`** — `multipart/form-data`: `file` (image), query param `limit` (default 10)
```jsonc
// Response — nearest neighbours from the images table via pgvector cosine distance
{
  "results": [
    { "hash_id": "...", "source_entity_id": "...", "similarity": 0.93 }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```

**`GET /health`** → `{"status": "ok", "service": "facial_analyzer", "model_loaded": true|false}`

---

### Text — port 8012
Semantic (sentence-transformers, lazy) + stylometric similarity, combined
60/40. Stateless.

**`POST /analyze/text-similarity`**
```jsonc
// Request — TextSimilarityRequest
{ "texts_a": ["post one", "post two"], "texts_b": ["another post"] }
```
```jsonc
// Response
{
  "results": [
    {
      "semantic_similarity": 0.42,
      "stylometric_similarity": 0.71,
      "combined_score": 0.536,
      "evidence": ["semantic_similarity: 0.420", "stylometric_similarity: 0.710"]
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```
`semantic_similarity` is always `0.0` (only stylometry contributes) if
`sentence-transformers` isn't installed.

**`GET /health`** → `{"status": "ok", "service": "text_analyzer", "semantic_model_loaded": true|false}`

---

### Timing — port 8013
24-bin hour-of-day + 7-bin day-of-week histograms compared via Bhattacharyya
coefficient, combined 70/30. Pure Python/numpy, stateless.

**`POST /analyze/timing`**
```jsonc
// Request — TimingRequest (unix seconds)
{ "timestamps_a": [1735000000, 1735003600, "... 5+ values"], "timestamps_b": ["... 5+ values"] }
```
```jsonc
// Response — needs 5+ timestamps per side, else a low-info fallback
{
  "results": [
    {
      "hourly_similarity": 0.81,
      "weekly_similarity": 0.64,
      "combined_score": 0.759,
      "evidence": ["hourly_similarity: 0.810", "weekly_similarity: 0.640", "peak_hours_a: [21, 22, 9]", "peak_hours_b: [21, 9, 14]", "shared_peak_hours: [9, 21]"]
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```
Fallback when either side has fewer than 5 timestamps:
`{"combined_score": 0.0, "evidence": ["insufficient_data (need 5+ posts each)"]}`.

**`GET /health`** → `{"status": "ok", "service": "timing_analyzer"}`

---

### Contacts — port 8014
Jaccard index + interaction-weighted overlap of follower/contact sets,
combined 40/60. Pure Python, stateless.

**`POST /analyze/contacts`**
```jsonc
// Request — ContactsRequest (each contact: {"id": str, "weight": float = 1.0})
{
  "contacts_a": [{"id": "u1", "weight": 2.0}, {"id": "u2"}],
  "contacts_b": [{"id": "u1", "weight": 1.0}, {"id": "u3"}]
}
```
```jsonc
// Response
{
  "results": [
    {
      "jaccard_followers": 0.33,
      "weighted_interaction_overlap": 0.4,
      "combined_score": 0.372,
      "mutual_contacts": ["u1"],
      "evidence": ["jaccard: 0.333", "weighted_overlap: 0.400", "mutual_contacts: 1"]
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```

**`GET /health`** → `{"status": "ok", "service": "contacts_analyzer"}`

---

### Content Profiler — port 8015
Per-account keywords (TF-IDF), hashtag frequency, VADER sentiment, and an
Ollama-classified tone. Stateless; each signal degrades independently if its
dependency (scikit-learn / vaderSentiment / Ollama) is unavailable.

**`POST /analyze/profile-content`**
```jsonc
// Request — ContentProfileRequest
{ "posts": ["post text #tag1", "another post #tag1 #tag2"], "platform": "twitter" }
```
```jsonc
// Response
{
  "results": [
    {
      "top_keywords": ["keyword1", "keyword2"],
      "top_hashtags": [["tag1", 2], ["tag2", 1]],
      "sentiment": { "positive": 0.2, "negative": 0.0, "neutral": 0.8, "compound": 0.15 },
      "tone": "casual",
      "post_count": 2,
      "avg_post_length": 27.5,
      "platform": "twitter"
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```
`tone` falls back to `"unknown"` when Ollama is unreachable; `sentiment`
defaults to `{"positive":0.0,"negative":0.0,"neutral":1.0,"compound":0.0}`
without vaderSentiment; `top_keywords` is `[]` without scikit-learn.

**`GET /health`** → `{"status": "ok", "service": "content_profiler"}`

---

### Image Similarity — port 8016
Perceptual-hash (pHash) matching for non-face image reuse (banners, memes,
re-posted photos). `/image/compare` is stateless; `/image/search` **writes to
PostgreSQL** (upserts the query image's phash into the `images` table) then
searches it.

**`POST /image/compare`** — `multipart/form-data`: `image_a`, `image_b` (image files)
```jsonc
// Response
{
  "results": [
    {
      "phash_distance": 4,
      "similarity": 0.9375,
      "likely_match": true,
      "evidence": ["phash_hamming_distance: 4", "threshold: MATCH (cutoff=10)"],
      "phash_a": "8f3e1c2b9a7d6f4e",
      "phash_b": "8f3e1c2b9a7d6f4c"
    }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```
Degrades to `{"similarity": 0.0, "likely_match": false, "evidence": ["could_not_hash_image_a"/"..._b"]}`
if an image can't be read or imagehash/Pillow aren't installed.

**`POST /image/search`** — `multipart/form-data`: `file` (image), query param `limit` (default 10)
```jsonc
// Response — nearest images in the images table by Hamming distance
{
  "results": [
    { "hash_id": "...", "source_entity_id": "...", "source_url": "...", "phash_distance": 4, "similarity": 0.9375, "likely_match": true }
  ],
  "provenance": { "...": "..." },
  "errors": []
}
```

**`GET /health`** → `{"status": "ok", "service": "image_similarity", "phash_available": true|false}`

---

### Face Pipeline — port 8017
Detects a face, reverse-image-searches it via Yandex (the `yandeximage`
provider), and scores facial similarity against each result (the `facial`
analyzer) — both called in-process, not over HTTP, so this service needs the
same dependencies as those two (facenet-pytorch model + Playwright/chromium)
to get real results. **Does not return the `ServiceResponse` envelope** —
the response is a plain-text summary, and matched images are saved to local
disk and served over a static-file route rather than embedded as base64 in
JSON (a single request could otherwise return megabytes of inline image
data). A copy of the summary is also written next to the images.

**`POST /analyze/face-pipeline`** — `multipart/form-data`: `file` (image); query param `top_n` (default 10)
```
Content-Type: text/plain

Detected face confidence: 0.9993
Source face crop: http://<host>/analyze/face-pipeline/files/<run_id>/00_source_face.png
Yandex results returned: 3  |  scored matches: 3

1. 98.3%  <page title>  (<domain>)
   source page: https://...
   image:       http://<host>/analyze/face-pipeline/files/<run_id>/01_098.3pct_<domain>.jpg

2. 97.6%  ...
```
`<run_id>` is the SHA-256 of the uploaded image, so re-running on the same
image overwrites its output rather than piling up. On failure the body is a
one-line plain-text reason instead: `"No face detected in the uploaded
image.\n"` or `"Face detected (confidence 0.99), but: <reason>\n"`.

**`GET /analyze/face-pipeline/files/<run_id>/<filename>`** — serves a saved
source crop or matched image directly (static file route, not JSON).

**`GET /health`** → `{"status": "ok", "service": "face_pipeline_analyzer"}`
