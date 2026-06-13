"""Azure Blob Storage for originals + extracted content (assignment §5).
Gracefully degrades to local disk when no connection string is configured,
so reviewers can run the core RAG flow with only DI + Search + AOAI."""
from pathlib import Path

from src.core.config import get_settings
from src.core.logging import get_logger

log = get_logger("blob_store")


class BlobStore:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._service = None
        if self._settings.blob_connection_string:
            from azure.storage.blob import BlobServiceClient
            self._service = BlobServiceClient.from_connection_string(self._settings.blob_connection_string)
            for container in (self._settings.blob_container_originals, self._settings.blob_container_extracts):
                try:
                    self._service.create_container(container)
                except Exception:
                    pass  # already exists

    @property
    def enabled(self) -> bool:
        return self._service is not None

    def upload(self, container: str, blob_name: str, data: bytes) -> str | None:
        """Upload and return the blob URL; None when running in local-disk mode."""
        if not self._service:
            log.info("blob_disabled_local_mode", blob=blob_name)
            return None
        client = self._service.get_blob_client(container=container, blob=blob_name)
        client.upload_blob(data, overwrite=True)
        return client.url

    def upload_original(self, doc_id: str, path: Path) -> str | None:
        return self.upload(self._settings.blob_container_originals, f"{doc_id}/{path.name}", path.read_bytes())

    def upload_extract(self, doc_id: str, markdown: str) -> str | None:
        return self.upload(self._settings.blob_container_extracts, f"{doc_id}/extract.md",
                           markdown.encode("utf-8"))


blob_store = BlobStore()
