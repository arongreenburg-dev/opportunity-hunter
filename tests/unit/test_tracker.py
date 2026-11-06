"""Workflow, persistence and API tests for the decision tracker.

These run without cloud credentials using the local JSON store.
"""

import socket
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import recheck, sources, tracker_store
from app.tracker import Tracker, TrackerError
from app.tracker_store import LocalJsonStore

DEMO = Path(__file__).resolve().parents[2] / "data" / "demo"
TODAY = date(2026, 11, 6)


@pytest.fixture
def store(tmp_path):
    return LocalJsonStore(tmp_path / "state.json")


@pytest.fixture
def t(store):
    return Tracker(store, today=TODAY)


def by_title(state, title):
    return next(o for o in state["opportunities"] if o["title"].startswith(title))


def test_demo_end_to_end(t, store):
    state = t.load_demo()
    assert len(state["opportunities"]) == 3
    assert state["queue"] == []
    for o in state["opportunities"]:
        assert o["is_demo"] and o["last_check"]["verdict"] == recheck.VERDICT_BASELINE
        assert o["evidence"]["fields"]

    t.publish_demo_v2()
    t.check_all()
    state = t.state()

    northstar = by_title(state, "Northstar")
    civic = by_title(state, "Civic")
    climate = by_title(state, "Open Climate")

    # One change reopens a prior decision.
    assert northstar["review"]["verdict"] == recheck.VERDICT_RECONSIDER
    assert northstar["decision"]["value"] == "pass"  # not changed until confirmed
    # One cosmetic edit stays quiet.
    assert civic["last_check"]["verdict"] == recheck.VERDICT_QUIET
    assert not civic.get("review")
    # One source failure preserves the last verified state.
    assert climate["review"]["verdict"] == recheck.VERDICT_UNVERIFIED
    assert climate["decision"]["value"] == "pursue"
    assert climate["evidence"]["check_id"] != climate["last_check"]["id"]
    assert "April 30, 2027" in climate["evidence"]["fields"]["deadline"]["text"]

    assert state["queue"] == [northstar["id"], climate["id"]]  # Reconsider first
    assert state["demo"]["checked_since_publish"]

    # Persisted: a fresh store on the same file sees the same state.
    reread = Tracker(LocalJsonStore(store.path), today=TODAY).state()
    assert reread["queue"] == state["queue"]

    # Confirm the decision change.
    t.resolve_review(northstar["id"], "change", "pursue")
    state = t.state()
    northstar = by_title(state, "Northstar")
    assert northstar["decision"]["value"] == "pursue"
    assert northstar["decision"]["via"] == "review"
    assert [d["value"] for d in northstar["decision_history"]] == ["pass", "pursue"]
    assert state["queue"] == [climate["id"]]

    # History holds both checks, newest first.
    checks = t.history(northstar["id"])["checks"]
    assert [c["verdict"] for c in checks] == ["reconsider", "baseline"]


def test_failed_check_does_not_replace_open_reconsider(t):
    t.load_demo()
    t.publish_demo_v2()
    t.check_all()
    northstar = by_title(t.state(), "Northstar")
    t.store.set_meta("demo_version", 99)  # unknown version -> falls back to v1 page
    # A later failure must not bury the Reconsider item.
    record = t.store.get_opportunity(northstar["id"])
    record["source_url"] = "/hunter/demo/listings/does-not-exist"
    t.store.put_opportunity(record)
    after = t.check(northstar["id"])
    assert after["last_check"]["verdict"] == recheck.VERDICT_UNVERIFIED
    assert after["review"]["verdict"] == recheck.VERDICT_RECONSIDER


def test_keep_decision_resolves_review(t):
    t.load_demo()
    t.publish_demo_v2()
    t.check_all()
    climate = by_title(t.state(), "Open Climate")
    t.resolve_review(climate["id"], "keep")
    after = t.state()
    assert climate["id"] not in after["queue"]
    assert by_title(after, "Open Climate")["decision"]["value"] == "pursue"


def test_validation(t):
    with pytest.raises(TrackerError):
        t.track(title="", decision="watch", reason="x")
    with pytest.raises(TrackerError):
        t.track(title="X", decision="maybe", reason="x")
    with pytest.raises(TrackerError):
        t.track(title="X", decision="watch", reason="  ")


