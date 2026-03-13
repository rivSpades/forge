"""Async Anthropic client support.

This file provides a shared async Claude client instance that can be used by
async jobs in the pipeline (e.g., plan generation).
"""

from anthropic import AsyncAnthropic

from utils.env import settings


async_claude = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
