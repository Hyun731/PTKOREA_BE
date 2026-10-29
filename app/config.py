"""Settings from environment. Secrets stay server-side (PRD 14)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # backend/

# Secrets live in backend/.env (git-ignored). Real environment variables win over the file.
# Tests set PTK_SKIP_DOTENV=1 so they never see real keys or make paid calls.
if os.environ.get("PTK_SKIP_DOTENV") != "1":
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:  # pragma: no cover - python-dotenv ships with uvicorn[standard]
        pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", f"sqlite:///{ROOT / 'var' / 'dev.db'}"))
    storage_backend: str = field(default_factory=lambda: _env("STORAGE_BACKEND", "local"))
    storage_root: Path = field(default_factory=lambda: Path(_env("STORAGE_ROOT", str(ROOT / "var" / "storage"))))
    job_backend: str = field(default_factory=lambda: _env("JOB_BACKEND", "thread"))  # thread | celery | eager
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379/0"))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o for o in _env("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o))
    # Shared secret between the web server and this API. When set, every /v1 request must carry it
    # in X-Backend-Token (the web middleware adds it server-side), so a publicly reachable tunnel
    # address cannot be used to call the API directly. Empty = local use, no check.
    backend_token: str = field(default_factory=lambda: _env("BACKEND_TOKEN"))
    max_image_bytes: int = 10 * 1024 * 1024
    max_images_per_project: int = field(default_factory=lambda: int(_env("MAX_IMAGES_PER_PROJECT", "100")))
    max_image_pixels: int = 40_000_000
    max_csv_bytes: int = 5 * 1024 * 1024

    def provider_configured(self, provider: str) -> bool:
        keys = {
            "perplexity": ["PERPLEXITY_API_KEY"],
            "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"],
            "scrapecreators": ["SCRAPECREATORS_API_KEY"],
            "apify": ["APIFY_TOKEN"],  # actor defaults to apify~instagram-hashtag-scraper
            "naver": ["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"],
        }[provider]
        aliases = {"APIFY_TOKEN": ("APIFY_TOKEN", "APIFY_API_TOKEN")}
        return all(any(_env(name) for name in aliases.get(k, (k,))) for k in keys)


settings = Settings()
