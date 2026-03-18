"""Phase 3: Build orchestration — create GitHub repo, Vercel project, Railway project for an approved idea."""

from utils.env import settings
from utils.supabase_client import supabase


def run_build_for_project(project_id: str) -> dict:
    """Create GitHub repo, Vercel project, and Railway project; update projects row.

    Requires GITHUB_BOT_TOKEN, VERCEL_TOKEN, RAILWAY_TOKEN (and optional VERCEL_TEAM_ID).
    Returns:
        {"ok": True, "github_repo": "...", "vercel_url": "...", "railway_url": "..."}
        or {"ok": False, "error": "..."}
    """
    if not settings.GITHUB_BOT_TOKEN or not settings.VERCEL_TOKEN or not settings.RAILWAY_TOKEN:
        return {"ok": False, "error": "Phase 3 not configured: set GITHUB_BOT_TOKEN, VERCEL_TOKEN, RAILWAY_TOKEN"}

    # Load project
    res = (
        supabase.table("projects")
        .select("id, product_name, judged_idea_id, status")
        .eq("id", project_id)
        .single()
        .execute()
    )
    if not res.data:
        return {"ok": False, "error": f"Project {project_id} not found"}

    project = res.data
    product_name = (project.get("product_name") or "product").strip() or "product"

    github_repo = None
    vercel_url = None
    railway_url = None

    try:
        # 1) GitHub repo
        from utils.github_client import create_repo as github_create_repo

        repo_info = github_create_repo(product_name, description=f"FORGE product: {product_name}", private=False)
        github_repo = repo_info.get("full_name") or repo_info.get("html_url")
        print(f"[phase3] Created GitHub repo: {github_repo}")

        # 2) Vercel project (link to GitHub repo)
        from utils.vercel_client import create_project as vercel_create_project

        v = vercel_create_project(product_name, repo_info["full_name"], framework="nextjs")
        vercel_url = v.get("link") or (f"https://{v.get('name', '')}.vercel.app" if v.get("name") else None)
        print(f"[phase3] Created Vercel project: {vercel_url}")

        # 3) Railway project (empty; user can link GitHub in dashboard or use CLI)
        from utils.railway_client import create_project as railway_create_project

        r = railway_create_project(product_name)
        railway_url = r.get("dashboard_url")
        print(f"[phase3] Created Railway project: {railway_url}")

        # 4) Update projects row
        supabase.table("projects").update(
            {
                "github_repo": github_repo,
                "vercel_url": vercel_url,
                "railway_url": railway_url,
                "status": "building",
            }
        ).eq("id", project_id).execute()
        print(f"[phase3] Updated project {project_id}")

        return {
            "ok": True,
            "github_repo": github_repo,
            "vercel_url": vercel_url,
            "railway_url": railway_url,
        }
    except Exception as e:
        # Partial update if we have any URLs
        update_payload = {"status": "build_failed"}
        if github_repo:
            update_payload["github_repo"] = github_repo
        if vercel_url:
            update_payload["vercel_url"] = vercel_url
        if railway_url:
            update_payload["railway_url"] = railway_url
        try:
            supabase.table("projects").update(update_payload).eq("id", project_id).execute()
        except Exception:
            pass
        print(f"[phase3] Build failed for {project_id}: {e}")
        return {"ok": False, "error": str(e)}


def run_build_for_idea(idea_id: str) -> dict:
    """Find project by judged_idea_id and run build for it."""
    res = (
        supabase.table("projects")
        .select("id")
        .eq("judged_idea_id", idea_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return {"ok": False, "error": f"No project found for judged_idea_id {idea_id}"}
    return run_build_for_project(res.data[0]["id"])
