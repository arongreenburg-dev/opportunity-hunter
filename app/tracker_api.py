"""HTTP routes for decisions, source rechecks, the review queue and the demo."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import sources
from app.tracker import Tracker, TrackerError
from app.tracker_store import get_store

router = APIRouter(include_in_schema=False)


def tracker() -> Tracker:
    return Tracker(get_store())


class TrackBody(BaseModel):
    title: str
    organization: str = ""
    source_url: str = ""
    decision: str = "watch"
    reason: str = ""
    evidence_note: str = ""


class DecisionBody(BaseModel):
    decision: str
    reason: str


class ResolveBody(BaseModel):
    action: str
    decision: str | None = None
    note: str = ""


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except TrackerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/hunter/api/state")
def get_state() -> dict:
    return tracker().state()


@router.post("/hunter/api/opportunities")
def track_opportunity(body: TrackBody) -> dict:
    return _run(tracker().track, **body.model_dump())


@router.post("/hunter/api/opportunities/{opp_id}/decision")
def update_decision(opp_id: str, body: DecisionBody) -> dict:
    return _run(tracker().set_decision, opp_id, body.decision, body.reason)


@router.post("/hunter/api/opportunities/{opp_id}/check")
def check_opportunity(opp_id: str) -> dict:
    return _run(tracker().check, opp_id)


@router.post("/hunter/api/check-all")
def check_all() -> dict:
    t = tracker()
    t.check_all()
    return t.state()


@router.post("/hunter/api/opportunities/{opp_id}/review")
def resolve_review(opp_id: str, body: ResolveBody) -> dict:
    return _run(tracker().resolve_review, opp_id, body.action, body.decision, body.note)


@router.get("/hunter/api/opportunities/{opp_id}/history")
def get_history(opp_id: str) -> dict:
    return _run(tracker().history, opp_id)


@router.delete("/hunter/api/opportunities/{opp_id}")
def remove_opportunity(opp_id: str) -> dict:
    tracker().remove(opp_id)
    return {"status": "removed"}


@router.post("/hunter/api/demo/load")
def demo_load() -> dict:
    return tracker().load_demo()


@router.post("/hunter/api/demo/publish-v2")
def demo_publish_v2() -> dict:
    return tracker().publish_demo_v2()


@router.delete("/hunter/api/demo")
def demo_clear() -> dict:
    return tracker().clear_demo()


@router.get(sources.DEMO_PREFIX + "{slug}", response_class=HTMLResponse)
def demo_listing_page(slug: str) -> HTMLResponse:
    """Serve the demo listing at its current version so source links work."""
    try:
        page = sources.demo_page(slug, tracker().demo_version())
    except sources.SourceError as exc:
        status = 503 if "503" in str(exc) else 404
        return HTMLResponse(
            f"<h1>{status}</h1><p>{exc}</p><p>(Demo fixture.)</p>", status_code=status
        )
    return HTMLResponse(page.html)
