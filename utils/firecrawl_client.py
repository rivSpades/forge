"""Helpers for fetching forum / thread content.

This module provides two entry points:
- scrape_url(url): fetches generic HTML pages (Firecrawl or similar).
- fetch_reddit_json(url): fetches Reddit JSON via the official API endpoint.
"""

import requests


def scrape_url(url: str, timeout: float = 15.0) -> str:
    """Fetch a URL and return the raw HTML text.

    Attempts a normal requests.get first. If blocked by Cloudflare or similar,
    falls back to cloudscraper (if installed).
    """

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ForgeScout/1.0; +https://example.com)"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception:
        # Try cloudscraper if available
        try:
            import cloudscraper

            scraper = cloudscraper.create_scraper()
            resp = scraper.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception:
            # Re-raise the original exception if we can't bypass.
            raise


def fetch_reddit_json(url: str, timeout: float = 15.0) -> dict:
    """Fetch Reddit JSON for a given endpoint (e.g., r/SideProject/top.json?t=day)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ForgeScout/1.0; +https://example.com)"
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
