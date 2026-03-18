"""Code Reviewer agent: review code diff against Architect spec via Claude API.

Used by the GitHub webhook on push to the development branch. Returns structured
verdict (PASS/FAIL), issues, and security_violations.
"""

import json

from utils.claude_client import call_agent, get_response_text


CODE_REVIEWER_SYSTEM = """You are the Code Reviewer subagent. Review the provided code diff against the Architect spec.

Check these items and report the result as JSON:

SECURITY CHECKS (any failure = immediate FAIL, alert CEO):
- No hardcoded API keys, secrets, or credentials anywhere
- All authenticated endpoints actually check the auth token
- User input is validated before database operations

SPEC COMPLIANCE:
- All features in the MVP list are present
- Screen descriptions from Designer spec match what is built (if Designer spec is provided)
- Error states and loading states exist for all interactive elements

Output exactly one JSON object with: verdict ("PASS" or "FAIL"), issues (array of strings), security_violations (array of strings).
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
        "issues": {"type": "array", "items": {"type": "string"}},
        "security_violations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "issues", "security_violations"],
    "additionalProperties": False,
}


def run_code_review(diff: str, architect_spec: str, designer_spec: str | None = None) -> dict:
    """Review code diff against Architect spec (and optional Designer spec). Returns verdict dict."""
    user_content = f"## Architect spec\n\n{architect_spec}\n\n"
    if designer_spec:
        user_content += f"## Designer spec (for screen/spec compliance)\n\n{designer_spec}\n\n"
    user_content += "## Code diff to review\n\n```diff\n" + (diff or "(empty diff)") + "\n```"

    response = call_agent(
        "code_reviewer",
        CODE_REVIEWER_SYSTEM,
        user_content,
        schema=OUTPUT_SCHEMA,
    )
    text = get_response_text(response)
    if not text:
        return {"verdict": "FAIL", "issues": ["No response from Code Reviewer"], "security_violations": []}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"verdict": "FAIL", "issues": [f"Code Reviewer returned invalid JSON: {text[:500]}"], "security_violations": []}
