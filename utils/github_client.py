"""Phase 3: GitHub API client for creating repositories (personal account)."""

import os
import re
import subprocess
import tempfile

import requests

from utils.env import settings

GITHUB_API_BASE = "https://api.github.com"


def _slugify(name: str, max_length: int = 80) -> str:
    """Turn product name into a valid GitHub repo name."""
    s = (name or "product").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:max_length] if s else "product"


def create_repo(repo_name: str, description: str = "", private: bool = False) -> dict:
    """Create a GitHub repository. Uses GITHUB_BOT_TOKEN (personal PAT).

    Returns:
        {"full_name": "owner/repo", "html_url": "https://github.com/owner/repo", "clone_url": "..."}
    """
    if not settings.GITHUB_BOT_TOKEN:
        raise RuntimeError("GITHUB_BOT_TOKEN not configured")

    try:
        from github import Github
    except ImportError:
        raise ImportError("pip install PyGithub")

    gh = Github(settings.GITHUB_BOT_TOKEN)
    user = gh.get_user()
    name = _slugify(repo_name)
    repo = user.create_repo(name, description=description or None, private=private)
    return {
        "full_name": repo.full_name,
        "html_url": repo.html_url,
        "clone_url": repo.clone_url,
    }


def _push_scaffold(clone_url: str, briefing: dict, token: str) -> None:
    """Push ARCHITECT_SPEC.md, DESIGNER_SPEC.md, CLAUDE.md to an existing repo (e.g. empty)."""
    from utils.build_specs import format_arch_spec, format_design_spec, get_parent_claude_md

    auth_url = clone_url.replace("https://", f"https://x-access-token:{token}@")
    with tempfile.TemporaryDirectory(prefix="forge-repo-") as tmp:
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp, check=True, capture_output=True, timeout=10)
        subprocess.run(["git", "remote", "add", "origin", auth_url], cwd=tmp, check=True, capture_output=True, timeout=5)
        with open(os.path.join(tmp, "ARCHITECT_SPEC.md"), "w") as f:
            f.write(format_arch_spec(briefing.get("technical_plan") or ""))
        with open(os.path.join(tmp, "DESIGNER_SPEC.md"), "w") as f:
            f.write(format_design_spec(briefing.get("design_direction") or ""))
        with open(os.path.join(tmp, "CLAUDE.md"), "w") as f:
            f.write(get_parent_claude_md())
        subprocess.run(["git", "add", "."], cwd=tmp, check=True, capture_output=True, timeout=10)
        subprocess.run(
            ["git", "commit", "-m", "chore: initial scaffold from FORGE"],
            cwd=tmp,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=tmp,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )


def create_product_repo(product_name: str, briefing: dict) -> str:
    """Create a GitHub repo with folder scaffold: ARCHITECT_SPEC.md, DESIGNER_SPEC.md, CLAUDE.md.

    Uses create_repo() then pushes scaffold. Returns the repo clone URL (https).
    """
    info = create_repo(
        product_name,
        description=f"FORGE product: {product_name}",
        private=False,
    )
    clone_url = info["clone_url"]
    token = settings.GITHUB_BOT_TOKEN
    if not token:
        raise RuntimeError("GITHUB_BOT_TOKEN not configured")
    _push_scaffold(clone_url, briefing, token)
    return clone_url


def get_compare_diff(repo_full_name: str, base_sha: str, head_sha: str) -> str:
    """Get the diff between two commits. Uses GITHUB_BOT_TOKEN. Returns empty string on error."""
    if not settings.GITHUB_BOT_TOKEN:
        return ""
    url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/compare/{base_sha}...{head_sha}"
    headers = {
        "Authorization": f"Bearer {settings.GITHUB_BOT_TOKEN}",
        "Accept": "application/vnd.github.diff",
    }
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code != 200:
        return ""
    return r.text or ""


def push_scaffold_to_repo(repo_ref: str, briefing: dict) -> None:
    """Push ARCHITECT_SPEC.md, DESIGNER_SPEC.md, CLAUDE.md to an existing repo (e.g. created by phase3_build).

    repo_ref can be clone URL (https://github.com/owner/repo.git) or full_name (owner/repo).
    """
    token = settings.GITHUB_BOT_TOKEN
    if not token:
        raise RuntimeError("GITHUB_BOT_TOKEN not configured")
    clone_url = repo_ref if repo_ref.strip().startswith("http") else f"https://github.com/{repo_ref.strip()}.git"
    _push_scaffold(clone_url, briefing, token)
