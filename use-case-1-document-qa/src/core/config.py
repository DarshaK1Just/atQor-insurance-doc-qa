"""Central configuration. Every Azure endpoint, key, deployment name and
behavioural knob is externalised here (assignment §6: Configuration Management).
Reviewers plug their own credentials into `.env` — nothing is hardcoded."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Chat LLM provider ─────────────────────────────────────────────────────
    # The CHAT model can be served by Azure OpenAI/Foundry or by Google Gemini
    # (via its OpenAI-compatible endpoint). Selected from .env:
    #   llm_provider="auto"   → Gemini if GEMINI_API_KEY is set, else Azure (default)
    #   llm_provider="gemini" → force Gemini      llm_provider="azure" → force Azure
    # EMBEDDINGS always stay on Azure — the search index is built on their 1536-d
    # vectors, so the retrieval path is unaffected by the chat-provider choice.
    llm_provider: str = "auto"

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

    # Google Gemini (OpenAI-compatible endpoint). gemini-2.5-flash has free-tier
    # quota and is fast; thinking is disabled per-call (reasoning_effort=none) so
    # short responses aren't eaten by reasoning tokens.
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

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
    # PERF: the LLM grader is a full extra round-trip, so it now fires ONLY when
    # the first-pass retrieval looks thin (fewer than `agentic_grade_when_chunks_below`
    # chunks). Strong retrievals skip it entirely — the common, fast path.
    agentic_rag: bool = True
    agentic_max_retries: int = 1
    agentic_recall_k: int = 8  # widened top-k used on a corrective retry
    agentic_grade_when_chunks_below: int = 3  # only critique sparse retrievals
    # Fire a tiny chat+embed call on startup so the first real query doesn't pay
    # the serverless cold-start. Runs in a daemon thread, so boot is not blocked.
    warmup_on_startup: bool = True
    # Periodically ping the Azure embedding deployment so a scale-to-zero resource
    # stays warm — otherwise the first query after an idle gap pays a multi-second
    # cold-start on the embed call (visible as a large retrieve_ms). 0 disables.
    embed_keepalive_seconds: int = 240

    # Hard ceiling on any single LLM/HTTP round-trip, so a hung serverless call
    # fails fast instead of wedging an ingestion worker or a chat turn forever.
    request_timeout_seconds: float = 90.0
    # A document left in a non-terminal state longer than this (no worker has
    # touched it) is considered orphaned — auto-failed/cleaned by the reaper so
    # the UI never shows perpetual "processing".
    stale_doc_seconds: int = 150


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "uploads").mkdir(exist_ok=True)
    (settings.data_dir / "extracts").mkdir(exist_ok=True)
    return settings


def active_provider() -> str:
    """Resolve the chat-LLM provider from config. 'auto' prefers Gemini when a
    GEMINI_API_KEY is present (so dropping a key into .env switches the chat model),
    otherwise Azure."""
    s = get_settings()
    p = (s.llm_provider or "auto").strip().lower()
    if p in ("gemini", "google"):
        return "gemini"
    if p in ("azure", "openai", "foundry"):
        return "azure"
    return "gemini" if s.gemini_api_key else "azure"