def test_track_without_url_saves_decision_only(t):
    o = t.track(title="Board seat", decision="watch", reason="Need intro first")
    assert o["last_check"] is None and o["decision"]["value"] == "watch"


class _Pages(BaseHTTPRequestHandler):
    pages: ClassVar[dict] = {}
    redirects: ClassVar[dict] = {}

    def do_GET(self):
        _Pages.last_host = self.headers.get("Host")
        if self.path in self.redirects:
            self.send_response(302)
            self.send_header("Location", self.redirects[self.path])
            self.end_headers()
            return
        status, body = self.pages.get(self.path, (404, "not found"))
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def http_source(monkeypatch):
    """A real HTTP server whose pages can change between checks."""
    for var in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OH_ALLOW_PRIVATE_SOURCES", "1")  # loopback test server
    server = HTTPServer(("127.0.0.1", 0), _Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", _Pages.pages
    server.shutdown()


def test_live_http_path_uses_same_logic(t, http_source):
    base, pages = http_source
    pages["/rules"] = (200, (DEMO / "northstar.v1.html").read_text())
    o = t.track(
        title="Northstar Health AI Challenge",
        source_url=base + "/rules",
        decision="pass",
        reason="Requires in-person travel to Boston.",
    )
    assert o["last_check"]["verdict"] == recheck.VERDICT_BASELINE

    pages["/rules"] = (200, (DEMO / "northstar.v2.html").read_text())
    o = t.check(o["id"])
    assert o["review"]["verdict"] == recheck.VERDICT_RECONSIDER

    verified = o["evidence"]
    pages["/rules"] = (500, "boom")
    o = t.check(o["id"])
    assert o["last_check"]["verdict"] == recheck.VERDICT_UNVERIFIED
    assert "HTTP 500" in o["last_check"]["error"]
    assert o["evidence"] == verified  # last verified evidence preserved
    assert o["review"]["verdict"] == recheck.VERDICT_RECONSIDER  # not buried


def test_api_routes(tmp_path, monkeypatch):
    from app.tracker_api import router

    monkeypatch.setenv("OH_STORAGE", "local")
    monkeypatch.setenv("OH_LOCAL_STORE", str(tmp_path / "api.json"))
    tracker_store.get_store.cache_clear()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    try:
        assert client.get("/hunter/api/state").json()["opportunities"] == []
        client.post("/hunter/api/demo/load")
        assert client.get("/hunter/demo/listings/openclimate").status_code == 200
        client.post("/hunter/api/demo/publish-v2")
        assert client.get("/hunter/demo/listings/openclimate").status_code == 503
        state = client.post("/hunter/api/check-all").json()
        assert len(state["queue"]) == 2
        bad = client.post(
            "/hunter/api/opportunities", json={"title": "x", "reason": ""}
        )
        assert bad.status_code == 400 and "reason" in bad.json()["detail"]
        first = state["queue"][0]
        r = client.post(
            f"/hunter/api/opportunities/{first}/review",
            json={"action": "change", "decision": "pursue"},
        )
        assert r.json()["decision"]["value"] == "pursue"
        assert client.delete("/hunter/api/demo").json()["opportunities"] == []
    finally:
        tracker_store.get_store.cache_clear()


# --- Review findings: SSRF, concurrent edits, accumulated changes ---------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/admin",
        "http://169.254.169.254/computeMetadata/v1/",
        "http://10.0.0.5/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://localhost/",
        "http://metadata.google.internal/",
        "ftp://example.com/rules",
    ],
)
def test_non_public_sources_are_rejected(t, url, monkeypatch):
    monkeypatch.delenv("OH_ALLOW_PRIVATE_SOURCES", raising=False)
    with pytest.raises(TrackerError, match="public"):
        t.track(title="X", source_url=url, decision="watch", reason="r")
    with pytest.raises(sources.SourceError):
        sources.fetch(url)


def test_redirect_to_private_address_is_blocked(http_source, monkeypatch):
    base, _pages = http_source
    monkeypatch.delenv("OH_ALLOW_PRIVATE_SOURCES", raising=False)
    real_check = sources.check_public_url

    def allow_loopback_server(url):
        if url.startswith(base):
            return
        real_check(url)

    monkeypatch.setattr(sources, "check_public_url", allow_loopback_server)
    _Pages.redirects = {"/hop": "http://169.254.169.254/latest/meta-data/"}
    try:
        with pytest.raises(sources.SourceError, match="public"):
            sources.fetch(base + "/hop")
    finally:
        _Pages.redirects = {}


