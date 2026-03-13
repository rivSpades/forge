"""Daily digest generator and sender."""

from datetime import datetime, timezone
from typing import List, Dict

import resend

from utils.env import settings
from utils.supabase_client import supabase


resend.api_key = settings.RESEND_API_KEY


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def fetch_todays_go_ideas() -> List[Dict]:
    """Fetch today's GO ideas plus their related raw/analyzed records."""
    today = today_str()
    # Use judged_at to filter today’s decisions (judged_ideas does not have created_at).
    return (
        supabase.table("judged_ideas")
        .select("*, analyzed_ideas(*, raw_ideas(*))")
        .eq("verdict", "GO")
        .gte("judged_at", f"{today}T00:00:00Z")
        .lt("judged_at", f"{today}T23:59:59Z")
        .execute()
        .data
    )


def _format_confidence_badge(confidence: str) -> str:
    color = "green" if confidence == "HIGH" else "orange" if confidence == "MEDIUM" else "gray"
    return f"<span style=\"color:{color};font-weight:bold\">{confidence}</span>"


def _format_idea_block(record: Dict) -> str:
    # Supabase may return related records as a dict or a single-item list.
    analyzed = record.get("analyzed_ideas")
    if isinstance(analyzed, list):
        analyzed = analyzed[0] if analyzed else {}
    elif analyzed is None:
        analyzed = {}

    raw = analyzed.get("raw_ideas") or {}
    # If raw_ideas is a list (some joins return lists), take the first item.
    if isinstance(raw, list):
        raw = raw[0] if raw else {}

    report = analyzed.get("report") or {}

    title = raw.get("post_title", "(no title)")
    url = raw.get("source_url", "#")
    forum = raw.get("forum_name", "")
    date = raw.get("created_at", "")
    score = record.get("weighted_total", "")
    confidence = _format_confidence_badge(record.get("confidence", ""))
    reasoning = report.get("assessment", "")
    risks = report.get("risks", [])[:3]

    req_plan_link = ""
    if settings.CEO_EMAIL:
        req_plan_link = (
            f"mailto:{settings.CEO_EMAIL}?subject=PLAN+REQUEST+{record.get('id')}"
            f"&body=I+want+a+full+plan+for+idea+{record.get('id')}"
        )

    risks_html = "".join(f"<li>{r}</li>" for r in risks)

    return f"""
    <div style=\"border:1px solid #ddd;padding:12px;margin:12px 0;\">
      <h2><a href=\"{url}\" target=\"_blank\">{title}</a></h2>
      <div><strong>Forum:</strong> {forum} • <strong>Date:</strong> {date}</div>
      <div><strong>Confidence:</strong> {confidence} • <strong>Score:</strong> {score}</div>
      <p><strong>Reasoning:</strong><br/>{reasoning}</p>
      <p><strong>Top Risks:</strong></p>
      <ul>{risks_html}</ul>
      <p><a href=\"{req_plan_link}\">Request Full Plan</a></p>
    </div>
    """


def build_digest_html(ideas: List[Dict]) -> str:
    go_blocks = []
    escalated_blocks = []

    for record in ideas:
        if record.get("verdict") == "GO":
            go_blocks.append(_format_idea_block(record))
        else:
            escalated_blocks.append(_format_idea_block(record))

    html = """
    <html><body>
      <h1>FORGE Daily Digest</h1>
      <p>Generated: {}</p>
      <h2>GO Ideas</h2>
      {}
      <h2>Flagged for Manual Review</h2>
      {}
    </body></html>
    """.format(today_str(), "".join(go_blocks), "".join(escalated_blocks))

    return html


def _save_digest_html(html: str) -> str:
    """Save digest HTML to logs and return the path."""
    import os

    os.makedirs("logs", exist_ok=True)
    filename = f"logs/digest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    return filename


def send_digest() -> None:
    ideas = fetch_todays_go_ideas()
    if not ideas:
        return

    html = build_digest_html(ideas)

    if not settings.RESEND_API_KEY:
        path = _save_digest_html(html)
        print(f"[digest] RESEND_API_KEY not configured; saved digest to {path}")
        return

    try:
        resend.Emails.send(
            {
                "from": "FORGE Digest <digest@yourdomain.com>",
                "to": [settings.CEO_EMAIL] if settings.CEO_EMAIL else [],
                "subject": f"FORGE Daily Digest — {len(ideas)} GO ideas — {today_str()}",
                "html": html,
            }
        )
    except Exception as e:
        path = _save_digest_html(html)
        print(f"[digest] failed to send email: {e}; saved digest to {path}")
