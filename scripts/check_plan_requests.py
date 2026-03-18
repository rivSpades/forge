"""Scan the CEO inbox for "PLAN REQUEST" emails and mark the corresponding idea as requested.

This is intended to be run on an hourly schedule.
"""

import imaplib
import re
from email import message_from_bytes
from datetime import datetime, timezone

from utils.env import settings
from utils.supabase_client import supabase


def _get_email_body(msg) -> str:
    """Extract plain text body from email.Message."""
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                try:
                    parts.append(part.get_payload(decode=True).decode(errors="ignore"))
                except Exception:
                    continue
        return "\n".join(parts).strip()
    try:
        return msg.get_payload(decode=True).decode(errors="ignore").strip()
    except Exception:
        return ""


def _update_notion_status(notion_url: str | None, status: str) -> None:
    if not notion_url:
        return
    try:
        from utils.notion_client import update_status

        update_status(notion_url, status)
    except Exception as e:
        print(f"[plan request] Failed to update Notion status: {e}")


def _create_project_if_approved(idea_id: str, notion_url: str | None, title: str | None) -> None:
    """Create a projects row and trigger Phase 3 build (GitHub, Vercel, Railway) if configured."""
    product_name = (title or "").strip() or f"Product-{idea_id}"
    try:
        res = supabase.table("projects").insert(
            {
                "product_name": product_name[:255],
                "judged_idea_id": idea_id,
                "status": "approved",
            }
        ).execute()
        print(f"[plan request] Created project record for {idea_id}")
        if res.data and len(res.data) > 0:
            project_id = res.data[0].get("id")
            if project_id:
                try:
                    from scripts.phase3_build import run_build_for_project
                    out = run_build_for_project(project_id)
                    if out.get("ok"):
                        print(f"[plan request] Phase 3 build started for project {project_id}")
                    else:
                        print(f"[plan request] Phase 3 build skipped or failed: {out.get('error', '')}")
                except Exception as e:
                    print(f"[plan request] Phase 3 build error: {e}")
    except Exception as e:
        print(f"[plan request] Failed to create project record: {e}")


def check_plan_requests() -> None:
    """Mark judged ideas as requested when a PLAN REQUEST email is received.

    Also process decision email replies (APPROVE/REJECT/CHANGES).
    """

    if not settings.PLAN_EMAIL or not settings.PLAN_EMAIL_PASSWORD:
        print("[plan request] PLAN_EMAIL or PLAN_EMAIL_PASSWORD not configured; skipping")
        return

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(settings.PLAN_EMAIL, settings.PLAN_EMAIL_PASSWORD)
    mail.select("inbox")

    # Fetch unseen messages and handle both plan requests and decision replies.
    _, msgs = mail.search(None, "(UNSEEN)")
    for num in msgs[0].split():
        _, data = mail.fetch(num, "(RFC822)")
        msg = message_from_bytes(data[0][1])
        subject = (msg.get("Subject", "") or "").strip()

        plan_match = re.search(r"PLAN REQUEST\s*[-–—]\s*([\w-]+)", subject, re.IGNORECASE)
        decision_match = re.search(r"^(APPROVE|REJECT|CHANGES)\s*[-–—]\s*([\w-]+)", subject, re.IGNORECASE)

        if plan_match:
            idea_id = plan_match.group(1)
            supabase.table("judged_ideas").update(
                {
                    "plan_requested": True,
                    "plan_requested_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", idea_id).execute()
            print(f"[plan request] Marked plan_requested for {idea_id}")

        elif decision_match:
            action = decision_match.group(1).upper()
            idea_id = decision_match.group(2)
            body = _get_email_body(msg)

            # Determine status labels for Notion.
            status_map = {"APPROVE": "Approved", "REJECT": "Rejected", "CHANGES": "Changes Requested"}
            status = status_map.get(action, "Pending Decision")

            # Update judged idea row with decision metadata.
            update_data = {
                "decision": action,
                "decision_at": datetime.now(timezone.utc).isoformat(),
                "decision_notes": body,
            }
            # Fetch notion_url (if saved) for updates.
            try:
                record = (
                    supabase.table("judged_ideas")
                    .select("notion_url, analyzed_ideas(raw_ideas(post_title))")
                    .eq("id", idea_id)
                    .single()
                    .execute()
                )
                notion_url = None
                title = None
                if record.data:
                    notion_url = record.data.get("notion_url")
                    analyzed = record.data.get("analyzed_ideas") or {}
                    raw = analyzed.get("raw_ideas") or {}
                    title = raw.get("post_title")
            except Exception:
                notion_url = None
                title = None

            try:
                supabase.table("judged_ideas").update(update_data).eq("id", idea_id).execute()
                print(f"[plan request] Recorded decision {action} for {idea_id}")
            except Exception as e:
                print(f"[plan request] Failed to save decision for {idea_id}: {e}")

            _update_notion_status(notion_url, status)

            if action == "APPROVE":
                _create_project_if_approved(idea_id, notion_url, title)

        else:
            # Unrecognized subject format; keep it unseen for manual handling.
            print(f"[plan request] Skipping email with subject: {subject}")
            continue

        mail.store(num, "+FLAGS", "\\Seen")

    mail.close()
    mail.logout()
