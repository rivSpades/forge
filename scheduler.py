from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio
import logging, traceback

from agents.scout import run_scout
from agents.analyst import run_analyst
from agents.reviewer import run_reviewer
from agents.judge import run_judge
from agents.digest import send_digest
from agents.planner import run_planning_pipeline
from scripts.check_plan_requests import check_plan_requests
from utils.supabase_client import supabase

logging.basicConfig(
    filename="logs/scheduler.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def send_alert_email(subject: str, body: str) -> None:
    """Placeholder for alerting; implement email/Slack/etc. in Phase 2."""
    logging.error(f"ALERT: {subject} - {body}")


def run_with_logging(agent_name, fn):
    try:
        logging.info(f"START {agent_name}")
        fn()
        logging.info(f"DONE  {agent_name}")
    except Exception as e:
        logging.error(f"FAIL  {agent_name}: {traceback.format_exc()}")
        send_alert_email(f"{agent_name} failed", str(e))


scheduler = BlockingScheduler(timezone="UTC")
scheduler.add_job(lambda: run_with_logging("scout", run_scout), CronTrigger(hour=7))
scheduler.add_job(lambda: run_with_logging("analyst", run_analyst), CronTrigger(hour=9))
scheduler.add_job(lambda: run_with_logging("reviewer", run_reviewer), CronTrigger(hour=11))
scheduler.add_job(lambda: run_with_logging("judge", run_judge), CronTrigger(hour=13))
scheduler.add_job(lambda: run_with_logging("digest", send_digest), CronTrigger(hour=15))


def _run_planning_for_pending_requests() -> None:
    """Process any judged ideas where the CEO has requested a full plan."""
    pending = supabase.table("judged_ideas").select("id").eq("plan_requested", True).execute().data
    for row in pending:
        idea_id = row.get("id")
        if not idea_id:
            continue
        try:
            asyncio.run(run_planning_pipeline(idea_id))
        except Exception as e:
            logging.error(f"FAIL planner for {idea_id}: {traceback.format_exc()}")


scheduler.add_job(lambda: run_with_logging("check_plan_requests", check_plan_requests), CronTrigger(minute=0))
scheduler.add_job(lambda: run_with_logging("planner", _run_planning_for_pending_requests), CronTrigger(minute=5))


if __name__ == "__main__":
    scheduler.start()
