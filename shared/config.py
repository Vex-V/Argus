"""Central configuration loaded from the environment / .env file.

Uses pydantic-settings so every service shares one Settings object.
Import the singleton: ``from shared.config import settings``.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Infrastructure — PostgreSQL runs in Docker as standby infra (nothing
    # writes to it yet; providers and analyzers are stateless).
    database_url: str = "postgresql://argus:argus_dev@localhost:5432/argus"

    # Service URLs / port map (providers 8020–8026, analyzers 8010–8017).
    maigret_url: str = "http://localhost:8020"
    moriarty_url: str = "http://localhost:8021"
    telegram_url: str = "http://localhost:8022"
    reddit_url: str = "http://localhost:8023"
    holehe_url: str = "http://localhost:8024"
    whatsapp_url: str = "http://localhost:8025"
    yandeximage_url: str = "http://localhost:8026"
    whatsmyname_url: str = "http://localhost:8027"
    ignorant_url: str = "http://localhost:8028"
    socialanalyzer_url: str = "http://localhost:8029"
    ghunt_url: str = "http://localhost:8030"
    username_analyzer_url: str = "http://localhost:8010"
    facial_analyzer_url: str = "http://localhost:8011"
    text_analyzer_url: str = "http://localhost:8012"
    timing_analyzer_url: str = "http://localhost:8013"
    contacts_analyzer_url: str = "http://localhost:8014"
    content_profiler_url: str = "http://localhost:8015"
    image_similarity_url: str = "http://localhost:8016"
    face_pipeline_analyzer_url: str = "http://localhost:8017"
    metadata_analyzer_url: str = "http://localhost:8018"

    # Content profiler tone backend (optional — degrades without it)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # CORS — comma-separated allowed origins
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # --- Maigret provider ---
    maigret_top_sites: int = 100  # 3000+ full scan is slow; cap for demos

    # --- Moriarty provider ---
    # Local clone of https://github.com/AzizKaplan/Moriarty-Project — its
    # Investigation/ modules are imported in-process (see providers/moriarty).
    # Defaults to external/Moriarty-Project.
    moriarty_project_path: str | None = None
    # Truecaller "FindOwner" lookup logs into this Google account to search
    # Truecaller's web UI. Use a disposable/burner account — automated sign-in
    # trips Google's anti-automation checks and risks the account being locked
    # or challenged. Feature is skipped entirely when unset.
    moriarty_google_email: str | None = None
    moriarty_google_password: str | None = None

    # --- Telegram provider (https://my.telegram.org/apps) ---
    telegram_api_id: str | None = None
    telegram_api_hash: str | None = None
    telegram_session_name: str = "argus_telegram"

    # --- Reddit provider ---
    # Reddit's official API now gates key issuance, so the reddit provider uses
    # RedScrapsLib (cookie-authenticated scraping) instead of asyncpraw.
    # RedScrapsLib's .NET backend enforces strict RFC 7230 User-Agent token
    # syntax (no colons in the product name), unlike Reddit's own API rules.
    reddit_user_agent: str = "ArgusSOCMINT/0.1"
    reddit_cookie_browser: str = "firefox"  # browser_cookie3 source: firefox|chrome|edge|...

    # --- Holehe provider ---
    # Local clone of https://github.com/megadose/holehe — its modules/ site
    # checkers are imported in-process (see providers/holehe), not pip-installed.
    # Defaults to external/holehe.
    holehe_project_path: str | None = None

    # --- WhatsApp provider ---
    # Not pip-installable — Baileys is Node/TS. A separate sidecar process
    # (services/providers/whatsapp/baileys-service/) holds the logged-in
    # WhatsApp session; this is just the URL this provider proxies to.
    whatsapp_baileys_url: str = "http://localhost:3025"

    # --- WhatsMyName provider ---
    # Local clone of https://github.com/WebBreacher/WhatsMyName — its
    # wmn-data.json detection dataset is read directly (no install needed).
    # Defaults to external/WhatsMyName.
    whatsmyname_project_path: str | None = None

    # --- Ignorant provider ---
    # Local clone of https://github.com/megadose/ignorant — its modules/ site
    # checkers are imported in-process (see providers/ignorant), like holehe.
    # Defaults to external/ignorant.
    ignorant_project_path: str | None = None

    # --- Social Analyzer provider ---
    # Local clone of https://github.com/qeeqbox/social-analyzer — its app.py is
    # imported in-process (see providers/socialanalyzer). Defaults to
    # external/social-analyzer. Needs tld/langdetect/galeodes (requirements.txt).
    socialanalyzer_project_path: str | None = None

    # --- GHunt provider ---
    # Local clone of https://github.com/mxrch/GHunt — its ghunt/ package is
    # imported in-process (see providers/ghunt). Defaults to external/GHunt.
    ghunt_project_path: str | None = None
    # GHunt session file (cookies + OSIDs + Android master token) produced once
    # by `ghunt login`. Defaults to GHunt's own path (~/.malfrats/ghunt/creds.m);
    # set this to point at a session generated elsewhere. Without a valid session
    # the provider returns only the credential-free registration check.
    ghunt_creds_path: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so the .env file is only parsed once."""
    return Settings()


settings = get_settings()
