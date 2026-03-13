"""Notion integration helpers."""

import json

from notion_client import Client

from utils.env import settings


notion = Client(auth=settings.NOTION_TOKEN)


def _extract_page_id(page_url: str) -> str | None:
    """Extract Notion page ID from a Notion page URL."""
    # Notion URLs end with a UUID with or without dashes.
    if not page_url:
        return None
    parts = page_url.rstrip("/").split("/")
    if not parts:
        return None
    candidate = parts[-1]
    # If it contains dashes, it's already the page ID.
    if "-" in candidate and len(candidate) >= 32:
        return candidate
    # Otherwise it may be in the last 32 chars.
    if len(candidate) >= 32:
        return candidate[-32:]
    return None


def build_notion_blocks(briefing: dict) -> list:
    """Convert the briefing object into Notion blocks.

    Each top-level key becomes a heading_2 + paragraph. Notion API expects rich_text, not text.
    """
    blocks = []
    for k, v in briefing.items():
        content = str(k)[:2000]
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": content}}]},
        })
        body = json.dumps(v, indent=2)[:2000]
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": body}}]},
        })
    return blocks


def _parse_number(value) -> float | None:
    """Parse a number from string (e.g. '$1,000' or '5000') or return float/None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").lstrip("$")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def push_briefing_to_notion(briefing: dict, judge_score: float) -> str | None:
    """Push a CEO briefing to Notion and return the page URL.

    Database must have these exact properties: Name (title), Status (select with option
    'Pending Decision'), Judge Score (number), Projected 30-Day MRR (number).
    """
    if not settings.NOTION_TOKEN or not settings.NOTION_DATABASE_ID:
        print("[notion] NOTION_TOKEN/NOTION_DATABASE_ID not configured; skipping Notion push")
        return None

    idea_summary = briefing.get("idea_summary")
    title = (idea_summary[:255] if isinstance(idea_summary, str) else (idea_summary or {}).get("title", "CEO Brief")) or "CEO Brief"
    projected_mrr = briefing.get("projected_mrr") or {}
    projected_30 = _parse_number(projected_mrr.get("day_30"))

    try:
        page = notion.pages.create(
            parent={"database_id": settings.NOTION_DATABASE_ID},
            properties={
                "Name": {"title": [{"text": {"content": title}}]},
                "Status": {"select": {"name": "Pending Decision"}},
                "Judge Score": {"number": judge_score},
                "Projected 30-Day MRR": {"number": projected_30},
            },
            children=build_notion_blocks(briefing),
        )
        url = page.get("url")
        if url:
            print(f"[notion] Page created: {url}")
        return url
    except Exception as e:
        print(f"[notion] push_briefing_to_notion failed: {e}")
        raise


def update_status(page_url: str, status: str) -> None:
    """Update the Status property of a Notion page."""
    page_id = _extract_page_id(page_url)
    if not page_id:
        print(f"[notion] could not parse page id from URL {page_url}")
        return

    notion.pages.update(
        page_id=page_id,
        properties={"Status": {"select": {"name": status}}},
    )
