"""Marketing Strategist agent: finds competitor pricing, communities, and CPC estimates.

The Strategist uses web search to locate real pricing pages, community hubs, and
CPC information for proposed channels.
"""

import json

import yaml

from utils.claude_client import call_agent, async_call_agent, get_response_text
from utils.supabase_client import supabase


MARKETING_SCHEMA = {
    "type": "object",
    "properties": {
        "competitor_pricing": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "pricing_page": {"type": "string"},
                    "pricing_summary": {"type": "string"},
                },
                "required": ["name", "pricing_page", "pricing_summary"],
            },
        },
        "communities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "audience": {"type": "string"},
                },
                "required": ["name", "url", "audience"],
            },
        },
        "paid_channels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string"},
                    "tactic": {"type": "string"},
                    "cpc_estimate": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["channel", "tactic", "cpc_estimate", "source_url"],
            },
        },
        "brand_positioning": {"type": "string"},
        "key_metrics": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "competitor_pricing",
        "communities",
        "paid_channels",
        "brand_positioning",
        "key_metrics",
    ],
}


MARKETING_SYSTEM_PROMPT = """You are a marketing strategist. Your output will be reviewed against a strict checklist. Use web search to gather real data; do not guess or use placeholders.

Ideal customer profile: Define one specific persona, not a vague segment. Include role, scale (e.g. team size or revenue), geography, and main pain point. Wrong: "small businesses", "creators", "agencies". Right: "OF agency owner, 5–20 models, US/UK, running paid ads, $10k–50k/month". Put this in ideal_customer_profile.

Competitor pricing: List only competitors where you have a working direct pricing URL (e.g. /pricing or /plans). If a competitor has no real pricing page or you only find a blog post, do not include them—replace with one that has a verifiable pricing page or drop the entry. Never cite "third-party review aggregators" or similar without a direct URL; if you cannot find a direct source for the figures, omit that competitor. If the only reference is a blog, you may use it only when unavoidable and must say in pricing_summary that it is the only available reference (e.g. "Pricing only found in blog; no dedicated pricing page").

Communities: Every URL must point to a specific, relevant destination. For forums, link to the exact subforum or thread for the ICP (e.g. onlyfans-marketing subforum), not the main forum index. For Telegram or other groups, use only links you can treat as real and current; if a link is unverifiable or dead, replace it with a confirmed active community or remove it. No generic index pages.

Paid channels: For each recommended channel give a concrete tactic, not just the channel name. Every CPC estimate must have a source_url (tool, benchmark, or advertiser resource). No figures without a URL.

Output the exact schema fields. Before returning, check: ICP is a concrete persona; every pricing entry has a real pricing URL and no aggregator-only citations; every community URL is specific and verifiable; every channel has a tactic and every CPC has a source_url."""


