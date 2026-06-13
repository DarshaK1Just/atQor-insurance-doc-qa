"""Central configuration. Every Azure endpoint, key, deployment name and
behavioural knob is externalised here (assignment §6: Configuration Management).
Reviewers plug their own credentials into `.env` — nothing is hardcoded."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Azure OpenAI
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_chat_deployment: str = "gpt-4o-mini"
    azure_openai_embed_deployment: str = "text-embedding-3-small"
    embed_dimensions: int = 1536

    # Document Intelligence
    docintel_endpoint: str = ""
    docintel_key: str = ""
    docintel_page_window: int = 2  # 0 disables the F0 two-page-window splitter

    # Azure AI Search
    search_endpoint: str = ""
    search_key: str = ""
    search_index_name: str = "insurance-chunks"

    # Blob storage (optional; local-disk fallback keeps the app runnable)
    blob_connection_string: str = ""
    blob_container_originals: str = "originals"
    blob_container_extracts: str = "extracts"

    # App behaviour
    data_dir: Path = Path("./data")
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 80
    top_k: int = 5
    compare_k_per_doc: int = 4
    compare_max_docs: int = 8
    rrf_floor: float = 0.01
    api_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "uploads").mkdir(exist_ok=True)
    (settings.data_dir / "extracts").mkdir(exist_ok=True)
    return settings
