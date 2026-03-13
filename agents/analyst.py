"""Analyst agent: deep market research using Claude's native web_search tool.

This agent reads unprocessed ideas from raw_ideas, runs a research prompt in Claude,
and stores the structured report in analyzed_ideas.
"""

import json

import yaml

from utils.claude_client import call_agent
from utils.supabase_client import supabase


ANALYST_SYSTEM = """
You are a Senior Market Research Analyst. For the given product idea,
perform deep research and produce a structured feasibility report.

RESEARCH RULES:
- Search for at least 3 real competitors. Include their URL and pricing.
- Search for market size data. Cite the source in your response.
- Search for "[idea] reddit" to find real user complaints about existing tools.
- Never state a market size without a source.
- Never name a competitor without confirming it exists via search.
- If data is unavailable, write INSUFFICIENT_DATA and explain what is missing.

Produce the report matching the required JSON schema exactly.
"""

ANALYST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "market_size_estimate": {"type": "string"},
        "market_size_source": {"type": "string"},
        "competitors": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "pricing": {"type": "string"},
                    "weakness": {"type": "string"},
                },
                "required": ["name", "url", "pricing", "weakness"],
            },
        },
        "monetization_model": {"type": "string"},
        "effort_score": {"type": "integer", "minimum": 1, "maximum": 10},
        "revenue_score": {"type": "integer", "minimum": 1, "maximum": 10},
        "risks": {
            "type": "array",
            "minItems": 3,
            "items": {"type": "string"},
        },
        "assessment": {"type": "string"},
    },
    "required": [
        "market_size_estimate",
        "market_size_source",
        "competitors",
        "monetization_model",
        "effort_score",
        "revenue_score",
        "risks",
        "assessment",
    ],
}


def run_analyst(limit: int = 5) -> None:
    """Process unprocessed raw ideas and reprocess ideas flagged for revision."""

    # Load review thresholds so we can re-run analysis for items that need revisions.
    with open("config/reviewer_checklist.yaml") as f:
        checklist = yaml.safe_load(f)

    max_revisions = checklist.get("thresholds", {}).get("max_revisions", 2)

    # 1) Re-run analysis for ideas the reviewer flagged for revision (up to the limit).
    revision_candidates = (
        supabase.table("analyzed_ideas")
        .select("id, raw_idea_id, reviewer_notes, revision_count, raw_ideas(post_title, body_text)")
        .eq("reviewer_pass", False)
        .neq("reviewer_notes", None)
        .lte("revision_count", max_revisions)
        .limit(limit)
        .execute()
        .data
    )

    remaining = limit - len(revision_candidates)

    # 2) If we still have budget, process new raw ideas.
    new_ideas = []
    if remaining > 0:
        new_ideas = (
            supabase.table("raw_ideas")
            .select("*, analyzed_ideas(id)")
            .eq("processed", False)
            .limit(remaining)
            .execute()
            .data
        )

    # Process revisions first, then new ideas.
    for record in revision_candidates:
        raw = record.get("raw_ideas") or {}
        reviewer_notes = record.get("reviewer_notes") or ""
        prompt = (
            f"Research this idea (REVISION request).\n\n" \
            f"Title: {raw.get('post_title')}\n\n" \
            f"Body: {raw.get('body_text', '')[:1500]}\n\n" \
            f"Reviewer notes: {reviewer_notes}\n\n" \
            "Please update the report based on the reviewer feedback."
        )

        response = call_agent(
            "analyst",
            ANALYST_SYSTEM,
            prompt,
            schema=ANALYST_SCHEMA,
        )

        report_text = next(b.text for b in response.content if b.type == "text")
        report = json.loads(report_text)

        supabase.table("analyzed_ideas").update(
            {
                "report": report,
                "reviewer_notes": None,
                "revision_count": (record.get("revision_count") or 0) + 1,
            }
        ).eq("id", record["id"]).execute()

    for idea in new_ideas:
        response = call_agent(
            "analyst",
            ANALYST_SYSTEM,
            f"Research this idea:\n\n{idea['post_title']}\n\n{idea['body_text'][:1500]}",
            schema=ANALYST_SCHEMA,
        )

        report_text = next(b.text for b in response.content if b.type == "text")
        report = json.loads(report_text)

        supabase.table("analyzed_ideas").insert(
            {"raw_idea_id": idea["id"], "report": report}
        ).execute()
        supabase.table("raw_ideas").update({"processed": True}).eq("id", idea["id"]).execute()
