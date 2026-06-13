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
    # Structured Outputs capability: "auto" probes once, "on" forces (gpt-4o),
    # "off" skips it (Kimi/serverless) to avoid a wasted round-trip per call.
    structured_outputs: str = "auto"

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

    # TLS verification. Keep True in production. Set False ONLY for a local demo
    # behind a corporate TLS-intercepting proxy whose root CA isn't in the trust
    # store (symptom: CERTIFICATE_VERIFY_FAILED on every Azure call). The proper
    # fix is to add the corporate root CA — see docs/SETUP.md.
    verify_ssl: bool = True

    # App behaviour
    data_dir: Path = Path("./data")
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 80
    top_k: int = 5
    compare_k_per_doc: int = 4
    compare_max_docs: int = 8
    rrf_floor: float = 0.01
    api_base_url: str = "http://localhost:8000"

    # Agentic RAG: self-grade retrieval and re-query once if the evidence is weak.
    agentic_rag: bool = True
    agentic_max_retries: int = 1
    agentic_recall_k: int = 8  # widened top-k used on a corrective retry
    # Fire a tiny chat+embed call on startup so the first real query doesn't pay
    # the serverless cold-start. Off by default (adds a few seconds to boot).
    warmup_on_startup: bool = False


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "uploads").mkdir(exist_ok=True)
    (settings.data_dir / "extracts").mkdir(exist_ok=True)
    return settings
