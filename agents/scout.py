"""Scout agent that discovers and classifies forum threads.

The Scout fetches thread lists from configured forums, deduplicates against
Supabase, classifies each thread via Claude, and inserts selected ideas into
`raw_ideas`.
"""

import json
import logging
import os
from typing import Any, Dict, List
from urllib.parse import urljoin

import yaml

from utils.claude_client import call_agent
from utils.supabase_client import supabase
from utils.firecrawl_client import scrape_url, fetch_reddit_json


# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/scout.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


with open("config/forums.yaml") as f:
    CONFIG = yaml.safe_load(f)


CATEGORIZATION_PROMPT = """
You are a forum intelligence specialist. Given a post title and body,
assign ONE category from this list: SaaS, Tool/App, Content, Marketplace,
Affiliate, Service, Community, Other.

The most important goal is to determine whether this is a *guide* (someone
explaining how to do something, with steps/details) versus a *question*
(seeking help or information). If the post primarily reads like a question
(e.g., “how do I…”, “anyone know…”, “what is…”, lots of question marks), set
keep=false. If it is clearly a guide/tutorial/explanation (e.g., “here’s how to”,
“step 1:”, “you can do this by…”), set keep=true.

Also rate quality 1-5: does this post contain specific results, dollar figures,
named tools, or first-person implementation details?

Return JSON: {category: string, quality_score: integer, keep: boolean}
"""

CATEGORIZATION_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string"},
        "quality_score": {"type": "integer", "minimum": 1, "maximum": 5},
        "keep": {"type": "boolean"},
    },
    "required": ["category", "quality_score", "keep"],
}


def _parse_threads_from_html(html: str, base_url: str) -> List[Dict[str, Any]]:
    """Parse thread links from HTML.

    For BlackHatWorld (and similar forum list pages) the correct links are those in
    `<div class="structItem-title"><a ...>Title</a></div>`.

    Additionally, extract the thread view count so we can filter threads by popularity.
    """

    def _parse_view_count(value: str) -> int | None:
        """Convert a views label like '2K' or '3,200' into an integer."""

        if not value:
            return None
        value = value.strip().upper().replace(",", "")
        try:
            if value.endswith("K"):
                return int(float(value[:-1]) * 1_000)
            if value.endswith("M"):
                return int(float(value[:-1]) * 1_000_000)
            return int(value)
        except Exception:
            return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # If BeautifulSoup isn't installed, fall back to a very loose parser.
        threads: List[Dict[str, Any]] = []
        for part in html.split("<a "):
            if "href=" not in part:
                continue
            try:
                href = part.split("href=")[1].split("\"")[1]
                title = part.split(">", 1)[1].split("<")[0].strip()
            except Exception:
                continue
            if not href or not title:
                continue
            if href.startswith("/"):
                href = base_url.rstrip("/") + href
            if href.startswith("http"):
                threads.append({"url": href, "title": title, "body": "", "views": None})
        return threads

    soup = BeautifulSoup(html, "html.parser")
    threads: List[Dict[str, Any]] = []

    # Each thread is represented by a structItem container.
    for item in soup.select(".structItem"):
        # Skip pinned/sticky highlighted threads
        if item.select_one(".sticky-thread--hightlighted"):
            continue

        link = item.select_one(".structItem-title a")
        if not link:
            continue

        href = link.get("href")
        title = link.get_text(strip=True)
        if not href or not title:
            continue
        # Normalize relative URLs to absolute using the page's base URL.
        if href.startswith("/") or not href.startswith("http"):
            href = urljoin(base_url, href)
        if not href.startswith("http"):
            continue

        # Extract views (e.g. "2K") if present.
        view_count = None
        meta = item.select_one(".structItem-cell--meta")
        if meta:
            # Look for the <dt>Views</dt> / <dd>..</dd> pair.
            for dl in meta.select("dl"):
                dt = dl.select_one("dt")
                dd = dl.select_one("dd")
                if dt and dd and dt.get_text(strip=True).lower() == "views":
                    view_count = _parse_view_count(dd.get_text(strip=True))
                    break

        threads.append({
            "url": href,
            "title": title,
            "body": "",
            "views": view_count,
        })

    return threads


def _fetch_thread_body(url: str) -> str:
    """Fetch the first post body text for a thread page.

    Uses BeautifulSoup to extract the first message body; returns an empty string on
    failure.
    """

    try:
        html = scrape_url(url)
    except Exception as e:
        logging.warning(f"Failed to fetch thread body for {url}: {e}")
        return ""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    msg = soup.select_one("article.message")
    if not msg:
        return ""

    content = msg.select_one(".bbWrapper")
    if not content:
        return ""

    return content.get_text(separator="\n", strip=True)


