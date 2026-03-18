"""Approve a judged idea from the terminal: create project row and trigger Phase 3 infra (GitHub, Vercel, Railway)."""

import sys

from utils.supabase_client import supabase


def approve_idea(idea_id: str, product_name: str | None = None) -> dict:
    """Create projects row for this idea and run Phase 3 build. Returns {ok, project_id?, error?}."""
    idea_id = (idea_id or "").strip()
    if not idea_id:
        return {"ok": False, "error": "idea_id required"}

    name = (product_name or "").strip() or f"Product-{idea_id}"
    try:
        res = supabase.table("projects").insert(
            {
                "product_name": name[:255],
                "judged_idea_id": idea_id,
                "status": "approved",
            }
        ).execute()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not res.data or len(res.data) == 0:
        return {"ok": False, "error": "Insert returned no data"}

    project_id = res.data[0].get("id")
    if not project_id:
        return {"ok": False, "error": "No project id in insert result"}

    print(f"[approve] Created project {project_id} for idea {idea_id}")
    try:
        from scripts.phase3_build import run_build_for_project
        out = run_build_for_project(project_id)
        if out.get("ok"):
            print(f"[approve] Phase 3 infra started: {out}")
        else:
            print(f"[approve] Phase 3 infra skipped or failed: {out.get('error', '')}")
        return {"ok": True, "project_id": project_id, "phase3": out}
    except Exception as e:
        print(f"[approve] Phase 3 error: {e}")
        return {"ok": True, "project_id": project_id, "error": str(e)}


if __name__ == "__main__":
    idea_id = (sys.argv[1] if len(sys.argv) > 1 else "").strip() or None
    product_name = (sys.argv[2] if len(sys.argv) > 2 else "").strip() or None
    if not idea_id:
        print("Usage: python -m scripts.approve_idea <idea_id> [product_name]")
        sys.exit(1)
    result = approve_idea(idea_id, product_name)
    print(f"Project ID: {result.get('project_id', 'N/A')}")
    sys.exit(0 if result.get("ok") else 1)
