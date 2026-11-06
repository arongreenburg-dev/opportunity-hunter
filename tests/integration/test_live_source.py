"""Opt-in live check against a real official listing.

    OH_LIVE_URL=https://www.nsf.gov/funding/opportunities/reu-research-experiences-undergraduates \
    OH_LIVE_TITLE="Research Experiences for Undergraduates (REU)" \
    uv run pytest tests/integration/test_live_source.py -q

Skipped unless OH_LIVE_URL and OH_LIVE_TITLE are set (needs outbound network access).
"""

import os

import pytest

from app import recheck
from app.tracker import Tracker
from app.tracker_store import LocalJsonStore

LIVE_URL = os.getenv("OH_LIVE_URL")
LIVE_TITLE = os.getenv("OH_LIVE_TITLE")


@pytest.mark.skipif(
    not (LIVE_URL and LIVE_TITLE), reason="set OH_LIVE_URL and OH_LIVE_TITLE to run"
)
def test_live_official_listing_baseline_then_recheck(tmp_path):
    t = Tracker(LocalJsonStore(tmp_path / "live.json"))
    o = t.track(
        title=LIVE_TITLE,
        source_url=LIVE_URL,
        decision="watch",
        reason="Checking deadline and eligibility",
    )
    assert o["last_check"]["outcome"] == "verified", o["last_check"]
    assert o["evidence"]["fields"], "no priority fields extracted"
    again = t.check(o["id"])
    # An unchanged official page must not create review noise.
    assert again["last_check"]["verdict"] in (
        recheck.VERDICT_CURRENT,
        recheck.VERDICT_QUIET,
    )
    assert not (again.get("review") or {}).get("open")
