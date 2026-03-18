"""Project Manager: synthesizes architect, design, and marketing plans into a CEO briefing.

This agent uses Claude Opus 4.6 with the Compaction API (interleaved thinking beta)
so it can handle very large combined inputs.
"""

import copy
import json
from datetime import datetime, timezone

from anthropic import AsyncAnthropic

from utils.claude_client import _sanitize_schema
from utils.env import settings
from utils.supabase_client import supabase


CEO_BRIEFING_SCHEMA = {
    "type": "object",
    "properties": {
        "idea_summary": {"type": "string"},
        "market_validation": {"type": "string"},
        "technical_plan": {"type": "string"},
        "design_direction": {"type": "string"},
        "gtm_strategy": {"type": "string"},
        "budget_breakdown": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "monthly_cost": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["item", "monthly_cost", "source"],
            },
        },
        "ceo_action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "where": {"type": "string"},
                    "cost": {"type": "string"},
                    "unblocks": {"type": "string"},
                    "dependencies": {"type": "string"},
                },
                "required": ["action", "where", "cost", "unblocks", "dependencies"],
            },
        },
        "risks_and_mitigations": {"type": "string"},
        "phased_roadmap": {
            "type": "object",
            "properties": {
                "mvp": {"type": "array", "items": {"type": "string"}},
                "v1": {"type": "array", "items": {"type": "string"}},
                "target_dates": {"type": "string"},
            },
        },
        "projected_mrr": {
            "type": "object",
            "properties": {
                "day_30": {"type": "string"},
                "day_60": {"type": "string"},
                "day_90": {"type": "string"},
                "assumptions": {"type": "string"},
            },
            "required": ["day_30", "day_60", "day_90", "assumptions"],
        },
    },
    "required": [
        "idea_summary",
        "market_validation",
        "technical_plan",
        "design_direction",
        "gtm_strategy",
        "budget_breakdown",
        "ceo_action_items",
        "risks_and_mitigations",
        "phased_roadmap",
        "projected_mrr",
    ],
}


PM_SYSTEM_PROMPT = """You are an executive-level project manager.

Your job is to synthesize multiple validated plans into a single CEO briefing that will be sent to Notion (or similar tools) for the CEO to read and decide on.

**Language and clarity**
- Use plain, executive-friendly language. Avoid jargon; if a technical term is needed, add a one-line explanation in parentheses.
- Write in clear, short sentences. One idea per sentence where possible.
- No TBD, placeholders, or "to be determined". Every section must be complete and specific.

**Structure and readability**
- Each schema field will be shown as a section (e.g. in Notion). Make each section scannable:
  - Start with the main takeaway or summary line, then add detail.
  - Use line breaks to separate distinct points.
  - For lists (e.g. MVP steps, action items), use bullet-style formatting: start each item with "- " or "• " on its own line.
- idea_summary: 2–4 sentences max. What we're building and why it matters.
- market_validation, technical_plan, design_direction, gtm_strategy, risks_and_mitigations: short paragraphs or bullet points; no walls of text.
- budget_breakdown and ceo_action_items: each entry must be clearly labeled and readable (e.g. "Item: X | Cost: Y | Source: Z" or one line per field).
- phased_roadmap: mvp and v1 as clear bullet lists; target_dates in plain language (e.g. "MVP: 4 weeks from kickoff; V1: +6 weeks").
- projected_mrr: numbers with units (e.g. "$500" or "€1.2k"); assumptions in 2–3 short sentences.

**Consistency**
- Use the same tone throughout: direct, confident, and actionable.
- Reference the source plans where it helps (e.g. "Per architect plan: ...") but keep the briefing self-contained.

Produce a JSON object matching the provided schema. The content of every string and array item must be human-readable and well-structured for display in Notion or similar tools.
"""


async def run_project_manager(idea: dict, arch_plan: dict, design_plan: dict, mktg_plan: dict):
    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    user_content = f"""
    Synthesize these three validated plans into one CEO Briefing.
    Resolve all contradictions. Extract all CEO action items.
    Build the phased roadmap. Calculate total budget.

    ARCHITECT PLAN:
    {json.dumps(arch_plan, indent=2)}

    DESIGNER BRIEF:
    {json.dumps(design_plan, indent=2)}

    MARKETING PLAN:
    {json.dumps(mktg_plan, indent=2)}
    """

    schema_payload = copy.deepcopy(CEO_BRIEFING_SCHEMA)
    _sanitize_schema(schema_payload)

    response = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8000,
        system=[
            {
                "type": "text",
                "text": PM_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
        output_config={"format": {"type": "json_schema", "schema": schema_payload}},
    )

    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _save_brief(idea_id: str, brief: dict) -> str:
    """Save CEO brief to planning_artifacts (upsert); return reference for ceo_brief_path."""
    try:
        supabase.table("planning_artifacts").upsert(
            {
                "judged_idea_id": idea_id,
                "artifact_type": "ceo_brief",
                "payload": brief,
                "reviewer_pass": False,
                "reviewer_notes": None,
                "revision_count": 0,
            },
            on_conflict="judged_idea_id,artifact_type",
        ).execute()
    except Exception as e:
        print(f"[pm] failed to save ceo_brief to planning_artifacts: {e}")
    return f"planning_artifacts:{idea_id}"


async def _push_to_notion(idea_id: str, brief: dict) -> None:
    token = settings.NOTION_TOKEN
    db_id = settings.NOTION_DATABASE_ID
    if not token or not db_id:
        print("[pm] Notion not configured; skipping push")
        return

    import requests

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            "Name": {"title": [{"text": {"content": f"CEO Brief {idea_id}"}}]},
            "Idea ID": {"rich_text": [{"text": {"content": idea_id}}]},
            "Date": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"text": [{"type": "text", "text": {"content": json.dumps(brief, indent=2)}}]},
            }
        ],
    }

    resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
    if not resp.ok:
        print(f"[pm] Notion push failed: {resp.status_code} {resp.text}")
    else:
        print(f"[pm] Pushed CEO brief for {idea_id} to Notion")


