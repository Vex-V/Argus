# Argus MCP server

Exposes the Argus SOCMINT toolkit to any MCP client (Claude Desktop, Claude
Code) so the model can run **multi-step, long-horizon OSINT** from a seed
identifier — a username, email, phone, or image — deciding which providers to
query and how to chain the results through the analyzers.

## How it works (and what it does *not* touch)

This server is a **pure HTTP client** of the existing Argus API. It:

- imports **nothing** from the Argus services and changes **no** Argus code;
- calls the same routes documented in [`../ENDPOINTS.md`](../ENDPOINTS.md) /
  [`../routes.md`](../routes.md), exactly like `curl` would;
- lives entirely in this `argus-mcp/` folder.

Nothing in the existing project is modified or turned off. The Argus API keeps
running as-is; this is a thin façade in front of it.

```
MCP client (Claude Desktop / Code)
        │  stdio  (tool calls)
        ▼
  argus-mcp/server.py   ──HTTP──▶   Argus API  (gateway :8000, or per-port services)
```

## Prerequisites

The Argus API must be running and reachable. Easiest is the gateway (all routes
on one port):

```bash
# from the repo root, with the Argus venv active
python gateway.py            # serves everything on http://localhost:8000
```

(Per-port standalone services work too — the gateway keeps every route's
original path, so the same tools hit either.)

## Install

You can reuse the Argus venv or make a dedicated one — only `mcp` + `httpx` are
needed here.

```bash
# from the repo root
pip install -r argus-mcp/requirements.txt
```

## Configure the client

### Claude Desktop

Edit `claude_desktop_config.json`
(`%APPDATA%\Claude\claude_desktop_config.json` on Windows) and merge in the
`argus` entry from [`claude_desktop_config.example.json`](claude_desktop_config.example.json).
Point `command` at the Python that has `mcp`/`httpx` installed and `args` at the
absolute path of `server.py`. Restart Claude Desktop.

### Claude Code (CLI)

```bash
claude mcp add argus \
  --env ARGUS_BASE_URL=http://localhost:8000 \
  -- /path/to/python /abs/path/to/argus-mcp/server.py
```

On Windows PowerShell:

```powershell
claude mcp add argus --env ARGUS_BASE_URL=http://localhost:8000 -- `
  "C:\Users\.a\codes\.vscode\python\Argus\.venv\Scripts\python.exe" `
  "C:\Users\.a\codes\.vscode\python\Argus\argus-mcp\server.py"
```

## Configuration

| Env var          | Default                 | Meaning                                   |
|------------------|-------------------------|-------------------------------------------|
| `ARGUS_BASE_URL` | `http://localhost:8000` | Base URL of the running Argus API         |
| `ARGUS_TIMEOUT`  | `180`                   | Per-request timeout, seconds (maigret/holehe scans are slow) |

## Tools

Meta: **`argus_health`** — always call first; shows which providers/analyzers
are actually live (many degrade to empty results without their credentials).

Providers (collection):

| Tool | Seed | Wraps |
|---|---|---|
| `maigret_search` | username | `POST /providers/maigret/search` |
| `moriarty_lookup` | phone | `POST /providers/moriarty/lookup` |
| `holehe_search` | email | `POST /providers/holehe/search` |
| `whatsapp_check` | phone | `POST /providers/whatsapp/check` |
| `reddit_subreddit` | subreddits | `POST /providers/reddit/subreddit` |
| `reddit_user_posts` | usernames | `POST /providers/reddit/user/posts` |
| `reddit_user_comments` | usernames | `POST /providers/reddit/user/comments` |
| `reddit_comments` | posts | `POST /providers/reddit/comments` |
| `yandeximage_search` | image path | `POST /providers/yandeximage/search` |

Analyzers (scoring — feed them evidence you already collected):

| Tool | Wraps |
|---|---|
| `analyze_username` | `POST /analyze/username` |
| `analyze_text_similarity` | `POST /analyze/text-similarity` |
| `analyze_timing` | `POST /analyze/timing` |
| `analyze_contacts` | `POST /analyze/contacts` |
| `analyze_profile_content` | `POST /analyze/profile-content` |
| `face_compare` | `POST /face/compare` |
| `face_detect` | `POST /face/detect` |
| `face_embed` † | `POST /face/embed` |
| `face_search` † | `POST /face/search` |
| `image_compare` | `POST /image/compare` |
| `image_search` † | `POST /image/search` |
| `face_pipeline` | `POST /analyze/face-pipeline` (returns plain text) |

† writes to / reads from PostgreSQL (the `images` table) — needs the DB up and
migrated. Every other tool is stateless.

> The Telegram provider is commented out in `gateway.py`, so it is intentionally
> not exposed here. If you re-enable it in the gateway, add a matching tool.

Image tools take a **local file path** on the machine running this server; the
server reads the bytes and forwards them (base64 for `face_compare`).

## Example investigation

Ask the client something like:

> Investigate the username `shadow_fox_99`. Find their accounts, then check
> whether the reddit account with that handle is the same person as the github
> one.

A typical chain the model can run:
1. `argus_health` → confirm maigret + reddit + analyzers are live.
2. `maigret_search("shadow_fox_99")` → list of accounts across sites.
3. `reddit_user_posts(["shadow_fox_99"])` + `reddit_user_comments([...])` →
   build a text/timing corpus.
4. `analyze_username`, `analyze_text_similarity`, `analyze_timing` on the two
   candidates → same-person score with evidence.

## Notes on responsible use

Argus is for authorized OSINT / SOCMINT work. Providers only touch data the
underlying tools already expose; several are credential-gated and degrade to
empty results when not configured. Keep request volume reasonable (the WhatsApp
sidecar in particular runs against your own linked-device session).
