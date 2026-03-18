"""Phase 3 Step 3: Trigger the Claude Code build.

After APPROVE, this orchestrator creates the product repo with scaffold (ARCHITECT_SPEC.md,
DESIGNER_SPEC.md, CLAUDE.md), then runs the Claude Code CLI in that repo so subagents build
the product. The CLI is invoked programmatically; no human interaction.
"""

import os
import shutil
import subprocess
from pathlib import Path

from utils.env import settings
from utils.supabase_client import supabase


def fetch_briefing(judged_idea_id: str) -> dict | None:
    """Load the latest CEO brief from planning_artifacts for this idea."""
    res = (
        supabase.table("planning_artifacts")
        .select("payload")
        .eq("judged_idea_id", judged_idea_id)
        .eq("artifact_type", "ceo_brief")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data or len(res.data) == 0:
        return None
    return res.data[0].get("payload")


def run_build_pipeline(project_id: str) -> subprocess.CompletedProcess:
    """Create product repo with scaffold, update projects.github_repo, clone to work dir, run Claude Code.

    Requires: GITHUB_BOT_TOKEN, and `claude` CLI installed (npm install -g @anthropic-ai/claude-code).
    Returns the result of the claude subprocess.
    """
    res = (
        supabase.table("projects")
        .select("*")
        .eq("id", project_id)
        .single()
        .execute()
    )
    if not res.data:
        raise ValueError(f"Project {project_id} not found")
    project = res.data

    briefing = fetch_briefing(project["judged_idea_id"])
    if not briefing:
        raise ValueError(f"No CEO brief found for judged_idea_id {project['judged_idea_id']}")

    from utils.github_client import create_product_repo, push_scaffold_to_repo

    existing_repo = (project.get("github_repo") or "").strip()
    if existing_repo:
        push_scaffold_to_repo(existing_repo, briefing)
        repo_url = existing_repo if existing_repo.startswith("http") else f"https://github.com/{existing_repo}.git"
    else:
        repo_url = create_product_repo(project["product_name"], briefing)
        supabase.table("projects").update({"github_repo": repo_url}).eq("id", project_id).execute()

    # Persist builds under the forge workspace so you can run locally from a stable path.
    root_dir = Path(__file__).resolve().parents[1]  # /home/ric/Projects/forge
    projects_dir = root_dir / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    slug = (project["product_name"] or "product").replace(" ", "-")
    work_dir = projects_dir / slug

    # Use an authenticated clone URL so we can push the Claude-generated commits back to GitHub.
    token = settings.GITHUB_BOT_TOKEN
    clone_url = repo_url
    if token and clone_url.startswith("https://"):
        clone_url = clone_url.replace("https://", f"https://x-access-token:{token}@", 1)

    def _default_remote_branch(repo_path: Path) -> str:
        try:
            ref = subprocess.check_output(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=str(repo_path),
                text=True,
            ).strip()
            return ref.split("/")[-1]
        except Exception:
            return "main"

    def _ensure_origin(repo_path: Path, origin_url: str) -> None:
        """Ensure `origin` remote exists and points to the expected URL for pushes."""
        try:
            existing = subprocess.check_output(
                ["git", "remote", "get-url", "origin"],
                cwd=str(repo_path),
                text=True,
            ).strip()
            # Keep it aligned so pushes are non-interactive.
            if existing != origin_url:
                subprocess.run(
                    ["git", "remote", "set-url", "origin", origin_url],
                    cwd=str(repo_path),
                    check=False,
                    capture_output=True,
                    text=True,
                )
            return
        except Exception:
            # origin missing
            subprocess.run(
                ["git", "remote", "add", "origin", origin_url],
                cwd=str(repo_path),
                check=False,
                capture_output=True,
                text=True,
            )

    if work_dir.exists() and (work_dir / ".git").exists():
        remote_branch = _default_remote_branch(work_dir)
        _ensure_origin(work_dir, clone_url)
        subprocess.run(["git", "fetch", "origin"], cwd=str(work_dir), check=False, capture_output=True, text=True)
        subprocess.run(["git", "checkout", remote_branch], cwd=str(work_dir), check=False, capture_output=True, text=True)
        subprocess.run(
            ["git", "reset", "--hard", f"origin/{remote_branch}"],
            cwd=str(work_dir),
            check=False,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "clean", "-fdx"], cwd=str(work_dir), check=False, capture_output=True, text=True)
    else:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        subprocess.run(["git", "clone", clone_url, str(work_dir)], check=True, capture_output=True, text=True, timeout=120)
        remote_branch = _default_remote_branch(work_dir)

    prompt = (
        "Build this product according to ARCHITECT_SPEC.md and DESIGNER_SPEC.md. "
        "Start with the layout, then landing page, then auth, then core product. "
        "Commit after each section. Stop and write to QUESTIONS.md if anything is ambiguous."
    )
    result = subprocess.run(
        [
            "claude",
            "--dangerously-skip-permissions",
            "--model", "claude-sonnet-4-6",
            "-p", prompt,
        ],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=3600,
    )

    # Extra step: push the Claude-generated commits back to GitHub so Vercel/webhooks see the build.
    if result.returncode == 0:
        try:
            _ensure_origin(work_dir, clone_url)
            subprocess.run(
                ["git", "push", "origin", f"HEAD:{remote_branch}"],
                cwd=str(work_dir),
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            # Don't fail the build if push fails; caller can inspect stdout/stderr.
            pass
    return result
