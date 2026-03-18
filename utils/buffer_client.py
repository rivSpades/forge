"""Buffer API client for publishing launch post. Phase 3 / Phase 4."""

import requests

from utils.env import settings

BUFFER_API_BASE = "https://api.bufferapp.com/1"


def publish_immediately(channel_ids: list[str], content: str) -> None:
    """Create and immediately publish a post to the given Buffer channel IDs.
    Requires BUFFER_ACCESS_TOKEN. channel_ids are Buffer profile IDs.
    """
    if not channel_ids:
        return
    token = getattr(settings, "BUFFER_ACCESS_TOKEN", None) or getattr(settings, "BUFFER_TOKEN", None)
    if not token:
        import logging
        logging.getLogger(__name__).info("[buffer] BUFFER_ACCESS_TOKEN not set; skipping publish_immediately")
        return
    # Buffer API: POST /1/updates/create — create update, then POST /1/updates/:id/share to share now
    url = f"{BUFFER_API_BASE}/updates/create.json"
    for profile_id in channel_ids:
        try:
            r = requests.post(
                url,
                params={"access_token": token},
                data={"profile_ids[]": profile_id, "text": content[:280], "shorten": "false"},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            update_id = data.get("id") if isinstance(data, dict) else None
            if update_id:
                share_url = f"{BUFFER_API_BASE}/updates/{update_id}/share.json"
                requests.post(share_url, params={"access_token": token}, timeout=30)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("[buffer] publish_immediately failed for %s: %s", profile_id, e)
