"""Reviewer for CEO briefing. Updates same planning_artifacts row (reviewer_pass, reviewer_notes)."""

import json

import yaml

from utils.claude_client import call_agent, get_response_text
from utils.supabase_client import supabase


REVIEWER_SYSTEM_INSTRUCTIONS = """You are a checklist-based reviewer. Your only job is to decide if the output satisfies the criteria below.

RULES:
- PASS: output meets the checklist criteria. revision_notes may briefly confirm or be empty.
- REVISE: one or more checklist items are not satisfied. failed_checks = list of check IDs that failed. revision_notes = concrete, actionable feedback only: what is missing or wrong and what to change. No commentary about the product concept, "cannot be revised at X level," or process—only checklist-based, actionable notes.
- ESCALATE: only when the output is out of scope or cannot be assessed against the checklist (e.g. empty or wrong type). revision_notes = which checks could not be assessed and why (one short sentence). Do not use ESCALATE for fixable checklist failures—use REVISE. No opinions about the product or whether something "can be revised"; no political or meta-commentary.

Keep revision_notes focused and brief. Do not write essays or opinions."""


def _checks_text(checklist: dict) -> str:
    return "\n".join(
        f"- {c['id']}: {c['description']}" for c in checklist.get("checks", [])
    )


PLAN_REVIEWER_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "REVISE", "ESCALATE"]},
        "failed_checks": {"type": "array", "items": {"type": "string"}},
        "revision_notes": {"type": "string"},
    },
    "required": ["verdict", "failed_checks", "revision_notes"],
}


def run_plan_reviewer(limit: int = 5) -> None:
    with open("config/plan_reviewer_checklist.yaml") as f:
        checklist = yaml.safe_load(f)
    checks_text = _checks_text(checklist)

    # Any ceo_brief not yet passed (revision_count not used here)
    all_rows = (
        supabase.table("planning_artifacts")
        .select("id, judged_idea_id, payload, revision_count, reviewer_pass")
        .eq("artifact_type", "ceo_brief")
        .limit(limit * 2)
        .execute()
        .data
    )
    pending = [r for r in (all_rows or []) if r.get("reviewer_pass") is not True][:limit]
    if not pending:
        print("[plan_reviewer] no ceo_brief artifacts pending review (all passed or none found)")
        return

    for row in pending:
        idea_id = row["judged_idea_id"]
        brief = json.dumps(row["payload"], indent=2)
        prompt = (
            f"CHECKLIST:\n{checks_text}\n\n"
            f"CEO Briefing for idea {idea_id}:\n\n{brief}\n\n"
            "Assess the briefing against the checklist above. Output only PASS, REVISE, or ESCALATE with failed_checks and revision_notes as per the rules."
        )
        response = call_agent(
            "plan_reviewer",
            REVIEWER_SYSTEM_INSTRUCTIONS,
            prompt,
            schema=PLAN_REVIEWER_SCHEMA,
            effort="low",
        )
        text = get_response_text(response)
        result = json.loads(text)
        try:
            if result["verdict"] == "PASS":
                supabase.table("planning_artifacts").update(
                    {"reviewer_pass": True, "reviewer_notes": result.get("revision_notes") or ""}
                ).eq("id", row["id"]).execute()
            elif result["verdict"] == "REVISE":
                supabase.table("planning_artifacts").update(
                    {
                        "reviewer_pass": False,
                        "reviewer_notes": result.get("revision_notes") or "",
                        "revision_count": row.get("revision_count", 0) + 1,
                    }
                ).eq("id", row["id"]).execute()
            else:
                supabase.table("planning_artifacts").update(
                    {
                        "reviewer_notes": "ESCALATED: " + (result.get("revision_notes") or ""),
                        "reviewer_pass": None,
                    }
                ).eq("id", row["id"]).execute()
            print(f"[plan_reviewer] updated planning_artifacts for {idea_id}")
        except Exception as e:
            print(f"[plan_reviewer] failed to update review for {idea_id}: {e}")


def run_plan_reviewer_for_idea(idea_id: str) -> None:
    res = (
        supabase.table("planning_artifacts")
        .select("id, payload, revision_count")
        .eq("judged_idea_id", idea_id)
        .eq("artifact_type", "ceo_brief")
        .limit(1)
        .execute()
    )
    if not res.data:
        print(f"[plan_reviewer] skip {idea_id}: no ceo_brief artifact in planning_artifacts")
        return
    with open("config/plan_reviewer_checklist.yaml") as f:
        checklist = yaml.safe_load(f)
    checks_text = _checks_text(checklist)
    row = res.data[0]
    brief = json.dumps(row["payload"], indent=2)
    prompt = (
        f"CHECKLIST:\n{checks_text}\n\n"
        f"CEO Briefing for idea {idea_id}:\n\n{brief}\n\n"
        "Assess the briefing against the checklist above. Output only PASS, REVISE, or ESCALATE with failed_checks and revision_notes as per the rules."
    )
    response = call_agent(
        "plan_reviewer",
        REVIEWER_SYSTEM_INSTRUCTIONS,
        prompt,
        schema=PLAN_REVIEWER_SCHEMA,
        effort="low",
    )
    text = get_response_text(response)
    result = json.loads(text)
    try:
        if result["verdict"] == "PASS":
            supabase.table("planning_artifacts").update(
                {"reviewer_pass": True, "reviewer_notes": result.get("revision_notes") or ""}
            ).eq("id", row["id"]).execute()
        elif result["verdict"] == "REVISE":
            supabase.table("planning_artifacts").update(
                {
                    "reviewer_pass": False,
                    "reviewer_notes": result.get("revision_notes") or "",
                    "revision_count": row.get("revision_count", 0) + 1,
                }
            ).eq("id", row["id"]).execute()
        else:
            supabase.table("planning_artifacts").update(
                {
                    "reviewer_notes": "ESCALATED: " + (result.get("revision_notes") or ""),
                    "reviewer_pass": None,
                }
            ).eq("id", row["id"]).execute()
        print(f"[plan_reviewer] updated planning_artifacts for {idea_id}")
    except Exception as e:
        print(f"[plan_reviewer] failed to update review for {idea_id}: {e}")
