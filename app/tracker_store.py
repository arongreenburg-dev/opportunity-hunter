"""Persistence for tracked opportunities, decisions and source-check history.

Uses the repo's existing Cloud Firestore project when credentials are
available (``OH_STORAGE=firestore`` or auto-detected). Falls back to a local
JSON file so the app and demo run without any cloud setup
(``OH_STORAGE=local``).
"""

from __future__ import annotations

import json
import os
import threading
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCAL_PATH = ROOT / ".oh_state" / "tracker.json"


class LocalJsonStore:
    kind = "local"

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or os.getenv("OH_LOCAL_STORE") or DEFAULT_LOCAL_PATH)
        self._lock = threading.RLock()

    # -- internals --------------------------------------------------------
    def _read(self) -> dict:
        if not self.path.exists():
            return {"opportunities": {}, "checks": {}, "meta": {}}
        data = json.loads(self.path.read_text() or "{}")
        data.setdefault("opportunities", {})
        data.setdefault("checks", {})
        data.setdefault("meta", {})
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, default=str))
        tmp.replace(self.path)

    # -- opportunities ----------------------------------------------------
    def list_opportunities(self) -> list[dict]:
        with self._lock:
            return list(self._read()["opportunities"].values())

    def get_opportunity(self, opp_id: str) -> dict | None:
        with self._lock:
            return self._read()["opportunities"].get(opp_id)

    def put_opportunity(self, record: dict) -> None:
        with self._lock:
            data = self._read()
            data["opportunities"][record["id"]] = record
            self._write(data)

    def delete_opportunity(self, opp_id: str) -> None:
        with self._lock:
            data = self._read()
            data["opportunities"].pop(opp_id, None)
            data["checks"].pop(opp_id, None)
            self._write(data)

    # -- checks -----------------------------------------------------------
    def add_check(self, opp_id: str, check: dict) -> None:
        with self._lock:
            data = self._read()
            data["checks"].setdefault(opp_id, []).append(check)
            self._write(data)

    def list_checks(self, opp_id: str) -> list[dict]:
        with self._lock:
            return list(reversed(self._read()["checks"].get(opp_id, [])))

    # -- meta -------------------------------------------------------------
    def get_meta(self, key: str, default=None):
        with self._lock:
            return self._read()["meta"].get(key, default)

    def set_meta(self, key: str, value) -> None:
        with self._lock:
            data = self._read()
            data["meta"][key] = value
            self._write(data)


class FirestoreStore:
    """Same interface, backed by the project's Firestore database."""

    kind = "firestore"

    def __init__(self) -> None:
        from app.memory_store import get_db

        self.db = get_db()
        self.collection = self.db.collection("tracked_opportunities")
        self.meta = self.db.collection("tracker_meta")

    def list_opportunities(self) -> list[dict]:
        return [doc.to_dict() for doc in self.collection.stream()]

    def get_opportunity(self, opp_id: str) -> dict | None:
        snap = self.collection.document(opp_id).get()
        return snap.to_dict() if snap.exists else None

    def put_opportunity(self, record: dict) -> None:
        self.collection.document(record["id"]).set(record)

    def delete_opportunity(self, opp_id: str) -> None:
        ref = self.collection.document(opp_id)
        for doc in ref.collection("checks").stream():
            doc.reference.delete()
        ref.delete()

    def add_check(self, opp_id: str, check: dict) -> None:
        self.collection.document(opp_id).collection("checks").document(check["id"]).set(
            check
        )

    def list_checks(self, opp_id: str) -> list[dict]:
        docs = self.collection.document(opp_id).collection("checks").stream()
        return sorted(
            (d.to_dict() for d in docs), key=lambda c: c["checked_at"], reverse=True
        )

    def get_meta(self, key: str, default=None):
        snap = self.meta.document(key).get()
        return snap.to_dict().get("value", default) if snap.exists else default

    def set_meta(self, key: str, value) -> None:
        self.meta.document(key).set({"value": value})


def _firestore_available() -> bool:
    try:
        import google.auth

        google.auth.default()
        return True
    except Exception:
        return False


@cache
def get_store():
    mode = os.getenv("OH_STORAGE", "auto").lower()
    if mode == "firestore" or (mode == "auto" and _firestore_available()):
        return FirestoreStore()
    return LocalJsonStore()
