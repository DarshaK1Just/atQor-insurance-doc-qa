"""Azure Blob Storage for originals + extracted content (assignment §5).

Degrades gracefully to local disk when Blob isn't configured OR isn't reachable,
so the core RAG flow runs with only Document Intelligence + Search + Azure OpenAI.

Two design points that keep startup fast and ingestion resilient:
* The client + containers are created **lazily on first use, never at import** —
  a slow or firewall-blocked Blob endpoint can no longer stall `uvicorn` startup.
* The connection is probed **once** with retries disabled; if Blob is unreachable
  it's switched off for the session, so uploads skip instantly instead of
  retrying (and timing out) on every document.
"""
from pathlib import Path

from src.core.config import get_settings
from src.core.logging import get_logger

log = get_logger("blob_store")


class BlobStore:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._service = None
        self._initialized = False

    def _ensure(self) -> None:
        """Create the client + containers once, lazily and best-effort. Disables
        Blob for the session (local-disk mode) if the endpoint can't be reached."""
        if self._initialized:
            return
        self._initialized = True
        if not self._settings.blob_connection_string:
            return
        try:
            from azure.core.exceptions import ResourceExistsError
            from azure.storage.blob import BlobServiceClient

            ssl_kw = {} if self._settings.verify_ssl else {"connection_verify": False}
            # retry_total=0 + short timeout → a blocked host fails in seconds, not minutes.
            service = BlobServiceClient.from_connection_string(
                self._settings.blob_connection_string,
                retry_total=0, connection_timeout=5, read_timeout=15, **ssl_kw)

            reachable = False
            for container in (self._settings.blob_container_originals,
                              self._settings.blob_container_extracts):
                try:
                    service.create_container(container)
                    reachable = True
                except ResourceExistsError:
                    reachable = True  # container already there ⇒ endpoint is reachable
                except Exception:
                    pass  # network/firewall error on this container — keep probing
            if reachable:
                self._service = service
                log.info("blob_ready")
            else:
                log.warning("blob_unavailable_local_mode",
                            hint="Blob endpoint unreachable; originals are served from local disk.")
        except Exception as exc:
            log.warning("blob_init_failed_local_mode", error=type(exc).__name__)
            self._service = None

    @property
    def enabled(self) -> bool:
        self._ensure()
        return self._service is not None

    def upload(self, container: str, blob_name: str, data: bytes) -> str | None:
        """Upload and return the blob URL; None in local-disk mode or on failure.
        Best-effort: a Blob failure never aborts ingestion — the original is also
        on local disk, which is what the citation preview actually serves from."""
        self._ensure()
        if not self._service:
            return None
        try:
            client = self._service.get_blob_client(container=container, blob=blob_name)
            client.upload_blob(data, overwrite=True)
            return client.url
        except Exception as exc:
            log.warning("blob_upload_skipped", blob=blob_name, error=type(exc).__name__)
            return None

    def upload_original(self, doc_id: str, path: Path) -> str | None:
        return self.upload(self._settings.blob_container_originals, f"{doc_id}/{path.name}", path.read_bytes())

    def upload_extract(self, doc_id: str, markdown: str) -> str | None:
        return self.upload(self._settings.blob_container_extracts, f"{doc_id}/extract.md",
                           markdown.encode("utf-8"))


blob_store = BlobStore()