def fetch_threads(forum: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch thread list for a given forum configuration."""

    forum_type = forum.get("type")
    base_url = forum.get("url")

    if forum_type == "reddit_json":
        data = fetch_reddit_json(base_url)
        threads: List[Dict[str, Any]] = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            threads.append(
                {
                    "url": "https://www.reddit.com" + post.get("permalink", ""),
                    "title": post.get("title", ""),
                    "body": post.get("selftext", ""),
                    "upvotes": post.get("ups", 0),
                }
            )
        return threads

    # Default: treat as a generic thread list page
    pages = forum.get("pages", 1)
    if pages < 1:
        pages = 1

    threads: List[Dict[str, Any]] = []
    for page in range(1, pages + 1):
        url = base_url if page == 1 else f"{base_url.rstrip('/')}/page-{page}"
        html = scrape_url(url)
        threads.extend(_parse_threads_from_html(html, base_url))

    return threads


def run_scout() -> None:
    for forum in CONFIG.get("forums", []):
        if not forum.get("active"):
            continue

        logging.info(f"Starting forum: {forum.get('name')} ({forum.get('url')})")
        print(f"[scout] starting forum: {forum.get('name')}")

        threads = fetch_threads(forum)
        logging.info(f"Fetched {len(threads)} threads from {forum.get('name')}")
        print(f"[scout] fetched {len(threads)} threads")

        new_count = 0

        for i, thread in enumerate(threads, start=1):
            logging.info(f"Processing thread {i}/{len(threads)}: {thread.get('url')}")
            print(f"[scout] thread {i}/{len(threads)}: {thread.get('url')}")

            # Prefer high-engagement threads: only process threads with >= 2K views.
            # If the scraper failed to extract views, we treat it as a low-engagement thread.
            views = thread.get("views")
            if (views is None) or (views < 2000):
                logging.info(f"Skipped - low/unknown views ({views})")
                continue

            existing = (
                supabase.table("raw_ideas")
                .select("id")
                .eq("source_url", thread["url"])
                .execute()
            )
            if existing.data:
                logging.info("Skipped - already exists")
                continue

            # Fetch the first post body to give the classifier more context.
            thread["body"] = _fetch_thread_body(thread["url"])

            # Quick heuristic to filter out question-style threads (no need to call the LLM)
            body_lower = thread["body"].lower()
            question_triggers = [
                "how do i",
                "how can i",
                "anyone know",
                "does anyone",
                "what is",
                "where can i",
                "help me",
                "can anyone",
            ]
            is_question = (
                thread["body"].count("?") >= 2
                or any(trigger in body_lower for trigger in question_triggers)
            )
            if is_question:
                logging.info("Skipped - looks like a question (not a guide)")
                continue

            try:
                result_json = call_agent(
                    "scout",
                    CATEGORIZATION_PROMPT,
                    f"Title: {thread['title']}\nBody: {thread['body'][:500]}",
                    schema=CATEGORIZATION_SCHEMA,
                )
            except Exception as e:
                logging.error(f"Error calling agent for thread {thread.get('url')}: {e}")
                continue

            # Support either structured output or raw text (defensive)
            text = None
            if hasattr(result_json, "content") and isinstance(result_json.content, list):
                text = result_json.content[0].text
            elif isinstance(result_json, dict) and "content" in result_json:
                text = result_json["content"]
            else:
                text = str(result_json)

            sanitized = text[:300].replace("\n", " ")
            logging.info(f"Agent output (first 300 chars): {sanitized}")

            try:
                result = json.loads(text)
            except Exception as e:
                logging.warning(f"Failed to parse JSON from agent output: {e}\n{text}")
                continue

            logging.info(
                f"Classification: keep={result.get('keep')} quality_score={result.get('quality_score')} category={result.get('category')}"
            )

            # Keep any thread that the classifier explicitly marks as a guide.
            # Quality score can be used for sorting later, but we do not reject
            # purely on quality because guide-style posts are what we want.
            if result.get("keep"):
                supabase.table("raw_ideas").insert(
                    {
                        "source_url": thread["url"],
                        "post_title": thread["title"],
                        "body_text": thread.get("body", ""),
                        "upvotes": thread.get("upvotes", 0),
                        "forum_name": forum.get("name"),
                        "category": result.get("category"),
                    }
                ).execute()
                new_count += 1
            else:
                logging.info("Skipped - classifier decided not to keep this thread")

        logging.info(f"Finished forum {forum.get('name')}: {new_count} new ideas saved")
        print(f"[scout] {forum.get('name')} → {new_count} new ideas saved")
