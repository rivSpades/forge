"""Phase 3: Railway API client (GraphQL) for creating projects (personal account)."""

import requests

from utils.env import settings

RAILWAY_GRAPHQL_URL = "https://backboard.railway.app/graphql/v2"


def create_project(project_name: str) -> dict:
    """Create an empty Railway project. Uses RAILWAY_TOKEN.

    To deploy from GitHub, link the repo in the Railway dashboard or use Railway CLI.
    Returns:
        {"id": "...", "name": "...", "dashboard_url": "https://railway.app/project/..."}
    """
    if not settings.RAILWAY_TOKEN:
        raise RuntimeError("RAILWAY_TOKEN not configured")

    query = """
    mutation projectCreate($name: String!) {
      projectCreate(input: { name: $name }) {
        id
        name
      }
    }
    """
    headers = {
        "Authorization": f"Bearer {settings.RAILWAY_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": {"name": (project_name or "forge-product")[:100]}}

    r = requests.post(RAILWAY_GRAPHQL_URL, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"Railway GraphQL errors: {data['errors']}")

    project = (data.get("data") or {}).get("projectCreate")
    if not project:
        raise RuntimeError("Railway did not return projectCreate result")

    project_id = project.get("id")
    dashboard_url = f"https://railway.app/project/{project_id}" if project_id else None
    return {
        "id": project_id,
        "name": project.get("name"),
        "dashboard_url": dashboard_url,
    }


def deploy_to_production(service_id: str) -> None:
    """Trigger production deploy for a Railway service. service_id is the service UUID.
    Railway does not expose a simple 'deploy' in public API; use Railway CLI or dashboard.
    This is a placeholder that logs; replace with Railway GraphQL mutation when available.
    """
    import logging
    logging.getLogger(__name__).info("[railway] deploy_to_production(%s) — trigger via Railway dashboard or CLI", service_id)
