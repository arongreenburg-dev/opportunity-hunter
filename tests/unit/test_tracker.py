"""Workflow, persistence and API tests for the decision tracker.

These run without cloud credentials using the local JSON store.
"""

import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import recheck, tracker_store
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

    def do_GET(self):
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
