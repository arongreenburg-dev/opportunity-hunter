"""Decision tracking workflow: save a decision, recheck the source, review changes."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime

from app import recheck, sources

PRIORITY = {
    recheck.VERDICT_RECONSIDER: 3,
    recheck.VERDICT_REVIEW: 2,
    recheck.VERDICT_UNVERIFIED: 1,
}


class TrackerError(ValueError):
    """Invalid request; message is user-facing."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _opp_id(title: str, url: str) -> str:
    key = (url or "").split("#")[0].rstrip("/").lower() or title.strip().lower()
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class Tracker:
    def __init__(self, store, *, today: date | None = None) -> None:
        self.store = store
        self._today = today

    # -- helpers ------------------------------------------------------------
    @property
    def today(self) -> date:
        return self._today or date.today()

    def demo_version(self) -> int:
        return int(self.store.get_meta("demo_version", 1) or 1)

    def _get(self, opp_id: str) -> dict:
        record = self.store.get_opportunity(opp_id)
        if not record:
            raise TrackerError("That opportunity is no longer on your watchlist.")
        return record

    # -- decisions ----------------------------------------------------------
    def track(
        self,
        *,
        title: str,
        organization: str = "",
        source_url: str = "",
        decision: str = "watch",
        reason: str = "",
        evidence_note: str = "",
        is_demo: bool = False,
        check_now: bool = True,
    ) -> dict:
        title = (title or "").strip()
        decision = (decision or "").strip().lower()
        if not title:
            raise TrackerError("Give the opportunity a name.")
        if decision not in recheck.DECISIONS:
            raise TrackerError("Choose Pursue, Watch or Pass.")
        if not (reason or "").strip():
            raise TrackerError(
                "Add a short reason so future changes can be checked against it."
            )

        now = _now()
        opp_id = _opp_id(title, source_url)
        existing = self.store.get_opportunity(opp_id)
        record = existing or {
            "id": opp_id,
            "created_at": now,
            "evidence": None,
            "last_check": None,
            "review": None,
            "decision_history": [],
        }
        record["title"] = title
        record["organization"] = (organization or "").strip()
        record["source_url"] = (source_url or "").strip()
        record["evidence_note"] = (evidence_note or "").strip()
        record["is_demo"] = is_demo
        record["updated_at"] = now
        self._apply_decision(record, decision, reason.strip(), via="saved")
        self.store.put_opportunity(record)
        if check_now and record["source_url"] and not record.get("evidence"):
            return self.check(opp_id)
        return record

    def _apply_decision(
        self, record: dict, decision: str, reason: str, via: str
    ) -> None:
        entry = {"value": decision, "reason": reason, "decided_at": _now(), "via": via}
        record["decision"] = entry
        record.setdefault("decision_history", []).append(entry)

    def set_decision(self, opp_id: str, decision: str, reason: str) -> dict:
        decision = (decision or "").lower()
        if decision not in recheck.DECISIONS:
            raise TrackerError("Choose Pursue, Watch or Pass.")
        if not (reason or "").strip():
            raise TrackerError("Add a short reason for the decision.")
        record = self._get(opp_id)
        self._apply_decision(record, decision, reason.strip(), via="edited")
        record["updated_at"] = _now()
        self.store.put_opportunity(record)
        return record

    def remove(self, opp_id: str) -> None:
        self.store.delete_opportunity(opp_id)

    # -- source rechecks ----------------------------------------------------
    def check(self, opp_id: str) -> dict:
        record = self._get(opp_id)
        checked_at = _now()
        baseline = (record.get("evidence") or {}).get("fields")
        current = None
        page_title = ""
        error = None
        try:
            result = sources.fetch(
                record["source_url"], demo_version=self.demo_version()
            )
            page_title, text = recheck.html_to_text(result.html)
            current = recheck.extract_evidence(text)
        except sources.SourceError as exc:
            error = str(exc)

        decision = record["decision"]
        verdict = recheck.evaluate_check(
            baseline=baseline,
            current=current,
            page_title=page_title,
            expected_title=record["title"],
            decision=decision["value"],
            reason=decision["reason"],
            error=error,
            today=self.today,
        )

        check = {
            "id": uuid.uuid4().hex[:12],
            "checked_at": checked_at,
            "source_url": record["source_url"],
            "page_title": page_title,
            "outcome": verdict["outcome"],
            "verdict": verdict["verdict"],
            "headline": verdict["headline"],
            "explanation": verdict["explanation"],
            "changes": verdict["changes"],
            "evidence": current if verdict["outcome"] == "verified" else None,
            "error": error,
            "decision_at_check": decision["value"],
        }
        self.store.add_check(opp_id, check)

        baseline_checked_at = (record.get("evidence") or {}).get("checked_at")
        record["last_check"] = {
            k: check[k]
            for k in ("id", "checked_at", "outcome", "verdict", "headline", "error")
        }
        if verdict["outcome"] == "verified":
            # Only successful checks advance the baseline.
            record["evidence"] = {
                "fields": current,
                "checked_at": checked_at,
                "page_title": page_title,
                "hash": recheck.content_hash(current or {}),
                "check_id": check["id"],
            }

        open_review = (
            record.get("review") if (record.get("review") or {}).get("open") else None
        )
        if verdict["verdict"] in recheck.ATTENTION_VERDICTS:
            new_priority = PRIORITY[verdict["verdict"]]
            if not open_review or new_priority >= PRIORITY.get(
                open_review["verdict"], 0
            ):
                record["review"] = {
                    "open": True,
                    "verdict": verdict["verdict"],
                    "headline": verdict["headline"],
                    "explanation": verdict["explanation"],
                    "changes": verdict["changes"],
                    "related_fields": verdict.get("related_fields", []),
                    "suggested_decision": verdict.get("suggested_decision"),
                    "check_id": check["id"],
                    "created_at": checked_at,
                    "decision_at_check": decision["value"],
                    "baseline_checked_at": baseline_checked_at,
                    "last_verified_at": (record.get("evidence") or {}).get(
                        "checked_at"
                    ),
                }
        elif open_review and open_review["verdict"] == recheck.VERDICT_UNVERIFIED:
            # Source is reachable again; the failure no longer needs attention.
            open_review.update(
                {
                    "open": False,
                    "resolved_at": checked_at,
                    "resolution": "source recovered",
                }
            )

        record["updated_at"] = checked_at
        self.store.put_opportunity(record)
        return record

    def check_all(self) -> list[dict]:
        return [
            self.check(r["id"])
            for r in self.store.list_opportunities()
            if r.get("source_url")
        ]

    def resolve_review(
        self, opp_id: str, action: str, decision: str | None = None, note: str = ""
    ) -> dict:
        record = self._get(opp_id)
        review = record.get("review")
        if not review or not review.get("open"):
            raise TrackerError("There is nothing to review for this opportunity.")
        now = _now()
        if action == "change":
            decision = (decision or "").lower()
            if decision not in recheck.DECISIONS:
                raise TrackerError("Choose Pursue, Watch or Pass.")
            reason = (
                note.strip()
                or f"Reconsidered after source change: {review['headline']}"
            )
            self._apply_decision(record, decision, reason, via="review")
            resolution = f"changed to {decision}"
        elif action == "keep":
            resolution = f"kept {record['decision']['value']}"
            record["decision_history"].append(
                {
                    "value": record["decision"]["value"],
                    "reason": record["decision"]["reason"],
                    "decided_at": now,
                    "via": f"reviewed: {review['headline']}",
                }
            )
        else:
            raise TrackerError("Unknown review action.")
        review.update({"open": False, "resolved_at": now, "resolution": resolution})
        record["updated_at"] = now
        self.store.put_opportunity(record)
        return record

    # -- views --------------------------------------------------------------
    def history(self, opp_id: str) -> dict:
        record = self._get(opp_id)
        return {"opportunity": record, "checks": self.store.list_checks(opp_id)}

    def state(self) -> dict:
        records = sorted(
            self.store.list_opportunities(),
            key=lambda r: r.get("updated_at", ""),
            reverse=True,
        )
        queue = [r for r in records if (r.get("review") or {}).get("open")]
        queue.sort(
            key=lambda r: (
                -PRIORITY.get(r["review"]["verdict"], 0),
                r["review"]["created_at"],
            )
        )
        checks = [r["last_check"]["checked_at"] for r in records if r.get("last_check")]
        demo_records = [r for r in records if r.get("is_demo")]
        published_at = self.store.get_meta("demo_published_at")
        demo_checked = bool(
            published_at
            and demo_records
            and all(
                (r.get("last_check") or {}).get("checked_at", "") >= published_at
                for r in demo_records
            )
        )
        return {
            "storage": self.store.kind,
            "demo": {
                "active": bool(demo_records),
                "version": self.demo_version(),
                "checked_since_publish": demo_checked,
            },
            "last_checked_at": max(checks) if checks else None,
            "queue": [r["id"] for r in queue],
            "opportunities": records,
        }

    # -- demo ---------------------------------------------------------------
    def load_demo(self) -> dict:
        self.clear_demo()
        self.store.set_meta("demo_version", 1)
        for listing in sources.demo_manifest()["listings"]:
            self.track(
                title=listing["title"],
                organization=listing["organization"],
                source_url=sources.DEMO_PREFIX + listing["slug"],
                decision=listing["decision"],
                reason=listing["reason"],
                is_demo=True,
            )
        return self.state()

    def publish_demo_v2(self) -> dict:
        self.store.set_meta("demo_version", 2)
        self.store.set_meta("demo_published_at", _now())
        return self.state()

    def clear_demo(self) -> dict:
        for record in self.store.list_opportunities():
            if record.get("is_demo"):
                self.store.delete_opportunity(record["id"])
        self.store.set_meta("demo_version", 1)
        self.store.set_meta("demo_published_at", None)
        return self.state()
