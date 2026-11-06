"""Unit tests for the deterministic evidence extraction and comparison engine."""

from datetime import date
from pathlib import Path

from app import recheck

DEMO = Path(__file__).resolve().parents[2] / "data" / "demo"
TODAY = date(2026, 11, 6)


def evidence(name: str) -> tuple[str, dict]:
    title, text = recheck.html_to_text((DEMO / name).read_text())
    return title, recheck.extract_evidence(text)


def test_extracts_priority_fields_from_structured_page():
    title, ev = evidence("northstar.v1.html")
    assert title.startswith("Northstar Health AI Challenge")
    assert set(ev) == {"deadline", "eligibility", "participation", "submission"}
    assert ev["deadline"]["dates"] == ["2027-01-15", "2027-02-01", "2027-03-04"]
    assert ev["participation"]["modes"] == ["in_person"]
    # Sections stop at the next heading; prize copy does not leak in.
    assert "prize" not in ev["submission"]["text"].lower()


def test_participation_modes():
    assert (
        recheck.participation_modes("Remote participation is not available.") == set()
    )
    assert recheck.participation_modes("Fully remote. No travel is required.") == {
        "remote"
    }
    assert recheck.participation_modes(
        "Finalists may present remotely or in person in Boston. Travel is optional."
    ) == {"remote", "in_person"}
    assert recheck.participation_modes("This is a hybrid event.") == {
        "remote",
        "in_person",
    }


def test_parse_dates_formats():
    assert recheck.parse_dates("Due Jan. 5, 2027 or 2027-02-01 or 3 March 2027") == [
        "2027-01-05",
        "2027-02-01",
        "2027-03-03",
    ]


def test_travel_to_remote_reopens_pass():
    _, v1 = evidence("northstar.v1.html")
    title, v2 = evidence("northstar.v2.html")
    result = recheck.evaluate_check(
        baseline=v1,
        current=v2,
        page_title=title,
        expected_title="Northstar Health AI Challenge",
        decision="pass",
        reason="Final round requires in-person travel to Boston.",
        today=TODAY,
    )
    assert result["verdict"] == recheck.VERDICT_RECONSIDER
    assert result["related_fields"] == ["participation"]
    assert result["suggested_decision"] == "pursue"
    assert "travel" in result["explanation"].lower()
    (change,) = result["changes"]
    assert change["field"] == "participation" and change["kind"] == "material"
    assert "remote" in change["after"].lower() and "not available" in change["before"]


def test_cosmetic_rewording_stays_quiet():
    _, v1 = evidence("civic.v1.html")
    title, v2 = evidence("civic.v2.html")
    result = recheck.evaluate_check(
        baseline=v1,
        current=v2,
        page_title=title,
        expected_title="Civic Data Fellowship 2027",
        decision="watch",
        reason="Waiting for the stipend amount to be announced; deadline is fine.",
        today=TODAY,
    )
    assert result["verdict"] == recheck.VERDICT_QUIET
    assert result["verdict"] not in recheck.ATTENTION_VERDICTS
    assert {c["kind"] for c in result["changes"]} == {"cosmetic"}


def test_unrelated_travel_change_does_not_reopen_on_unrelated_reason():
    _, v1 = evidence("northstar.v1.html")
    _, v2 = evidence("northstar.v2.html")
    result = recheck.evaluate_check(
        baseline=v1,
        current=v2,
        page_title="",
        expected_title="",
        decision="pass",
        reason="Prize is too small for the effort.",
        today=TODAY,
    )
    # Still material, so it is surfaced, but not as Reconsider.
    assert result["verdict"] == recheck.VERDICT_REVIEW


def test_material_changes_detected():
    cases = [
        (
            "deadline",
            "Applications close March 1, 2027.",
            "Applications close March 15, 2027.",
        ),
        ("eligibility", "Open to US residents.", "Open to residents of Canada."),
        ("submission", "A demo video is optional.", "A demo video is required."),
        ("submission", "Budget up to $25,000.", "Budget up to $10,000."),
    ]
    for field, before, after in cases:
        change = recheck.classify_field_change(field, before, after)
        assert change and change.kind == "material", (before, after)


def test_deadline_extension_reopens_pass_for_timing_reason():
    base = {"deadline": {"text": "Applications close January 5, 2027."}}
    now = {"deadline": {"text": "Applications close February 20, 2027."}}
    result = recheck.evaluate_check(
        baseline=base,
        current=now,
        page_title="",
        expected_title="",
        decision="pass",
        reason="Deadline is too soon; not enough time.",
        today=TODAY,
    )
    assert result["verdict"] == recheck.VERDICT_RECONSIDER


def test_earlier_deadline_flags_pursue_for_review():
    base = {"deadline": {"text": "Proposals are due April 30, 2027."}}
    now = {"deadline": {"text": "Proposals are due March 1, 2027."}}
    result = recheck.evaluate_check(
        baseline=base,
        current=now,
        page_title="",
        expected_title="",
        decision="pursue",
        reason="Great fit.",
        today=TODAY,
    )
    assert result["verdict"] == recheck.VERDICT_REVIEW
    assert "tightened" in result["headline"]


def test_retrieval_failure_is_unverified():
    result = recheck.evaluate_check(
        baseline={"deadline": {"text": "x"}},
        current=None,
        page_title="",
        expected_title="",
        decision="pursue",
        reason="r",
        error="The official page returned HTTP 503.",
    )
    assert result["outcome"] == "failed"
    assert result["verdict"] == recheck.VERDICT_UNVERIFIED
    assert "unchanged" in result["explanation"]


def test_ambiguous_pages_are_unverified():
    _, v1 = evidence("northstar.v1.html")
    # Different page at the same URL.
    wrong = recheck.evaluate_check(
        baseline=v1,
        current=v1,
        page_title="Page not found | Northwind Careers",
        expected_title="Northstar Health AI Challenge",
        decision="pass",
        reason="travel",
    )
    assert (
        wrong["outcome"] == "ambiguous"
        and wrong["verdict"] == recheck.VERDICT_UNVERIFIED
    )
    # Most key terms vanished.
    gutted = recheck.evaluate_check(
        baseline=v1,
        current={"deadline": v1["deadline"]},
        page_title="",
        expected_title="",
        decision="pass",
        reason="travel",
    )
    assert gutted["outcome"] == "ambiguous"
    # Nothing extractable at all.
    empty = recheck.evaluate_check(
        baseline=v1,
        current={},
        page_title="",
        expected_title="",
        decision="pass",
        reason="x",
    )
    assert empty["outcome"] == "ambiguous"


def test_word_diff_marks_insertions_and_deletions():
    d = recheck.word_diff("Travel is required.", "Travel is optional.")
    assert {"op": "del", "text": "required."} in d["before"]
    assert {"op": "ins", "text": "optional."} in d["after"]
