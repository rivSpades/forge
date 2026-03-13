"""Judge agent: makes GO/NO-GO decisions using Claude Opus 4.6 with adaptive thinking."""

import json
from typing import Dict

import yaml

from utils.claude_client import call_agent
from utils.supabase_client import supabase


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "market_demand": {"type": "number"},
        "competition_moat": {"type": "number"},
        "build_complexity": {"type": "number"},
        "time_to_revenue": {"type": "number"},
        "capital_required": {"type": "number"},
        "weighted_total": {"type": "number"},
        "verdict": {"type": "string", "enum": ["GO", "NO-GO"]},
        "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "reasoning": {"type": "string"},
    },
    "required": [
        "market_demand",
        "competition_moat",
        "build_complexity",
        "time_to_revenue",
        "capital_required",
        "weighted_total",
        "verdict",
        "confidence",
        "reasoning",
    ],
}


def _build_judge_prompt(rubric: Dict) -> str:
    dims = rubric.get("dimensions", {})
    dim_lines = []
    for name, group in dims.items():
        dim_lines.append(f"### {name.replace('_', ' ').title()}")
        dim_lines.append(f"Weight: {group.get('weight')}")
        for score, desc in group.get("scores", {}).items():
            dim_lines.append(f"  {score}: {desc}")
        dim_lines.append("")

    thresholds = rubric.get("go_threshold"), rubric.get("high_confidence_threshold")
    prompt = f"""You are the Judge. You will score an idea across five dimensions using the rubric below.

{chr(10).join(dim_lines)}

Compute a weighted total score and output a JSON object matching this schema:
{json.dumps(JUDGE_SCHEMA, indent=2)}

Use the thresholds:
- GO if weighted_total >= {thresholds[0]}
- NO-GO if weighted_total < {thresholds[0]}

Set confidence to HIGH if weighted_total >= {thresholds[1]}, otherwise MEDIUM.

Be explicit in reasoning and cite which rubric lines you used for each dimension.
"""

    return prompt


def _format_idea_for_judge(record: Dict) -> str:
    raw = record.get("raw_ideas", {})
    title = raw.get("post_title")
    body = raw.get("body_text")
    category = raw.get("category")

    return (
        f"Idea: {title}\n"
        f"Category: {category}\n\n"
        f"Post body:\n{body}\n"
    )


def run_judge() -> None:
    with open("config/judge_rubric.yaml") as f:
        rubric = yaml.safe_load(f)

    # Find ideas that have passed review but haven't been judged yet.
    judged = (
        supabase.table("judged_ideas").select("analyzed_idea_id").execute().data
    )
    judged_ids = [item["analyzed_idea_id"] for item in judged if item.get("analyzed_idea_id")]

    query = (
        supabase.table("analyzed_ideas")
        .select("*, raw_ideas(post_title, body_text, category)")
        .eq("reviewer_pass", True)
    )

    if judged_ids:
        # Use the Supabase query builder's `not_` branch to apply a NOT IN filter.
        # The `in_` method accepts a list of values.
        query = query.not_.in_("id", judged_ids)

    approved = query.execute().data

    prompt = _build_judge_prompt(rubric)

    for record in approved:
        response = call_agent(
            "judge",
            prompt,
            _format_idea_for_judge(record),
            schema=JUDGE_SCHEMA,
            effort="high",
        )

        # structured output comes back as a text block
        text = None
        if hasattr(response, "content") and isinstance(response.content, list):
            text = response.content[0].text
        else:
            text = str(response)

        score = json.loads(text)
        score["analyzed_idea_id"] = record["id"]

        supabase.table("judged_ideas").insert(score).execute()
