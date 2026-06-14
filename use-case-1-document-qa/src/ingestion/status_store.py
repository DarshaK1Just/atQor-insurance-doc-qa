"""Per-document status tracking (assignment §4.1) — file-backed so status
survives restarts. Statuses: uploaded → extracting → classifying → chunking →
indexing → ready | failed."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import get_settings
from src.core.logging import get_logger

log = get_logger("status_store")
_LOCK = threading.Lock()

# States that mean "a worker should be actively progressing this document".
_NON_TERMINAL = ("uploaded", "extracting", "classifying", "chunking", "indexing")


class StatusStore:
    def __init__(self) -> None:
        self._path: Path = get_settings().data_dir / "status.json"

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            return json.loads(self._path.read_text(encoding="utf-8"))
        return {}

    def _save(self, data: dict[str, Any]) -> None:
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def create(self, doc_id: str, doc_name: str) -> None:
        with _LOCK:
            data = self._load()
            data[doc_id] = {
                "doc_id": doc_id,
                "doc_name": doc_name,
                "status": "uploaded",
                "detail": "",
                "doc_type": "",
                "pages": 0,
                "chunks": 0,
                "upload_ts": datetime.now(timezone.utc).isoformat(),
                "updated_ts": datetime.now(timezone.utc).isoformat(),
            }
            self._save(data)

    def update(self, doc_id: str, status: str, **fields: Any) -> None:
        with _LOCK:
            data = self._load()
            if doc_id in data:
                data[doc_id].update(status=status, updated_ts=datetime.now(timezone.utc).isoformat(), **fields)
                self._save(data)

    def get(self, doc_id: str) -> dict[str, Any] | None:
        with _LOCK:
            return self._load().get(doc_id)

    def delete(self, doc_id: str) -> None:
        with _LOCK:
            data = self._load()
            if data.pop(doc_id, None) is not None:
                self._save(data)

    def list_all(self) -> list[dict[str, Any]]:
        with _LOCK:
            return sorted(self._load().values(), key=lambda d: d["upload_ts"], reverse=True)

    def reap_stale(self, max_age_seconds: float) -> int:
        """Self-heal orphaned documents so the UI never shows perpetual 'processing'.

        A non-terminal document whose `updated_ts` is older than `max_age_seconds`
        has no live worker (server restart, or a genuinely hung Azure call). For
        each such ghost:
          · if a *ready* document with the same name already exists → delete the
            duplicate (cleans the corpus, e.g. demo loaded twice);
          · otherwise → mark it 'failed' with a clear reason.

        Called at boot with age 0 (every in-flight doc is an orphan after a
        restart) and opportunistically from GET /documents for live hangs.
        Returns the number of records reaped."""
        now = datetime.now(timezone.utc)
        reaped = 0
        with _LOCK:
            data = self._load()
            ready_names = {d["doc_name"] for d in data.values() if d.get("status") == "ready"}
            for doc_id, rec in list(data.items()):
                if rec.get("status") not in _NON_TERMINAL:
                    continue
                try:
                    updated = datetime.fromisoformat(rec.get("updated_ts", rec["upload_ts"]))
                except (ValueError, KeyError):
                    updated = now
                if (now - updated).total_seconds() < max_age_seconds:
                    continue
                if rec.get("doc_name") in ready_names:
                    data.pop(doc_id, None)  # a good copy exists — drop the duplicate
                    log.info("reaped_duplicate", doc_id=doc_id, doc_name=rec.get("doc_name"))
                else:
                    rec.update(status="failed",
                               detail="Processing was interrupted (server restart or timeout). "
                                      "Re-upload the document to retry.",
                               updated_ts=now.isoformat())
                    log.info("reaped_orphan", doc_id=doc_id, doc_name=rec.get("doc_name"))
                reaped += 1
            if reaped:
                self._save(data)
        return reaped


status_store = StatusStore()
