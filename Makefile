# Argus — developer tasks.
# On Windows without `make`, run the underlying commands directly (see README).

.PHONY: up down migrate dev test gateway \
        maigret moriarty telegram reddit holehe whatsapp whatsapp-sidecar yandeximage \
        username facial text timing contacts content-profiler image-similarity face-pipeline

# --- Infra (PostgreSQL only) ---
up:
	docker compose up -d

down:
	docker compose down

migrate:
	alembic upgrade head

# --- Run everything (POSIX shells). On Windows run each in its own terminal. ---
# Does NOT start the whatsapp-sidecar (Node) — start that separately first,
# it needs an interactive terminal for the one-time QR-code login.
dev:
	uvicorn services.providers.maigret.main:app --port 8020 --reload &
	uvicorn services.providers.moriarty.main:app --port 8021 --reload &
	uvicorn services.providers.telegram.main:app --port 8022 --reload &
	uvicorn services.providers.reddit.main:app --port 8023 --reload &
	uvicorn services.providers.holehe.main:app --port 8024 --reload &
	uvicorn services.providers.whatsapp.main:app --port 8025 --reload &
	uvicorn services.providers.yandeximage.main:app --port 8026 --reload &
	uvicorn services.analyzers.username.main:app --port 8010 --reload &
	uvicorn services.analyzers.facial.main:app --port 8011 --reload &
	uvicorn services.analyzers.text.main:app --port 8012 --reload &
	uvicorn services.analyzers.timing.main:app --port 8013 --reload &
	uvicorn services.analyzers.contacts.main:app --port 8014 --reload &
	uvicorn services.analyzers.content_profiler.main:app --port 8015 --reload &
	uvicorn services.analyzers.image_similarity.main:app --port 8016 --reload &
	uvicorn services.analyzers.face_pipeline.main:app --port 8017 --reload &

# --- Providers ---
maigret:
	uvicorn services.providers.maigret.main:app --port 8020 --reload

moriarty:
	uvicorn services.providers.moriarty.main:app --port 8021 --reload

telegram:
	uvicorn services.providers.telegram.main:app --port 8022 --reload

reddit:
	uvicorn services.providers.reddit.main:app --port 8023 --reload

holehe:
	uvicorn services.providers.holehe.main:app --port 8024 --reload

whatsapp:
	uvicorn services.providers.whatsapp.main:app --port 8025 --reload

# Node sidecar holding the logged-in WhatsApp session — run this first (own
# terminal; scans a QR code on first run). Needs `npm install` there once.
whatsapp-sidecar:
	cd services/providers/whatsapp/baileys-service && npm start

yandeximage:
	uvicorn services.providers.yandeximage.main:app --port 8026 --reload

# --- Analyzers ---
username:
	uvicorn services.analyzers.username.main:app --port 8010 --reload

facial:
	uvicorn services.analyzers.facial.main:app --port 8011 --reload

text:
	uvicorn services.analyzers.text.main:app --port 8012 --reload

timing:
	uvicorn services.analyzers.timing.main:app --port 8013 --reload

contacts:
	uvicorn services.analyzers.contacts.main:app --port 8014 --reload

content-profiler:
	uvicorn services.analyzers.content_profiler.main:app --port 8015 --reload

image-similarity:
	uvicorn services.analyzers.image_similarity.main:app --port 8016 --reload

face-pipeline:
	uvicorn services.analyzers.face_pipeline.main:app --port 8017 --reload

test:
	pytest tests/ -v

# --- Gateway: every route above, merged onto one network-reachable port ---
gateway:
	python gateway.py