def run_marketing_strategist(limit: int = 3) -> None:
    """Generate marketing strategy. Prioritize revision candidates (reviewer_pass=False + reviewer_notes), then new GO ideas."""
    with open("config/marketing_reviewer_checklist.yaml") as f:
        checklist = yaml.safe_load(f)

    # 1) Revision candidates first (any with reviewer feedback; no revision_count cap so manual re-runs always work)
    revision_rows = (
        supabase.table("planning_artifacts")
        .select("id, judged_idea_id, reviewer_notes, revision_count")
        .eq("artifact_type", "marketing")
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
        prompt = _record_to_prompt(record) + _revision_prompt_suffix(idea_id, "marketing")
        try:
            response = call_agent(
                "marketing_strategist",
                MARKETING_SYSTEM_PROMPT,
                prompt,
                schema=MARKETING_SCHEMA,
                tools=["web_search"],
            )
        except Exception as e:
            print(f"[marketing] failed for {idea_id}: {e}")
            continue
        text = get_response_text(response)
        try:
            plan = json.loads(text)
        except Exception:
            if "Message(id=" in text or text.strip().startswith("Message("):
                print(f"[marketing] skipping {idea_id}: response was raw API Message (tool loop may not have returned text)")
                continue
            plan = {"raw": text}
        try:
            supabase.table("planning_artifacts").upsert(
                {
                    "judged_idea_id": idea_id,
                    "artifact_type": "marketing",
                    "payload": plan,
                    "reviewer_pass": False,
                    "reviewer_notes": None,
                    "revision_count": (row.get("revision_count") or 0) + 1,
                },
                on_conflict="judged_idea_id,artifact_type",
            ).execute()
            print(f"[marketing] saved revision for {idea_id} to planning_artifacts")
        except Exception as e:
            print(f"[marketing] failed to save planning_artifacts for {idea_id}: {e}")

    remaining = limit - len(revision_rows)
    if remaining <= 0:
        return

    # 2) New GO ideas (no marketing artifact yet)
    have_marketing = {
        r["judged_idea_id"]
        for r in (
            supabase.table("planning_artifacts")
            .select("judged_idea_id")
            .eq("artifact_type", "marketing")
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
    pending = [r for r in pending if r["id"] not in have_marketing][:remaining]

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
            "Provide a marketing strategy matching the schema."
        )
        try:
            response = call_agent(
                "marketing_strategist",
                MARKETING_SYSTEM_PROMPT,
                prompt,
                schema=MARKETING_SCHEMA,
                tools=["web_search"],
            )
        except Exception as e:
            print(f"[marketing] failed for {record['id']}: {e}")
            continue
        text = get_response_text(response)
        try:
            plan = json.loads(text)
        except Exception:
            if "Message(id=" in text or text.strip().startswith("Message("):
                print(f"[marketing] skipping {record['id']}: response was raw API Message (tool loop may not have returned text)")
                continue
            plan = {"raw": text}
        try:
            supabase.table("planning_artifacts").upsert(
                {
                    "judged_idea_id": record["id"],
                    "artifact_type": "marketing",
                    "payload": plan,
                    "reviewer_pass": False,
                    "reviewer_notes": None,
                    "revision_count": 0,
                },
                on_conflict="judged_idea_id,artifact_type",
            ).execute()
            print(f"[marketing] saved strategy for {record['id']} to planning_artifacts")
        except Exception as e:
            print(f"[marketing] failed to save planning_artifacts for {record['id']}: {e}")


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
        "Please update the marketing strategy based on the reviewer feedback."
    )


def _record_to_prompt(record: dict) -> str:
    """Build marketing strategist prompt from judged_ideas record."""
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
        "Provide a marketing strategy matching the schema."
    )


async def run_marketing_strategist_for_idea(idea_id: str, record: dict) -> dict:
    """Run marketing strategist for a single idea (async, for parallel Phase 2 pipeline)."""
    prompt = _record_to_prompt(record) + _revision_prompt_suffix(idea_id, "marketing")
    response = await async_call_agent(
        "marketing_strategist",
        MARKETING_SYSTEM_PROMPT,
        prompt,
        schema=MARKETING_SCHEMA,
        tools=["web_search"],
    )
    text = get_response_text(response)
    try:
        plan = json.loads(text)
    except json.JSONDecodeError:
        if "Message(id=" in text or text.strip().startswith("Message("):
            raise ValueError("Marketing response was raw API Message; tool loop did not return JSON")
        raise
    revision_count = 0
    existing = (
        supabase.table("planning_artifacts")
        .select("revision_count, reviewer_notes")
        .eq("judged_idea_id", idea_id)
        .eq("artifact_type", "marketing")
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
                "artifact_type": "marketing",
                "payload": plan,
                "reviewer_pass": False,
                "reviewer_notes": None,
                "revision_count": revision_count,
            },
            on_conflict="judged_idea_id,artifact_type",
        ).execute()
        print(f"[marketing] saved strategy for {idea_id} to planning_artifacts")
    except Exception as e:
        print(f"[marketing] failed to save planning_artifacts for {idea_id}: {e}")
    return plan