def test_check_does_not_overwrite_decision_edited_during_fetch(t, monkeypatch):
    o = t.track(title="Board seat", decision="pursue", reason="Fits", check_now=False)
    record = t.store.get_opportunity(o["id"])
    record["source_url"] = "https://example.org/rules"
    t.store.put_opportunity(record)
    page = (DEMO / "civic.v1.html").read_text()

    def slow_fetch(url, **kwargs):
        # The user changes their mind while the page is being fetched.
        t.set_decision(o["id"], "pass", "No longer interested")
        return sources.FetchResult(url, 200, page)

    monkeypatch.setattr(sources, "fetch", slow_fetch)
    after = t.check(o["id"])
    assert after["decision"]["value"] == "pass"
    assert [d["value"] for d in after["decision_history"]] == ["pursue", "pass"]
    assert after["last_check"]["outcome"] == "verified"
    assert t.store.get_opportunity(o["id"])["decision"]["value"] == "pass"


def test_unreviewed_changes_accumulate_across_checks(t, monkeypatch):
    def page(eligibility, deadline):
        return (
            "<title>Fellowship</title><h2>Key Dates</h2><p>Applications close "
            f"{deadline}.</p><h2>Eligibility</h2><p>{eligibility}</p>"
        )

    current = {"html": page("Open to US residents.", "March 1, 2027")}
    monkeypatch.setattr(
        sources,
        "fetch",
        lambda url, **k: sources.FetchResult(url, 200, current["html"]),
    )
    o = t.track(
        title="Fellowship",
        source_url="https://example.org/f",
        decision="watch",
        reason="Waiting on stipend",
    )
    current["html"] = page("Open to residents of Canada.", "March 1, 2027")
    t.check(o["id"])
    current["html"] = page("Open to residents of Canada.", "March 20, 2027")
    review = t.check(o["id"])["review"]
    assert review["open"]
    fields = {c["field"]: c for c in review["changes"]}
    assert set(fields) == {"deadline", "eligibility"}
    # "before" is the wording from when the review opened.
    assert "US residents" in fields["eligibility"]["before"]
    assert "March 1, 2027" in fields["deadline"]["before"]
    assert len(review["check_ids"]) == 1  # second check folded in

    # A field that reverts drops out of the pending review.
    current["html"] = page("Open to US residents.", "March 20, 2027")
    review = t.check(o["id"])["review"]
    assert {c["field"] for c in review["changes"]} == {"deadline"}


def test_fetch_connects_to_the_validated_address(http_source, monkeypatch):
    """DNS is resolved once; the connection uses that IP, not a fresh lookup."""
    base, pages = http_source
    port = base.rsplit(":", 1)[1]
    pages["/rules"] = (
        200,
        "<title>Rules</title><p>Applications close May 1, 2027.</p>",
    )
    real = socket.getaddrinfo
    lookups = []

    def resolver(host, *args, **kwargs):
        if host == "rules.example":
            lookups.append(host)
            return real("127.0.0.1", *args, **kwargs)
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    # "rules.example" does not exist in real DNS, so this only succeeds if the
    # client connects to the pinned IP rather than resolving the name again.
    result = sources.fetch(f"http://rules.example:{port}/rules")
    assert "May 1, 2027" in result.html
    assert result.url == f"http://rules.example:{port}/rules"
    assert lookups == ["rules.example"]
    assert _Pages.last_host == f"rules.example:{port}"


def test_https_pinning_keeps_hostname_for_tls(monkeypatch):
    monkeypatch.setattr(sources, "check_public_url", lambda url: "93.184.215.14")
    seen = {}

    def handler(request):
        seen.update(
            host=request.url.host,
            header=request.headers["host"],
            sni=request.extensions.get("sni_hostname"),
        )
        return httpx.Response(200, html="<p>ok</p>")

    sources.fetch("https://rules.example.org/x", transport=httpx.MockTransport(handler))
    assert seen == {
        "host": "93.184.215.14",
        "header": "rules.example.org",
        "sni": "rules.example.org",
    }
