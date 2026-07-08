"""Shared CORS setup so every service accepts the React dev server."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.config import settings


def add_cors(app: FastAPI) -> None:
    """Attach permissive-for-dev CORS middleware to a FastAPI app."""
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
