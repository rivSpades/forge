"""Architect agent: recommends a full technical stack and implementation plan.

The Architect uses Claude Opus 4.6 with adaptive thinking and a high effort
setting. It uses web_search to validate current pricing and versioning for
third-party APIs and tools.
"""

import json

import yaml

from utils.claude_client import call_agent, async_call_agent, get_response_text
from utils.supabase_client import supabase


ARCHITECT_SCHEMA = {
    "type": "object",
    "properties": {
        "stack": {
            "type": "object",
            "properties": {
                "frontend": {"type": "string"},
                "backend": {"type": "string"},
                "database": {"type": "string"},
                "auth": {"type": "string"},
                "hosting": {"type": "string"},
                "payments": {"type": "string"},
            },
        },
        "stack_rationale": {"type": "string"},
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "responsibility": {"type": "string"},
                },
                "required": ["name", "responsibility"],
            },
        },
        "features": {
            "type": "object",
            "properties": {
                "mvp": {"type": "array", "items": {"type": "string"}},
                "v1": {"type": "array", "items": {"type": "string"}},
                "later": {"type": "array", "items": {"type": "string"}},
            },
        },
        "third_party_apis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "monthly_cost": {"type": "string"},
                },
                "required": ["name", "purpose", "monthly_cost"],
            },
        },
        "database_schema": {"type": "string"},
        "folder_structure": {"type": "string"},
        "security_design": {"type": "string"},
        "effort_estimate_weeks": {"type": "number"},
    },
    "required": [
        "stack",
        "stack_rationale",
        "components",
        "features",
        "third_party_apis",
        "database_schema",
        "folder_structure",
        "security_design",
        "effort_estimate_weeks",
    ],
}


ARCHITECT_SYSTEM_PROMPT = """You are an expert software architect.

You will recommend a modern, scalable tech stack and implementation plan for a
new product based on the idea description and analysis.

Requirements:
- Use web search to verify current pricing and versioning for every third-party API or tool you recommend.
- Reason about tradeoffs: performance, build speed, cost, and long-term maintainability.
- For a simple tool, be concise. For a complex SaaS product, take more time and justify complexity.
- Output must match the provided JSON schema exactly.
"""


def run_architect(limit: int = 5) -> None:
    """Generate architecture. Prioritize revision candidates (reviewer_pass=False + reviewer_notes), then new GO ideas."""
    with open("config/arch_reviewer_checklist.yaml") as f:
        checklist = yaml.safe_load(f)

    # 1) Revision candidates first (any with reviewer feedback; no revision_count cap so manual re-runs always work)
    revision_rows = (
        supabase.table("planning_artifacts")
        .select("id, judged_idea_id, reviewer_notes, revision_count")
        .eq("artifact_type", "architect")
        .eq("reviewer_pass", False)
        .neq("reviewer_notes", None)
        .limit(limit)
        .execute()
        .data
    )
    if revision_rows is None:
        revision_rows = []

    for row in revision_rows:
        idea_id = row["judged_idea_id"]
        record_res = (
            supabase.table("judged_ideas")
            .select("id, analyzed_idea_id, verdict, analyzed_ideas(*, raw_ideas(*))")
            .eq("id", idea_id)
            .single()
            .execute()
        )
        if not record_res.data:
            continue
        record = record_res.data
        prompt = _record_to_prompt(record) + _revision_prompt_suffix(idea_id, "architect")
        try:
            response = call_agent(
                "architect",
                ARCHITECT_SYSTEM_PROMPT,
                prompt,
                schema=ARCHITECT_SCHEMA,
                tools=["web_search"],
            )
        except Exception as e:
            print(f"[architect] failed for {idea_id}: {e}")
            continue
        text = get_response_text(response)
        try:
            plan_payload = json.loads(text)
        except Exception:
            plan_payload = {"raw": text}
        try:
            supabase.table("planning_artifacts").upsert(
                {
                    "judged_idea_id": idea_id,
                    "artifact_type": "architect",
                    "payload": plan_payload,
                    "reviewer_pass": False,
                    "reviewer_notes": None,
                    "revision_count": (row.get("revision_count") or 0) + 1,
                },
                on_conflict="judged_idea_id,artifact_type",
            ).execute()
            print(f"[architect] saved revision for {idea_id} to planning_artifacts")
        except Exception as e:
            print(f"[architect] failed to save planning_artifacts for {idea_id}: {e}")

    remaining = limit - len(revision_rows)
    if remaining <= 0:
        return

    # 2) New GO ideas (no architect artifact yet)
    have_architect = {
        r["judged_idea_id"]
        for r in (
            supabase.table("planning_artifacts")
            .select("judged_idea_id")
            .eq("artifact_type", "architect")
            .execute()
            .data
        )
    }
    pending = (
        supabase.table("judged_ideas")
        .select("id, analyzed_idea_id, verdict, analyzed_ideas(*, raw_ideas(*))")
        .eq("verdict", "GO")
        .execute()
        .data
    )
    pending = [r for r in pending if r["id"] not in have_architect][:remaining]

    for record in pending:
        idea = record.get("analyzed_ideas")
        if isinstance(idea, list):
            idea = idea[0] if idea else {}
        raw = (idea.get("raw_ideas") or {})
        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        idea_text = raw.get("post_title", "") + "\n\n" + raw.get("body_text", "")
        analysis = idea.get("report", {})
        prompt = (
            f"Idea: {idea_text}\n\n"
            f"Analysis:\n{json.dumps(analysis, indent=2)}\n\n"
            "Please produce a detailed architecture recommendation matching the schema."
        )
        try:
            response = call_agent(
                "architect",
                ARCHITECT_SYSTEM_PROMPT,
                prompt,
                schema=ARCHITECT_SCHEMA,
                tools=["web_search"],
            )
        except Exception as e:
            print(f"[architect] failed for {record['id']}: {e}")
            continue
        text = get_response_text(response)
        try:
            plan_payload = json.loads(text)
        except Exception:
            plan_payload = {"raw": text}
        try:
            supabase.table("planning_artifacts").upsert(
                {
                    "judged_idea_id": record["id"],
                    "artifact_type": "architect",
                    "payload": plan_payload,
                    "reviewer_pass": False,
                    "reviewer_notes": None,
                    "revision_count": 0,
                },
                on_conflict="judged_idea_id,artifact_type",
            ).execute()
            print(f"[architect] saved architecture for {record['id']} to planning_artifacts")
        except Exception as e:
            print(f"[architect] failed to save planning_artifacts for {record['id']}: {e}")


