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
    # Phase 3 — Build (personal GitHub, Vercel, Railway)
    GITHUB_BOT_TOKEN: Optional[str] = None
    VERCEL_TOKEN: Optional[str] = None
    VERCEL_TEAM_ID: Optional[str] = None
    RAILWAY_TOKEN: Optional[str] = None
    CREDENTIAL_ENCRYPTION_KEY: Optional[str] = None
    # GitHub webhook (Code Reviewer on push)
    GITHUB_WEBHOOK_SECRET: Optional[str] = None
    # Launch approval (one-click link in Launch Readiness Report email)
    LAUNCH_APPROVAL_SECRET: Optional[str] = None
    LAUNCH_GATEWAY_URL: Optional[str] = None  # e.g. https://forge.example.com
    BUFFER_ACCESS_TOKEN: Optional[str] = None  # Buffer API for launch social post


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
    GITHUB_BOT_TOKEN=_get_env("GITHUB_BOT_TOKEN", required=False),
    VERCEL_TOKEN=_get_env("VERCEL_TOKEN", required=False),
    VERCEL_TEAM_ID=_get_env("VERCEL_TEAM_ID", required=False),
    RAILWAY_TOKEN=_get_env("RAILWAY_TOKEN", required=False),
    CREDENTIAL_ENCRYPTION_KEY=_get_env("CREDENTIAL_ENCRYPTION_KEY", required=False),
    GITHUB_WEBHOOK_SECRET=_get_env("GITHUB_WEBHOOK_SECRET", required=False),
    LAUNCH_APPROVAL_SECRET=_get_env("LAUNCH_APPROVAL_SECRET", required=False),
    LAUNCH_GATEWAY_URL=_get_env("LAUNCH_GATEWAY_URL", required=False),
    BUFFER_ACCESS_TOKEN=_get_env("BUFFER_ACCESS_TOKEN", required=False),
)

# Optional convenience:
# ROOT = Path(__file__).resolve().parents[1]
