from datetime import datetime, timezone

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
