"""Launch sequence: run on CEO one-click approval. Promotes Vercel, sets env, deploys Railway, publishes first post, updates status."""

from datetime import datetime, timezone

from utils.supabase_client import supabase


def fetch_project(project_id: str) -> dict | None:
    """Load full project row."""
    res = (
        supabase.table("projects")
        .select("*")
        .eq("id", project_id)
        .single()
        .execute()
    )
    return res.data if res.data else None


def fetch_project_credentials(project_id: str) -> dict:
    """Load project_credentials for this project. Returns dict credential_name -> decrypted value (or placeholder if no key)."""
    res = (
        supabase.table("project_credentials")
        .select("credential_name, encrypted_value")
        .eq("project_id", project_id)
        .execute()
    )
    creds = {}
    if not res.data:
        return creds
    key = getattr(__import__("utils.env", fromlist=["settings"]).settings, "CREDENTIAL_ENCRYPTION_KEY", None)
    if not key:
        for row in res.data:
            creds[row["credential_name"]] = "(encrypted; set CREDENTIAL_ENCRYPTION_KEY to decrypt)"
        return creds
    try:
        from cryptography.fernet import Fernet
        f = Fernet(key.encode() if isinstance(key, str) else key)
        for row in res.data:
            try:
                creds[row["credential_name"]] = f.decrypt(row["encrypted_value"].encode()).decode()
            except Exception:
                creds[row["credential_name"]] = "(decrypt failed)"
    except Exception:
        for row in res.data:
            creds[row["credential_name"]] = "(decrypt failed)"
    return creds


def generate_launch_post(project: dict) -> str:
    """First social post content (pre-written by Marketing agent). Prefer content_calendar, else placeholder."""
    project_id = project.get("id")
    if project_id:
        res = (
            supabase.table("content_calendar")
            .select("content")
            .eq("project_id", project_id)
            .eq("status", "generated")
            .order("scheduled_date", desc=False)
            .limit(1)
            .execute()
        )
        if res.data and res.data[0].get("content"):
            return res.data[0]["content"]
    product_name = project.get("product_name") or "Our product"
    return f"We just launched {product_name}. Check it out!"


def launch_product(project_id: str) -> dict:
    """Run full launch sequence. Returns {ok: bool, error?: str, steps: list}."""
    project = fetch_project(project_id)
    if not project:
        return {"ok": False, "error": "Project not found", "steps": []}

    steps = []
    product_name = (project.get("product_name") or "product").replace(" ", "-").lower()[:100]
    custom_domain = project.get("custom_domain")
    railway_service_id = project.get("railway_service_id") or project.get("vercel_project_id")  # optional

    try:
        # 1. Promote Vercel preview to production
        try:
            from utils.vercel_client import promote_to_production
            promote_to_production(product_name, custom_domain)
            steps.append("vercel_promote")
        except Exception as e:
            steps.append(f"vercel_promote: {e}")
            logger = __import__("logging").getLogger(__name__)
            logger.warning("Vercel promote skipped or failed: %s", e)

        # 2. Set environment variables in Vercel production
        creds = fetch_project_credentials(project_id)
        if creds:
            try:
                from utils.vercel_client import set_env_vars
                set_env_vars(product_name, creds)
                steps.append("vercel_env")
            except Exception as e:
                steps.append(f"vercel_env: {e}")

        # 3. Deploy backend to Railway production
        if railway_service_id:
            try:
                from utils.railway_client import deploy_to_production
                deploy_to_production(railway_service_id)
                steps.append("railway_deploy")
            except Exception as e:
                steps.append(f"railway_deploy: {e}")

        # 4. Publish first social post via Buffer
        try:
            from utils.buffer_client import publish_immediately
            ch_res = supabase.table("social_channels").select("buffer_channel_id").eq("project_id", project_id).execute()
            channel_ids = [r["buffer_channel_id"] for r in (ch_res.data or []) if r.get("buffer_channel_id")]
            if channel_ids:
                first_post = generate_launch_post(project)
                publish_immediately(channel_ids, first_post)
                steps.append("buffer_publish")
            else:
                steps.append("buffer_publish: no channels")
        except Exception as e:
            steps.append(f"buffer_publish: {e}")

        # 5. Update project status
        supabase.table("projects").update({
            "status": "active_growth",
            "launched_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", project_id).execute()
        steps.append("status_updated")

        # 6. Send CEO confirmation
        try:
            send_launch_confirmation_email(project)
            steps.append("confirmation_email")
        except Exception as e:
            steps.append(f"confirmation_email: {e}")

        return {"ok": True, "steps": steps}
    except Exception as e:
        steps.append(str(e))
        return {"ok": False, "error": str(e), "steps": steps}


def send_launch_confirmation_email(project: dict) -> None:
    """Send CEO confirmation that the product is live."""
    from utils.env import settings
    if not settings.RESEND_API_KEY or not settings.CEO_EMAIL:
        return
    import resend
    resend.api_key = settings.RESEND_API_KEY
    product_name = project.get("product_name") or "Product"
    vercel_url = project.get("vercel_url") or "(see dashboard)"
    resend.Emails.send({
        "from": "FORGE Launch <launch@yourdomain.com>",
        "to": [settings.CEO_EMAIL],
        "subject": f"FORGE — {product_name} is live",
        "html": f"<h1>Launch complete</h1><p><strong>{product_name}</strong> is now live.</p><p>URL: {vercel_url}</p><p>Status set to active_growth.</p>",
    })
