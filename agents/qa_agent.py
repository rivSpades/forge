"""QA Agent: generate Playwright tests from Designer spec, run them and Lighthouse, build Launch Readiness Report."""

import json
import subprocess
import tempfile

from utils.claude_client import get_response_text
from utils.supabase_client import supabase

# Minimum Lighthouse scores (0-100) for READY verdict. All must pass.
LIGHTHOUSE_THRESHOLDS = {"performance": 70, "accessibility": 80, "best-practices": 80, "seo": 70}


QA_GENERATE_TESTS_SCHEMA = {
    "type": "object",
    "properties": {
        "tests_py": {"type": "string"},
    },
    "required": ["tests_py"],
    "additionalProperties": False,
}


def fetch_designer_spec(project_id: str) -> dict | None:
    """Load designer artifact for the project's judged_idea_id."""
    res = (
        supabase.table("projects")
        .select("judged_idea_id")
        .eq("id", project_id)
        .single()
        .execute()
    )
    if not res.data:
        return None
    idea_id = res.data.get("judged_idea_id")
    if not idea_id:
        return None
    art = (
        supabase.table("planning_artifacts")
        .select("payload")
        .eq("judged_idea_id", idea_id)
        .eq("artifact_type", "designer")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not art.data:
        return None
    return art.data[0].get("payload")


async def run_qa(project_id: str, preview_url: str) -> dict:
    """Generate Playwright tests from Designer key_screens, run pytest and Lighthouse, return launch readiness report."""
    designer_spec = fetch_designer_spec(project_id)
    if not designer_spec:
        return {
            "ok": False,
            "error": "No designer spec found for project",
            "pytest_exit": None,
            "lighthouse": None,
        }

    key_screens = designer_spec.get("key_screens") if isinstance(designer_spec, dict) else None
    if not key_screens:
        key_screens = designer_spec

    from utils.claude_client import async_call_agent

    prompt = (
        "Convert the Designer screen spec below into Playwright Python tests using pytest and pytest-playwright. "
        "Use the 'page' fixture and set base_url via pytest-base-url or pass base_url to page.goto. "
        "Write one test per user flow. Include assertions (e.g. expect visibility, text). "
        "Output only valid Python code that can be run with: pytest <file> --base-url <url> -v."
    )
    user_content = json.dumps(key_screens, indent=2) if key_screens is not None else str(designer_spec)

    response = await async_call_agent(
        "qa",
        prompt,
        user_content,
        schema=QA_GENERATE_TESTS_SCHEMA,
    )
    text = get_response_text(response)
    if not text:
        return {"ok": False, "error": "QA agent returned no tests", "pytest_exit": None, "lighthouse": None}
    try:
        data = json.loads(text)
        tests_py = data.get("tests_py") or ""
    except json.JSONDecodeError:
        tests_py = text

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(tests_py)
        test_path = f.name

    try:
        result = subprocess.run(
            [
                "python", "-m", "pytest", test_path,
                "--base-url", preview_url,
                "-v",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pytest timed out", "pytest_exit": -1, "lighthouse": None}
    finally:
        import os
        try:
            os.unlink(test_path)
        except Exception:
            pass

    lh_scores = None
    try:
        lh_result = subprocess.run(
            ["npx", "lighthouse", preview_url, "--output=json", "--quiet", "--chrome-flags=--headless"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if lh_result.returncode == 0 and (lh_result.stdout or "").strip():
            lh_data = json.loads(lh_result.stdout)
            lh_scores = _parse_lighthouse_scores(lh_data)
    except Exception as e:
        lh_scores = {"error": str(e)}

    report = build_launch_readiness_report(result, lh_scores)
    if report.get("verdict") == "READY":
        send_launch_readiness_email(project_id, report, code_reviewer_flags=[])
    return report


def _parse_lighthouse_scores(lh_data: dict) -> dict:
    """Extract performance, accessibility, best-practices, seo from Lighthouse JSON."""
    cats = lh_data.get("categories") or {}
    out = {}
    for name, c in cats.items():
        if isinstance(c, dict) and "score" in c:
            out[name] = round((c["score"] or 0) * 100)
    return out


def build_launch_readiness_report(pytest_result: subprocess.CompletedProcess, lh_scores: dict | None) -> dict:
    """Build launch readiness report from pytest and Lighthouse results. Sets verdict READY or NOT_READY."""
    tests_pass = pytest_result.returncode == 0
    lh_ok = True
    lh_pass_fail = {}
    if lh_scores and isinstance(lh_scores, dict) and "error" not in lh_scores:
        for name, threshold in LIGHTHOUSE_THRESHOLDS.items():
            score = lh_scores.get(name)
            if score is not None:
                passed = score >= threshold
                lh_pass_fail[name] = {"score": score, "threshold": threshold, "pass": passed}
                if not passed:
                    lh_ok = False
            else:
                lh_pass_fail[name] = {"score": None, "threshold": threshold, "pass": False}
                lh_ok = False
    else:
        lh_ok = False

    verdict = "READY" if (tests_pass and lh_ok) else "NOT_READY"
    report = {
        "ok": tests_pass,
        "verdict": verdict,
        "pytest_exit": pytest_result.returncode,
        "pytest_stdout": (pytest_result.stdout or "")[-2000:],
        "pytest_stderr": (pytest_result.stderr or "")[-1000:],
        "lighthouse": lh_scores,
        "lighthouse_pass_fail": lh_pass_fail,
    }
    if lh_scores and isinstance(lh_scores, dict) and "error" not in lh_scores:
        report["lighthouse_summary"] = (
            f"Performance: {lh_scores.get('performance', 'N/A')}, "
            f"Accessibility: {lh_scores.get('accessibility', 'N/A')}, "
            f"Best Practices: {lh_scores.get('best-practices', 'N/A')}, "
            f"SEO: {lh_scores.get('seo', 'N/A')}"
        )
    return report


def send_launch_readiness_email(
    project_id: str,
    report: dict,
    code_reviewer_flags: list[str] | None = None,
) -> None:
    """Send Launch Readiness Report email via Resend: summary table, Lighthouse pass/fail, approval link."""
    from utils.env import settings
    from utils.launch_token import create_launch_approval_token

    if not settings.RESEND_API_KEY or not settings.CEO_EMAIL:
        print("[qa] RESEND_API_KEY or CEO_EMAIL not set; skipping Launch Readiness email")
        return
    if not settings.LAUNCH_APPROVAL_SECRET or not settings.LAUNCH_GATEWAY_URL:
        print("[qa] LAUNCH_APPROVAL_SECRET or LAUNCH_GATEWAY_URL not set; skipping approval link")
        return

    try:
        token = create_launch_approval_token(project_id)
        base = (settings.LAUNCH_GATEWAY_URL or "").rstrip("/")
        approval_url = f"{base}/approve-launch?project_id={project_id}&token={token}"
    except Exception as e:
        print(f"[qa] Cannot create approval token: {e}")
        approval_url = "(configure LAUNCH_APPROVAL_SECRET and LAUNCH_GATEWAY_URL)"

    flags = code_reviewer_flags or []
    lh_pf = report.get("lighthouse_pass_fail") or {}
    rows = []
    for name, data in lh_pf.items():
        score = data.get("score")
        passed = data.get("pass", False)
        status = "✅ Pass" if passed else "❌ Fail"
        rows.append(f"<tr><td>{name}</td><td>{score if score is not None else 'N/A'}</td><td>{status}</td></tr>")
    lh_table = "<table border='1' cellpadding='6'><tr><th>Category</th><th>Score</th><th>Status</th></tr>" + "".join(rows) + "</table>"

    test_status = "✅ All tests passed" if report.get("ok") else "❌ Some tests failed"
    flags_html = "<p>No unresolved Code Reviewer flags.</p>" if not flags else "<ul>" + "".join(f"<li>{f}</li>" for f in flags) + "</ul>"

    html = f"""
    <h1>Launch Readiness Report</h1>
    <p><strong>Project ID:</strong> {project_id}</p>
    <h2>Test results</h2>
    <p>{test_status}</p>
    <h2>Lighthouse scores</h2>
    {lh_table}
    <h2>Code Reviewer</h2>
    {flags_html}
    <h2>Approve launch</h2>
    <p><a href="{approval_url}">Click here to approve launch</a> (one-click; product goes live in ~2 minutes).</p>
    <p><small>If you did not request this report, ignore this email.</small></p>
    """
    import resend
    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send({
        "from": "FORGE Launch <launch@yourdomain.com>",
        "to": [settings.CEO_EMAIL],
        "subject": f"FORGE Launch Readiness — Project {project_id[:8]}... — READY",
        "html": html,
    })
    print(f"[qa] Launch Readiness Report email sent to {settings.CEO_EMAIL}")
