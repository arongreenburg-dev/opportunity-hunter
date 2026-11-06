"""Retrieve official-source pages for rechecks.

Live URLs are fetched over HTTP. Demo URLs (``/hunter/demo/listings/<slug>``)
resolve to local fixture files so the demo works offline, but the returned
HTML then goes through exactly the same extraction and comparison pipeline.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"
DEMO_PREFIX = "/hunter/demo/listings/"
USER_AGENT = "OpportunityHunter/0.2 (official-source recheck)"
MAX_BYTES = 3_000_000
MAX_REDIRECTS = 5
_INTERNAL_SUFFIXES = (".internal", ".local", ".localhost", ".lan", ".home.arpa")


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


def _proxy_configured(scheme: str) -> bool:
    names = (f"{scheme}_proxy", f"{scheme.upper()}_PROXY", "all_proxy", "ALL_PROXY")
    return any(os.getenv(n) for n in names)


def check_public_url(url: str) -> None:
    """Reject URLs that would make the server reach a non-public destination.

    Source URLs are user-supplied, so without this the recheck would be a
    server-side request forgery primitive (loopback, private networks, cloud
    metadata). Every address a hostname resolves to must be globally routable.
    Set OH_ALLOW_PRIVATE_SOURCES=1 only for local testing.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SourceError("Only public http(s) web pages can be checked.")
    if os.getenv("OH_ALLOW_PRIVATE_SOURCES") == "1":
        return
    host = parts.hostname.rstrip(".").lower()
    blocked = SourceError("Only public web addresses can be checked.")
    if host in ("localhost", "metadata", "metadata.google.internal") or host.endswith(
        _INTERNAL_SUFFIXES
    ):
        raise blocked
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    else:
        try:
            infos = socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
        except (socket.gaierror, UnicodeError) as exc:
            # Behind an explicit egress proxy the proxy resolves names and
            # enforces its own network policy; otherwise unresolvable is a
            # failure.
            if _proxy_configured(parts.scheme):
                return
            raise SourceError("The official page's host could not be found.") from exc
        addresses = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    for ip in addresses:
        mapped = getattr(ip, "ipv4_mapped", None)
        if not ip.is_global or (mapped is not None and not mapped.is_global):
            raise blocked


def fetch(url: str, *, demo_version: int = 1, timeout: float = 15.0) -> FetchResult:
    """Fetch an official source page. Raises SourceError on any failure."""
    if is_demo_url(url):
        return demo_page(url[len(DEMO_PREFIX) :].strip("/"), demo_version)

    if not url or not url.lower().startswith(("http://", "https://")):
        raise SourceError("No official source URL is saved for this opportunity.")

    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            },
        ) as client:
            # Follow redirects by hand so every hop is validated.
            for _hop in range(MAX_REDIRECTS + 1):
                check_public_url(url)
                response = client.get(url)
                if not response.is_redirect:
                    break
                url = urljoin(url, response.headers.get("location", ""))
            else:
                raise SourceError("The official page redirected too many times.")
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
