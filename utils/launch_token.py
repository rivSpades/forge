"""Signed token for one-click launch approval link. HMAC(project_id) prevents forgery."""

import hmac
import hashlib

from utils.env import settings


def create_launch_approval_token(project_id: str) -> str:
    """Return HMAC-SHA256 of project_id using LAUNCH_APPROVAL_SECRET (hex)."""
    if not settings.LAUNCH_APPROVAL_SECRET:
        raise RuntimeError("LAUNCH_APPROVAL_SECRET not configured")
    return hmac.new(
        settings.LAUNCH_APPROVAL_SECRET.encode(),
        project_id.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_launch_approval_token(project_id: str, token: str) -> bool:
    """Constant-time verification of approval token."""
    if not settings.LAUNCH_APPROVAL_SECRET or not token:
        return False
    expected = create_launch_approval_token(project_id)
    return hmac.compare_digest(expected, token)
