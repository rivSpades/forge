"""Supabase client initialization.

Exports both sync and async Supabase clients for use across the pipeline.
"""

from supabase import create_client, create_async_client

from utils.env import settings


supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

# Async client is created lazily; use get_async_supabase() to access it.
_async_supabase = None


async def get_async_supabase():
    global _async_supabase
    if _async_supabase is None:
        _async_supabase = await create_async_client(
            settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY
        )
    return _async_supabase
