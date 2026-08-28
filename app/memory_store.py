from datetime import datetime, timezone
import hashlib
import json

from google.cloud import firestore


PROJECT_ID = "opportunity-hunter-506704"


def get_db():
    return firestore.Client(project=PROJECT_ID)


def save_profile(profile_id: str, profile: dict) -> dict:
    db = get_db()

    record = {
        **profile,
        "profile_id": profile_id,
        "updated_at": datetime.now(timezone.utc),
    }

    db.collection("profiles").document(profile_id).set(record)

    return {
        "status": "saved",
        "collection": "profiles",
        "document_id": profile_id,
    }


def get_profile(profile_id: str) -> dict:
    db = get_db()

    snapshot = db.collection("profiles").document(profile_id).get()

    if not snapshot.exists:
        return {
            "status": "not_found",
            "profile_id": profile_id,
        }

    data = snapshot.to_dict()

    return {
        "status": "found",
        "profile": data,
    }


def _opportunity_doc_id(candidate_id: str) -> str:
    """Create a Firestore-safe stable ID from the normalized candidate ID."""
    return hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:24]


def _opportunity_fingerprint(opportunity: dict) -> str:
    """Fingerprint only fields whose changes may matter to the user."""
    material_fields = {
        "title": opportunity.get("title", ""),
        "organization": opportunity.get("organization", ""),
        "deadline": opportunity.get("deadline", ""),
        "eligibility": opportunity.get("eligibility", ""),
        "location": opportunity.get("location", ""),
        "remote_option": opportunity.get("remote_option", ""),
        "financial_upside": opportunity.get("financial_upside", ""),
        "estimated_time_commitment": opportunity.get(
            "estimated_time_commitment", ""
        ),
        "requirements": opportunity.get("requirements", []),
        "current_status": opportunity.get("current_status", ""),
        "source_url": opportunity.get("source_url", ""),
    }

    canonical = json.dumps(
        material_fields,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def save_opportunity_evaluation(
    opportunity: dict,
    evaluation: dict,
) -> dict:
    """Persist an opportunity/evaluation and identify NEW/CHANGED/UNCHANGED state."""

    candidate_id = opportunity.get("candidate_id")

    if not candidate_id:
        return {
            "status": "error",
            "message": "candidate_id is required",
        }

    db = get_db()

    now = datetime.now(timezone.utc)
    doc_id = _opportunity_doc_id(candidate_id)
    fingerprint = _opportunity_fingerprint(opportunity)

    opportunity_ref = db.collection("opportunities").document(doc_id)
    existing_snapshot = opportunity_ref.get()

    if not existing_snapshot.exists:
        change_state = "NEW"
        first_seen = now
        previous_fingerprint = None
    else:
        existing = existing_snapshot.to_dict()
        previous_fingerprint = existing.get("fingerprint")
        first_seen = existing.get("first_seen", now)

        if previous_fingerprint == fingerprint:
            change_state = "UNCHANGED"
        else:
            change_state = "CHANGED"

    record = {
        **opportunity,
        "candidate_id": candidate_id,
        "fingerprint": fingerprint,
        "first_seen": first_seen,
        "last_seen": now,
        "change_state": change_state,
    }

    opportunity_ref.set(record)

    evaluation_record = {
        **evaluation,
        "candidate_id": candidate_id,
        "opportunity_doc_id": doc_id,
        "change_state": change_state,
        "evaluated_at": now,
    }

    db.collection("evaluations").add(evaluation_record)

    return {
        "status": "saved",
        "change_state": change_state,
        "candidate_id": candidate_id,
        "document_id": doc_id,
        "previous_fingerprint": previous_fingerprint,
        "fingerprint": fingerprint,
    }


def save_hunt(hunt_id: str, hunt: dict) -> dict:
    """Create or update a saved Opportunity Hunter Hunt."""
    db = get_db()
    now = datetime.now(timezone.utc)

    ref = db.collection("hunts").document(hunt_id)
    existing = ref.get()

    record = {
        **hunt,
        "hunt_id": hunt_id,
        "updated_at": now,
    }

    if existing.exists:
        record["created_at"] = existing.to_dict().get("created_at", now)
    else:
        record["created_at"] = now

    ref.set(record)

    return {
        "status": "saved",
        "hunt_id": hunt_id,
    }


def get_hunt(hunt_id: str) -> dict:
    """Retrieve one saved Hunt."""
    db = get_db()
    snapshot = db.collection("hunts").document(hunt_id).get()

    if not snapshot.exists:
        return {
            "status": "not_found",
            "hunt_id": hunt_id,
        }

    return {
        "status": "found",
        "hunt": snapshot.to_dict(),
    }


def list_hunts() -> dict:
    """Return all saved Hunts."""
    db = get_db()
    hunts = [doc.to_dict() for doc in db.collection("hunts").stream()]

    return {
        "status": "ok",
        "count": len(hunts),
        "hunts": hunts,
    }
