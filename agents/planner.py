"""Phase 2 planning pipeline: parallel Architect + Designer + Marketing → PM → Notion.

When the CEO marks an idea as interested (plan_requested=True), this pipeline:
1. Runs Architect, Designer, and Marketing Strategist in parallel (asyncio, 4h timeout).
2. Runs each paired Reviewer on the outputs.
3. Project Manager synthesizes all three into a CEO Briefing.
4. Plan Reviewer reviews the briefing.
5. Pushes the briefing to Notion and marks the request complete.

No LangGraph — pure asyncio with AsyncAnthropic.
"""

import asyncio
from datetime import datetime, timezone

from utils.supabase_client import get_async_supabase

# Parallel planning agents (async, single-idea)
from agents.architect import run_architect_for_idea
from agents.designer import run_designer_for_idea
from agents.marketing_strategist import run_marketing_strategist_for_idea

# Reviewers (sync, single-idea)
from agents.arch_reviewer import run_arch_reviewer_for_idea
from agents.design_reviewer import run_design_reviewer_for_idea
from agents.marketing_reviewer import run_marketing_reviewer_for_idea
from agents.plan_reviewer import run_plan_reviewer_for_idea

# PM synthesis and persistence
from agents.project_manager import run_project_manager, _save_brief, _send_notification
from utils.notion_client import push_briefing_to_notion

PLANNING_TIMEOUT_SECONDS = 14400  # 4 hours


async def _fetch_idea(idea_id: str):
    """Fetch judged idea with analyzed_ideas and raw_ideas. Return record or None."""
    client = await get_async_supabase()
    res = await (
        client.table("judged_ideas")
        .select("*, analyzed_ideas(*, raw_ideas(*))")
        .eq("id", idea_id)
        .eq("plan_requested", True)
        .maybe_single()
        .execute()
    )
    return res.data if res.data else None


def _safe_task_result(task):
    """Return task result or None if not done or raised."""
    if not task.done():
        return None
    try:
        return task.result()
    except Exception:
        return None


async def run_planning_pipeline(idea_id: str) -> None:
    """Run the full Phase 2 pipeline for one idea: parallel planning → reviewers → PM → Notion."""

    record = await _fetch_idea(idea_id)
    if not record:
        return

    # Fire all three planning agents simultaneously
    architect_task = asyncio.create_task(run_architect_for_idea(idea_id, record))
    designer_task = asyncio.create_task(run_designer_for_idea(idea_id, record))
    marketing_task = asyncio.create_task(run_marketing_strategist_for_idea(idea_id, record))

    try:
        arch_plan, design_plan, mktg_plan = await asyncio.wait_for(
            asyncio.gather(architect_task, designer_task, marketing_task),
            timeout=PLANNING_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        arch_plan = _safe_task_result(architect_task)
        design_plan = _safe_task_result(designer_task)
        mktg_plan = _safe_task_result(marketing_task)
        if not (arch_plan and design_plan and mktg_plan):
            print(f"[planner] timeout for {idea_id}; at least one plan missing, continuing with partial")
    except Exception as e:
        arch_plan = _safe_task_result(architect_task)
        design_plan = _safe_task_result(designer_task)
        mktg_plan = _safe_task_result(marketing_task)
        print(f"[planner] planning failed for {idea_id}: {e}; using partial results if any")

    if not arch_plan or not design_plan or not mktg_plan:
        print(f"[planner] skipping PM/Notion for {idea_id}: missing one or more plans")
        return

    # Paired reviewers (sync)
    run_arch_reviewer_for_idea(idea_id)
    run_design_reviewer_for_idea(idea_id)
    run_marketing_reviewer_for_idea(idea_id)

    # PM synthesizes into CEO Briefing
    idea_context = {"id": idea_id, "weighted_total": record.get("weighted_total")}
    brief = await run_project_manager(idea_context, arch_plan, design_plan, mktg_plan)
    brief_path = _save_brief(idea_id, brief)

    # Plan reviewer on the briefing
    run_plan_reviewer_for_idea(idea_id)

    # Push to Notion
    judge_score = float(record.get("weighted_total") or 0)
    notion_url = None
    try:
        notion_url = push_briefing_to_notion(brief, judge_score)
    except Exception as e:
        print(f"[planner] Notion push failed for {idea_id}: {e}")

    # Mark plan_requested False and store notion_url / path
    client = await get_async_supabase()
    await (
        client.table("judged_ideas")
        .update(
            {
                "plan_requested": False,
                "plan_requested_at": datetime.now(timezone.utc).isoformat(),
                "notion_url": notion_url,
                "ceo_brief_path": brief_path,
            }
        )
        .eq("id", idea_id)
        .execute()
    )

    _send_notification(idea_id, brief_path, notion_url)
    print(f"[planner] Phase 2 complete for {idea_id}: brief at {brief_path}, Notion={notion_url or 'n/a'}")