def _send_notification(idea_id: str, brief_path: str, notion_url: str | None) -> None:
    if not settings.RESEND_API_KEY or not settings.CEO_EMAIL:
        print("[pm] Email notification not configured; skipping")
        return

    import resend

    resend.api_key = settings.RESEND_API_KEY
    subject = f"CEO Brief Ready: {idea_id}"

    approve_link = f"mailto:{settings.CEO_EMAIL}?subject=APPROVE%20%E2%80%94%20{idea_id}"
    reject_link = f"mailto:{settings.CEO_EMAIL}?subject=REJECT%20%E2%80%94%20{idea_id}"
    changes_link = f"mailto:{settings.CEO_EMAIL}?subject=CHANGES%20%E2%80%94%20{idea_id}"

    body_lines = [
        f"The CEO briefing is ready: {brief_path}",
    ]
    if notion_url:
        body_lines.append(f"Notion: {notion_url}")
    body_lines.append("")
    body_lines.append(f"Approve: {approve_link}")
    body_lines.append(f"Reject: {reject_link}")
    body_lines.append(f"Request changes: {changes_link}")

    body = "\n".join(body_lines)

    try:
        resend.Emails.send(
            {
                "from": "FORGE Briefing <digest@yourdomain.com>",
                "to": [settings.CEO_EMAIL],
                "subject": subject,
                "text": body,
            }
        )
        print(f"[pm] Notification sent to {settings.CEO_EMAIL}")
    except Exception as e:
        print(f"[pm] Notification failed: {e}")


def _get_latest_artifact(idea_id: str, artifact_type: str) -> dict | None:
    """Load latest planning_artifacts row by judged_idea_id and artifact_type."""
    res = (
        supabase.table("planning_artifacts")
        .select("payload")
        .eq("judged_idea_id", idea_id)
        .eq("artifact_type", artifact_type)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0]["payload"] if res.data else None


def get_idea_id_with_plans(idea_id: str | None = None) -> str | None:
    """Return idea_id if it has architect+designer+marketing artifacts; else first such judged_idea_id or None."""
    if idea_id and idea_id != "1":
        arch = _get_latest_artifact(idea_id, "architect")
        design = _get_latest_artifact(idea_id, "designer")
        mktg = _get_latest_artifact(idea_id, "marketing")
        if arch and design and mktg:
            return idea_id
        return None
    r = (
        supabase.table("planning_artifacts")
        .select("judged_idea_id")
        .eq("artifact_type", "architect")
        .limit(500)
        .execute()
    )
    ids = list({x["judged_idea_id"] for x in (r.data or [])})
    for i in ids:
        if _get_latest_artifact(i, "designer") and _get_latest_artifact(i, "marketing"):
            return i
    return None


async def run_project_manager_pipeline(idea_id: str) -> None:
    """Runs the full PM pipeline for one idea ID. Loads plans from planning_artifacts."""

    arch_plan = _get_latest_artifact(idea_id, "architect")
    design_plan = _get_latest_artifact(idea_id, "designer")
    mktg_plan = _get_latest_artifact(idea_id, "marketing")

    if not arch_plan or not design_plan or not mktg_plan:
        print(f"[pm] missing inputs for {idea_id} in planning_artifacts")
        return

    brief = await run_project_manager({}, arch_plan, design_plan, mktg_plan)
    brief_path = _save_brief(idea_id, brief)

    notion_url = None
    try:
        from utils.notion_client import push_briefing_to_notion

        # In absence of a judge score, we default to 0.
        judge_score = 0
        notion_url = push_briefing_to_notion(brief, judge_score)
        if notion_url:
            print(f"[pm] Notion brief: {notion_url}")
    except Exception as e:
        print(f"[pm] Notion push failed: {e}")

    if notion_url:
        try:
            supabase.table("judged_ideas").update(
                {"notion_url": notion_url, "ceo_brief_path": brief_path}
            ).eq("id", idea_id).execute()
        except Exception as e:
            print(f"[pm] Failed to save Notion URL to Supabase: {e}")

    _send_notification(idea_id, brief_path, notion_url)

    print(f"[pm] CEO brief generated and saved to {brief_path}")
