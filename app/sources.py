"""Retrieve official-source pages for rechecks.

Live URLs are fetched over HTTP. Demo URLs (``/hunter/demo/listings/<slug>``)
resolve to local fixture files so the demo works offline, but the returned
HTML then goes through exactly the same extraction and comparison pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import httpx

DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"
DEMO_PREFIX = "/hunter/demo/listings/"
USER_AGENT = "OpportunityHunter/0.2 (official-source recheck)"
MAX_BYTES = 3_000_000


class SourceError(Exception):
    """Retrieval failed; message is user-facing."""


@dataclass
class FetchResult:
    url: str
    status: int
    html: str


@cache
def demo_manifest() -> dict:
    return json.loads((DEMO_DIR / "listings.json").read_text())


def demo_listing(slug: str) -> dict | None:
    return next((x for x in demo_manifest()["listings"] if x["slug"] == slug), None)


def demo_page(slug: str, version: int) -> FetchResult:
    listing = demo_listing(slug)
    if not listing:
        raise SourceError("Demo listing not found (HTTP 404).")
    spec = listing["versions"].get(str(version)) or listing["versions"]["1"]
    url = DEMO_PREFIX + slug
    if "http_status" in spec:
        raise SourceError(
            f"The official page returned HTTP {spec['http_status']} (service unavailable)."
        )
    return FetchResult(url, 200, (DEMO_DIR / spec["file"]).read_text())


def is_demo_url(url: str) -> bool:
    return (url or "").startswith(DEMO_PREFIX)


def fetch(url: str, *, demo_version: int = 1, timeout: float = 15.0) -> FetchResult:
    """Fetch an official source page. Raises SourceError on any failure."""
    if is_demo_url(url):
        return demo_page(url[len(DEMO_PREFIX) :].strip("/"), demo_version)

    if not url or not url.lower().startswith(("http://", "https://")):
        raise SourceError("No official source URL is saved for this opportunity.")

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            },
        ) as client:
            response = client.get(url)
    except httpx.TimeoutException as exc:
        raise SourceError("The official page timed out.") from exc
    except httpx.HTTPError as exc:
        raise SourceError(
            f"The official page could not be reached ({type(exc).__name__})."
        ) from exc

    if response.status_code >= 400:
        raise SourceError(f"The official page returned HTTP {response.status_code}.")
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        raise SourceError(
            f"The source is not a web page ({content_type or 'unknown type'})."
        )
    if len(response.content) > MAX_BYTES:
        raise SourceError("The official page is too large to check.")
    return FetchResult(str(response.url), response.status_code, response.text)
