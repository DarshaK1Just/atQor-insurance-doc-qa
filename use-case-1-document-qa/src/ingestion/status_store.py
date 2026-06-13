"""Per-document status tracking (assignment §4.1) — file-backed so status
survives restarts. Statuses: uploaded → extracting → classifying → chunking →
indexing → ready | failed."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import get_settings

_LOCK = threading.Lock()


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

    def list_all(self) -> list[dict[str, Any]]:
        with _LOCK:
            return sorted(self._load().values(), key=lambda d: d["upload_ts"], reverse=True)


status_store = StatusStore()
