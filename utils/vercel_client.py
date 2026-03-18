"""Phase 3: Vercel API client for creating projects from GitHub (personal/Hobby)."""

import requests

from utils.env import settings

VERCEL_API_BASE = "https://api.vercel.com"


def create_project(project_name: str, repo_full_name: str, framework: str = "nextjs") -> dict:
    """Create a Vercel project linked to a GitHub repository.

    Requires Vercel GitHub app to be installed on the repo's owner. Uses VERCEL_TOKEN.
    For personal account, leave VERCEL_TEAM_ID empty.

    Returns:
        {"id": "...", "name": "...", "link": "https://project.vercel.app"} or similar
    """
    if not settings.VERCEL_TOKEN:
        raise RuntimeError("VERCEL_TOKEN not configured")

    url = f"{VERCEL_API_BASE}/v10/projects"
    headers = {"Authorization": f"Bearer {settings.VERCEL_TOKEN}", "Content-Type": "application/json"}
    params = {}
    if settings.VERCEL_TEAM_ID:
        params["teamId"] = settings.VERCEL_TEAM_ID

    payload = {
        "name": project_name.replace(" ", "-").lower()[:100],
        "framework": framework,
        "gitRepository": {"repo": repo_full_name, "type": "github"},
    }

    r = requests.post(url, headers=headers, params=params or None, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()

    # Production URL might be in data.get("link") or from first deployment
    link = data.get("link") or data.get("project", {}).get("link")
    return {
        "id": data.get("id") or data.get("project", {}).get("id"),
        "name": data.get("name") or project_name,
        "link": link,
        "project_id": data.get("id"),
    }


def promote_to_production(project_name: str, custom_domain: str | None = None) -> None:
    """Promote latest Vercel preview deployment to production. Optional custom_domain for alias."""
    if not settings.VERCEL_TOKEN:
        raise RuntimeError("VERCEL_TOKEN not configured")
    name = project_name.replace(" ", "-").lower()[:100]
    params = {"projectId": name}
    if settings.VERCEL_TEAM_ID:
        params["teamId"] = settings.VERCEL_TEAM_ID
    headers = {"Authorization": f"Bearer {settings.VERCEL_TOKEN}"}
    # List deployments (Vercel v6 or v9)
    for ver in ("v9", "v6"):
        url = f"{VERCEL_API_BASE}/{ver}/deployments"
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code != 200:
            continue
        data = r.json()
        deployments = data.get("deployments") if isinstance(data, dict) else (data if isinstance(data, list) else [])
        if not deployments:
            continue
        deployment_id = deployments[0].get("uid")
        if not deployment_id:
            continue
        promote_url = f"{VERCEL_API_BASE}/{ver}/deployments/{deployment_id}/promote"
        pr = requests.post(promote_url, headers=headers, timeout=30)
        if pr.status_code == 200:
            return
    raise RuntimeError(f"Could not promote deployment for project {name}; check Vercel API docs")


def set_env_vars(project_name: str, env_vars: dict) -> None:
    """Set environment variables in Vercel production for the project."""
    if not settings.VERCEL_TOKEN:
        raise RuntimeError("VERCEL_TOKEN not configured")
    name = project_name.replace(" ", "-").lower()[:100]
    url = f"{VERCEL_API_BASE}/v10/projects/{name}/env"
    headers = {"Authorization": f"Bearer {settings.VERCEL_TOKEN}", "Content-Type": "application/json"}
    params = {"target": "production"}
    if settings.VERCEL_TEAM_ID:
        params["teamId"] = settings.VERCEL_TEAM_ID
    for key, value in env_vars.items():
        if "(encrypted" in str(value) or "(decrypt" in str(value):
            continue
        payload = {"key": key, "value": value, "type": "encrypted"}
        requests.post(url, headers=headers, params=params, json=payload, timeout=30)