def _get_reviewer_notes(idea_id: str, artifact_type: str) -> str | None:
    """Return reviewer_notes from planning_artifacts if present (for revision rounds)."""
    res = (
        supabase.table("planning_artifacts")
        .select("reviewer_notes")
        .eq("judged_idea_id", idea_id)
        .eq("artifact_type", artifact_type)
        .limit(1)
        .execute()
    )
    if not res.data or not res.data[0].get("reviewer_notes"):
        return None
    s = (res.data[0]["reviewer_notes"] or "").strip()
    return s if s else None


def _revision_prompt_suffix(idea_id: str, artifact_type: str) -> str:
    """Append REVISION request and reviewer notes (Analyst-style)."""
    notes = _get_reviewer_notes(idea_id, artifact_type)
    if not notes:
        return ""
    return (
        "\n\nREVISION request.\n\n"
        f"Reviewer notes: {notes}\n\n"
        "Please update the architecture based on the reviewer feedback."
    )


def _record_to_prompt(record: dict) -> str:
    """Build architect prompt from judged_ideas record (with analyzed_ideas, raw_ideas)."""
    idea = record.get("analyzed_ideas")
    if isinstance(idea, list):
        idea = idea[0] if idea else {}
    raw = idea.get("raw_ideas") or {}
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    idea_text = raw.get("post_title", "") + "\n\n" + raw.get("body_text", "")
    analysis = idea.get("report", {})
    return (
        f"Idea: {idea_text}\n\n"
        f"Analysis:\n{json.dumps(analysis, indent=2)}\n\n"
        "Please produce a detailed architecture recommendation matching the schema."
    )


async def run_architect_for_idea(idea_id: str, record: dict) -> dict:
    """Run architect for a single idea (async, for parallel Phase 2 pipeline)."""
    prompt = _record_to_prompt(record) + _revision_prompt_suffix(idea_id, "architect")
    response = await async_call_agent(
        "architect",
        ARCHITECT_SYSTEM_PROMPT,
        prompt,
        schema=ARCHITECT_SCHEMA,
        tools=["web_search"],
    )
    text = get_response_text(response)
    plan = json.loads(text)
    revision_count = 0
    existing = (
        supabase.table("planning_artifacts")
        .select("revision_count, reviewer_notes")
        .eq("judged_idea_id", idea_id)
        .eq("artifact_type", "architect")
        .limit(1)
        .execute()
        .data
    )
    if existing and (existing[0].get("reviewer_notes") or "").strip():
        revision_count = (existing[0].get("revision_count") or 0) + 1
    try:
        supabase.table("planning_artifacts").upsert(
            {
                "judged_idea_id": idea_id,
                "artifact_type": "architect",
                "payload": plan,
                "reviewer_pass": False,
                "reviewer_notes": None,
                "revision_count": revision_count,
            },
            on_conflict="judged_idea_id,artifact_type",
        ).execute()
        print(f"[architect] saved architecture for {idea_id} to planning_artifacts")
    except Exception as e:
        print(f"[architect] failed to save planning_artifacts for {idea_id}: {e}")
    return plan
