#!/bin/bash
# Launch all Argus services (7 providers + 8 analyzers).
#
# Does NOT start the whatsapp-sidecar (Node/Baileys) — that needs an
# interactive terminal for the one-time QR-code login. Start it separately:
#   cd services/providers/whatsapp/baileys-service && npm install && npm start
#
# POSIX shells only (Linux/macOS/Git-Bash). Run from Git Bash on Windows:
#   bash scripts/start_all.sh
#
# Uses the venv's own python/uvicorn directly (not bare `uvicorn`), so this
# works whether or not the venv is "activated" in your shell — activating a
# Python venv only prepends its Scripts/bin dir to PATH, and a bare `uvicorn`
# call silently resolves to nothing (or the wrong install) if that never
# happened. Same reason maigret/other CLI tools looked "not installed" earlier
# in this project until their lookup was made venv-path-aware.
set -u
cd "$(dirname "$0")/.."

if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"      # Windows venv layout
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"              # POSIX venv layout
else
  echo "No .venv found — create one first: python -m venv .venv && pip install -r requirements.txt"
  exit 1
fi

echo "Starting infrastructure (PostgreSQL only)..."
docker compose up -d
sleep 3

echo "Applying database migrations (standby schema — nothing writes yet)..."
"$PY" -m alembic upgrade head || echo "  (migrations skipped — Postgres not required to run the services)"

echo "Starting provider services..."
"$PY" -m uvicorn services.providers.maigret.main:app            --port 8020 --reload &
"$PY" -m uvicorn services.providers.moriarty.main:app           --port 8021 --reload &
"$PY" -m uvicorn services.providers.telegram.main:app           --port 8022 --reload &
"$PY" -m uvicorn services.providers.reddit.main:app             --port 8023 --reload &
"$PY" -m uvicorn services.providers.holehe.main:app              --port 8024 --reload &
"$PY" -m uvicorn services.providers.whatsapp.main:app            --port 8025 --reload &
"$PY" -m uvicorn services.providers.yandeximage.main:app         --port 8026 --reload &

echo "Starting analyzer services..."
"$PY" -m uvicorn services.analyzers.username.main:app           --port 8010 --reload &
"$PY" -m uvicorn services.analyzers.facial.main:app             --port 8011 --reload &
"$PY" -m uvicorn services.analyzers.text.main:app               --port 8012 --reload &
"$PY" -m uvicorn services.analyzers.timing.main:app             --port 8013 --reload &
"$PY" -m uvicorn services.analyzers.contacts.main:app           --port 8014 --reload &
"$PY" -m uvicorn services.analyzers.content_profiler.main:app   --port 8015 --reload &
"$PY" -m uvicorn services.analyzers.image_similarity.main:app   --port 8016 --reload &
"$PY" -m uvicorn services.analyzers.face_pipeline.main:app      --port 8017 --reload &

cat <<'PORTS'

All services started. Port map:
  Providers                    Analyzers
  8020  Maigret                8010  Username
  8021  Moriarty               8011  Facial
  8022  Telegram               8012  Text
  8023  Reddit                 8013  Timing
  8024  Holehe                 8014  Contacts
  8025  WhatsApp               8015  Content Profiler
  8026  Yandex Image           8016  Image Similarity
                               8017  Face Pipeline

PORTS

echo "Run '$PY scripts/health_check.py' to confirm all services are up."
wait
