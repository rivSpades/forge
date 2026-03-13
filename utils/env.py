"""Environment configuration.

Load .env and expose a typed Settings object that can be imported by other modules.

Usage:
    from utils.env import settings
    print(settings.ANTHROPIC_API_KEY)
"""

from __future__ import annotations

from dataclasses import dataclass
from dotenv import load_dotenv
import os
from typing import Optional

load_dotenv()  # load variables from .env into os.environ


def _get_env(key: str, required: bool = True, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(key, default)
    if required and not value:
        raise RuntimeError(f"Missing required env var: {key}")
    return value


@dataclass(frozen=True)
class Settings:
    ANTHROPIC_API_KEY: str
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_KEY: str
    FIRECRAWL_API_KEY: Optional[str] = None
    RESEND_API_KEY: Optional[str] = None
    CEO_EMAIL: Optional[str] = None
    PLAN_EMAIL: Optional[str] = None
    PLAN_EMAIL_PASSWORD: Optional[str] = None
    NOTION_TOKEN: Optional[str] = None
    NOTION_DATABASE_ID: Optional[str] = None


settings = Settings(
    ANTHROPIC_API_KEY=_get_env("ANTHROPIC_API_KEY"),
    SUPABASE_URL=_get_env("SUPABASE_URL"),
    SUPABASE_ANON_KEY=_get_env("SUPABASE_ANON_KEY"),
    SUPABASE_SERVICE_KEY=_get_env("SUPABASE_SERVICE_KEY"),
    FIRECRAWL_API_KEY=_get_env("FIRECRAWL_API_KEY", required=False),
    RESEND_API_KEY=_get_env("RESEND_API_KEY", required=False),
    CEO_EMAIL=_get_env("CEO_EMAIL", required=False),
    PLAN_EMAIL=_get_env("PLAN_EMAIL", required=False),
    PLAN_EMAIL_PASSWORD=_get_env("PLAN_EMAIL_PASSWORD", required=False),
    NOTION_TOKEN=_get_env("NOTION_TOKEN", required=False),
    NOTION_DATABASE_ID=_get_env("NOTION_DATABASE_ID", required=False),
)

# Optional convenience:
# ROOT = Path(__file__).resolve().parents[1]
