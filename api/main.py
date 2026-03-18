"""FastAPI app for FORGE infrastructure: GitHub webhook (Code Reviewer on push)."""

import hmac
import hashlib
import json
import logging

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Query
from fastapi.responses import JSONResponse, HTMLResponse

from utils.env import settings
from utils.supabase_client import supabase

logger = logging.getLogger(__name__)

app = FastAPI(title="FORGE Webhooks", version="1.0")


def _verify_github_signature(body: bytes, signature: str | None) -> bool:
    if not settings.GITHUB_WEBHOOK_SECRET or not signature:
        return False
    expected = "sha256=" + hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def _project_for_repo(repo_full_name: str) -> dict | None:
    """Find project whose github_repo matches repo_full_name (owner/repo or URL)."""
    repo_ref = repo_full_name.strip()
    res = (
        supabase.table("projects")
        .select("id, judged_idea_id, github_repo")
        .ilike("github_repo", f"%{repo_ref}%")
        .limit(5)
        .execute()
    )
    if not res.data:
        return None
    for row in res.data:
        gr = (row.get("github_repo") or "").strip()
        if gr == repo_ref or gr == f"https://github.com/{repo_ref}" or repo_ref in gr:
            return row
    return res.data[0]


def _fetch_architect_spec(judged_idea_id: str) -> str:
    res = (
        supabase.table("planning_artifacts")
        .select("payload")
        .eq("judged_idea_id", judged_idea_id)
        .eq("artifact_type", "architect")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return "(No architect spec found for this project.)"
    payload = res.data[0].get("payload") or {}
    if isinstance(payload, dict):
        return json.dumps(payload, indent=2)
    return str(payload)


def _fetch_designer_spec(judged_idea_id: str) -> str | None:
    res = (
        supabase.table("planning_artifacts")
        .select("payload")
        .eq("judged_idea_id", judged_idea_id)
        .eq("artifact_type", "designer")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    payload = res.data[0].get("payload") or {}
    if isinstance(payload, dict):
        return json.dumps(payload, indent=2)
    return str(payload)


def _run_code_review_sync(repo_full_name: str, ref: str, before: str, after: str) -> None:
    """Run Code Reviewer for this push (sync, for background task)."""
    try:
        project = _project_for_repo(repo_full_name)
        if not project:
            logger.info("[webhook] No project found for repo %s", repo_full_name)
            return
        from utils.github_client import get_compare_diff
        from agents.code_reviewer_agent import run_code_review

        diff = get_compare_diff(repo_full_name, before, after)
        architect_spec = _fetch_architect_spec(project["judged_idea_id"])
        designer_spec = _fetch_designer_spec(project["judged_idea_id"])

        result = run_code_review(diff, architect_spec, designer_spec)
        logger.info("[webhook] Code review %s for %s: %s", result.get("verdict"), repo_full_name, result)
        if result.get("verdict") == "FAIL":
            logger.warning("[webhook] Code review FAIL for %s: issues=%s security_violations=%s",
                          repo_full_name, result.get("issues"), result.get("security_violations"))
    except Exception as e:
        logger.exception("[webhook] Code review failed for %s: %s", repo_full_name, e)


@app.post("/webhooks/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive GitHub webhook. On push to development branch, run Code Reviewer with diff and Architect spec."""
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")
    if not _verify_github_signature(body, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = request.headers.get("X-GitHub-Event", "")
    if event != "push":
        return JSONResponse(content={"ok": True, "event": event, "handled": False})

    repo = payload.get("repository") or {}
    repo_full_name = repo.get("full_name")
    ref = payload.get("ref", "")
    before = payload.get("before", "")
    after = payload.get("after", "")

    if not repo_full_name or not after:
        return JSONResponse(content={"ok": True, "handled": False, "reason": "missing repo or after"})

    # Only run Code Reviewer on development branch (configurable: main or development)
    if ref not in ("refs/heads/main", "refs/heads/development", "refs/heads/dev"):
        return JSONResponse(content={"ok": True, "handled": False, "ref": ref})

    background_tasks.add_task(_run_code_review_sync, repo_full_name, ref, before, after)
    return JSONResponse(content={"ok": True, "handled": True, "repo": repo_full_name, "ref": ref})


@app.get("/approve-launch", response_class=HTMLResponse)
async def approve_launch(
    project_id: str = Query(..., alias="project_id"),
    token: str = Query(..., alias="token"),
):
    """One-click launch approval. Token = HMAC(project_id) with LAUNCH_APPROVAL_SECRET."""
    from utils.launch_token import verify_launch_approval_token
    from scripts.launch_product import launch_product

    if not verify_launch_approval_token(project_id, token):
        return HTMLResponse(
            content="<h1>Invalid or expired link</h1><p>This approval link is invalid or has expired.</p>",
            status_code=403,
        )
    try:
        result = launch_product(project_id)
        if result.get("ok"):
            steps = result.get("steps", [])
            steps_ul = "".join(f"<li>{s}</li>" for s in steps)
            return HTMLResponse(
                content=f"<h1>Launch approved</h1><p>Product is going live. Steps:</p><ul>{steps_ul}</ul><p>You will receive a confirmation email shortly.</p>",
                status_code=200,
            )
        err = result.get("error", "Unknown error")
        steps_ul = "".join(f"<li>{s}</li>" for s in result.get("steps", []))
        return HTMLResponse(
            content=f"<h1>Launch failed</h1><p>{err}</p><p>Steps attempted:</p><ul>{steps_ul}</ul>",
            status_code=500,
        )
    except Exception as e:
        logger.exception("approve_launch failed for %s", project_id)
        return HTMLResponse(
            content=f"<h1>Error</h1><p>{e}</p>",
            status_code=500,
        )


@app.get("/health")
async def health():
    return {"status": "ok"}
