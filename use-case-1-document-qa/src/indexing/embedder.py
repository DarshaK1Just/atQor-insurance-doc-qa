"""Batched embeddings via Azure OpenAI text-embedding-3-small (1536d).

Batches are sent concurrently via a ThreadPoolExecutor — for a 200-chunk
ingestion that's ~4 batches; running them in parallel collapses the embedding
phase from ~4-8s down to roughly the slowest single batch. The Azure OpenAI
client (httpx-backed) is thread-safe under concurrent use."""
from concurrent.futures import ThreadPoolExecutor

from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.azure_clients import openai_client
from src.core.config import get_settings
from src.core.logging import get_logger

log = get_logger("embedder")
_BATCH = 64
_MAX_PARALLEL = 6


@retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(5), reraise=True)
def _embed_batch(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    response = openai_client().embeddings.create(
        model=settings.azure_openai_embed_deployment,
        input=texts,
        dimensions=settings.embed_dimensions,
    )
    return [item.embedding for item in response.data]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    batches = [texts[i:i + _BATCH] for i in range(0, len(texts), _BATCH)]
    if len(batches) == 1:
        return _embed_batch(batches[0])
    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, len(batches))) as pool:
        results = list(pool.map(_embed_batch, batches))
    vectors = [vec for batch in results for vec in batch]
    log.info("embedded", count=len(vectors), batches=len(batches), parallel=True)
    return vectors


def embed_query(text: str) -> list[float]:
    return _embed_batch([text])[0]
