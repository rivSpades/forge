"""Designer agent: creates product naming, branding, and UX direction.

The Designer uses claude-sonnet-4-6 with web search enabled to validate:
- social handle availability (Twitter, Instagram)
- brand visuals / color palette fit for the product category
- name trademark status for the category

Output is stored to disk for review.
"""

import json

from utils.claude_client import call_agent, async_call_agent, get_response_text
from utils.supabase_client import supabase


DESIGNER_SCHEMA = {
    "type": "object",
    "properties": {
        "product_names": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "domain_available": {"type": "boolean"},
                    "twitter_available": {"type": "boolean"},
                    "instagram_available": {"type": "boolean"},
                    "rationale": {"type": "string"},
                },
                "required": ["name", "rationale"],
            },
        },
        "recommended_name": {"type": "string"},
        "tone_adjectives": {"type": "array", "items": {"type": "string"}, "minItems": 3},
        "example_social_post": {"type": "string"},
        "colors": {
            "type": "object",
            "properties": {
                "primary": {"type": "string"},
                "accent1": {"type": "string"},
                "accent2": {"type": "string"},
            },
        },
        "fonts": {
            "type": "object",
            "properties": {
                "display": {"type": "string"},
                "body": {"type": "string"},
            },
        },
        "user_flows": {"type": "array", "items": {"type": "string"}},
        "key_screens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "screen_name": {"type": "string"},
                    "description": {"type": "string"},
                    "loading_state": {"type": "string"},
                    "empty_state": {"type": "string"},
                    "error_state": {"type": "string"},
                },
                "required": [
                    "screen_name",
                    "description",
                    "loading_state",
                    "empty_state",
                    "error_state",
                ],
            },
        },
    },
    "required": [
        "product_names",
        "recommended_name",
        "tone_adjectives",
        "example_social_post",
        "colors",
        "fonts",
        "user_flows",
        "key_screens",
    ],
}


DESIGNER_SYSTEM_PROMPT = """You are a product designer and branding expert.

You will propose product names, branding directions, color palettes, and core UX flows.
Use web search to validate:
- whether recommended social handles are available (search for twitter.com/handle and instagram.com/handle)
- whether the chosen palette fits the product category by looking at competitors
- whether the proposed product name is already trademarked in the relevant category

Output must match the schema exactly.
"""


def run_designer(limit: int = 3) -> None:
    """Generate design artifacts. Prioritize revision candidates (reviewer_pass=False + reviewer_notes), then new GO ideas."""
    import yaml
    with open("config/design_reviewer_checklist.yaml") as f:
        checklist = yaml.safe_load(f)

    # 1) Revision candidates first (any with reviewer feedback; no revision_count cap so manual re-runs always work)
    revision_rows = (
        supabase.table("planning_artifacts")
        .select("id, judged_idea_id, reviewer_notes, revision_count")
        .eq("artifact_type", "designer")
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
        prompt = _record_to_prompt(record) + _revision_prompt_suffix(idea_id, "designer")
        try:
            response = call_agent(
                "designer",
                DESIGNER_SYSTEM_PROMPT,
                prompt,
                schema=DESIGNER_SCHEMA,
                tools=["web_search"],
            )
        except Exception as e:
            print(f"[designer] failed for {idea_id}: {e}")
            continue
        text = get_response_text(response)
        try:
            plan = json.loads(text)
        except Exception:
            if "Message(id=" in text or text.strip().startswith("Message("):
                print(f"[designer] skipping {idea_id}: response was raw API Message (tool loop may not have returned text)")
                continue
            plan = {"raw": text}
        try:
            supabase.table("planning_artifacts").upsert(
                {
                    "judged_idea_id": idea_id,
                    "artifact_type": "designer",
                    "payload": plan,
                    "reviewer_pass": False,
                    "reviewer_notes": None,
                    "revision_count": (row.get("revision_count") or 0) + 1,
                },
                on_conflict="judged_idea_id,artifact_type",
            ).execute()
            print(f"[designer] saved revision for {idea_id} to planning_artifacts")
        except Exception as e:
            print(f"[designer] failed to save planning_artifacts for {idea_id}: {e}")

    remaining = limit - len(revision_rows)
    if remaining <= 0:
        return

    # 2) New GO ideas (no designer artifact or already passed)
    have_designer = {
        r["judged_idea_id"]
        for r in (
            supabase.table("planning_artifacts")
            .select("judged_idea_id")
            .eq("artifact_type", "designer")
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
    pending = [r for r in pending if r["id"] not in have_designer][:remaining]

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
            "Provide naming, branding, and UX direction according to the schema."
        )
        try:
            response = call_agent(
                "designer",
                DESIGNER_SYSTEM_PROMPT,
                prompt,
                schema=DESIGNER_SCHEMA,
                tools=["web_search"],
            )
        except Exception as e:
            print(f"[designer] failed for {record['id']}: {e}")
            continue
        text = get_response_text(response)
        try:
            plan = json.loads(text)
        except Exception:
            if "Message(id=" in text or text.strip().startswith("Message("):
                print(f"[designer] skipping {record['id']}: response was raw API Message (tool loop may not have returned text)")
                continue
            plan = {"raw": text}
        try:
            supabase.table("planning_artifacts").upsert(
                {
                    "judged_idea_id": record["id"],
                    "artifact_type": "designer",
                    "payload": plan,
                    "reviewer_pass": False,
                    "reviewer_notes": None,
                    "revision_count": 0,
                },
                on_conflict="judged_idea_id,artifact_type",
            ).execute()
            print(f"[designer] saved design output for {record['id']} to planning_artifacts")
        except Exception as e:
            print(f"[designer] failed to save planning_artifacts for {record['id']}: {e}")


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
    """Append REVISION request and reviewer notes (Analyst-style) so the agent addresses them."""
    notes = _get_reviewer_notes(idea_id, artifact_type)
    if not notes:
        return ""
    return (
        "\n\nREVISION request.\n\n"
        f"Reviewer notes: {notes}\n\n"
        "Please update the design based on the reviewer feedback."
    )


def _record_to_prompt(record: dict) -> str:
    """Build designer prompt from judged_ideas record."""
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
        "Provide naming, branding, and UX direction according to the schema."
    )


async def run_designer_for_idea(idea_id: str, record: dict) -> dict:
    """Run designer for a single idea (async, for parallel Phase 2 pipeline)."""
    prompt = _record_to_prompt(record) + _revision_prompt_suffix(idea_id, "designer")
    response = await async_call_agent(
        "designer",
        DESIGNER_SYSTEM_PROMPT,
        prompt,
        schema=DESIGNER_SCHEMA,
        tools=["web_search"],
    )
    text = get_response_text(response)
    try:
        plan = json.loads(text)
    except json.JSONDecodeError:
        if "Message(id=" in text or text.strip().startswith("Message("):
            raise ValueError("Designer response was raw API Message; tool loop did not return JSON")
        raise
    revision_count = 0
    existing = (
        supabase.table("planning_artifacts")
        .select("revision_count, reviewer_notes")
        .eq("judged_idea_id", idea_id)
        .eq("artifact_type", "designer")
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
                "artifact_type": "designer",
                "payload": plan,
                "reviewer_pass": False,
                "reviewer_notes": None,
                "revision_count": revision_count,
            },
            on_conflict="judged_idea_id,artifact_type",
        ).execute()
        print(f"[designer] saved design output for {idea_id} to planning_artifacts")
    except Exception as e:
        print(f"[designer] failed to save planning_artifacts for {idea_id}: {e}")
    return plan
