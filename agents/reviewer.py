"""Reviewer agent: evaluates Analyst reports against a checklist."""

import json

import yaml

from utils.claude_client import call_agent
from utils.supabase_client import supabase


REVIEWER_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "REVISE", "ESCALATE"]},
        "failed_checks": {"type": "array", "items": {"type": "string"}},
        "revision_notes": {"type": "string"},
    },
    "required": ["verdict", "failed_checks", "revision_notes"],
}


def run_reviewer() -> None:
    with open("config/reviewer_checklist.yaml") as f:
        checklist = yaml.safe_load(f)

    checks_text = "\n".join(
        f"- {c['id']}: {c['description']}" for c in checklist["checks"]
    )

    max_revisions = checklist["thresholds"]["max_revisions"]

    # Review any idea that has not passed yet, regardless of whether notes exist.
    # This allows Analyst to clear notes while still letting Reviewer re-run.
    pending = (
        supabase.table("analyzed_ideas")
        .select("*, raw_ideas(post_title)")
        .eq("reviewer_pass", False)
        .lte("revision_count", max_revisions)
        .execute()
        .data
    )

    for record in pending:
        report_json = json.dumps(record["report"], indent=2)
        result_text = call_agent(
            "reviewer",
            f"You are a QA analyst. Apply these checks to the report:\n{checks_text}",
            f"Report to review:\n{report_json}",
            schema=REVIEWER_SCHEMA,
            effort="low",
        )

        # structured outputs always return at least one text block
        text = None
        if hasattr(result_text, "content") and isinstance(result_text.content, list):
            text = result_text.content[0].text
        else:
            text = str(result_text)

        result = json.loads(text)

        if result["verdict"] == "PASS":
            supabase.table("analyzed_ideas").update(
                {"reviewer_pass": True}
            ).eq("id", record["id"]).execute()
        elif result["verdict"] == "REVISE":
            supabase.table("analyzed_ideas").update(
                {
                    "reviewer_notes": result["revision_notes"],
                    "revision_count": record.get("revision_count", 0) + 1,
                }
            ).eq("id", record["id"]).execute()
        else:  # ESCALATE
            supabase.table("analyzed_ideas").update(
                {
                    "reviewer_notes": "ESCALATED: " + result["revision_notes"],
                    "reviewer_pass": None,  # null = escalated state
                }
            ).eq("id", record["id"]).execute()
