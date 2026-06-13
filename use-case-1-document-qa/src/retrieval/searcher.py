"""Hybrid retrieval (BM25 + vector + RRF — fully supported on the FREE Search
tier) with a per-document fan-out strategy for comparison queries.

Comparison rationale: naive top-k lets one verbose policy crowd out the others.
We enumerate documents via a facet query (zero extra infrastructure), then run
the same hybrid sub-query once per document with a filter, so every document is
guaranteed representation in the evidence."""
from dataclasses import dataclass

from azure.search.documents.models import VectorizedQuery
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.azure_clients import search_client
from src.core.config import get_settings
from src.core.logging import get_logger
from src.indexing.embedder import embed_query

log = get_logger("searcher")

_SELECT = ["chunk_id", "doc_id", "doc_name", "doc_type", "page_start", "page_end",
           "synthetic_pages", "heading_path", "content"]


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    doc_name: str
    doc_type: str
    page_start: int
    page_end: int
    synthetic_pages: bool
    heading_path: str
    content: str
    score: float


def _to_chunk(result: dict) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=result["chunk_id"], doc_id=result["doc_id"], doc_name=result["doc_name"],
        doc_type=result.get("doc_type") or "other",
        page_start=result.get("page_start") or 1, page_end=result.get("page_end") or 1,
        synthetic_pages=bool(result.get("synthetic_pages")),
        heading_path=result.get("heading_path") or "", content=result["content"],
        score=result.get("@search.score") or 0.0,
    )


@retry(wait=wait_exponential(min=1, max=15), stop=stop_after_attempt(4), reraise=True)
def hybrid_search(query: str, top: int, doc_filter: str | None = None) -> list[RetrievedChunk]:
    """One hybrid query: BM25 text leg + client-side-embedded vector leg, RRF-fused."""
    vector = VectorizedQuery(vector=embed_query(query), k_nearest_neighbors=50,
                             fields="content_vector")
    results = search_client().search(
        search_text=query,
        vector_queries=[vector],
        filter=doc_filter,
        select=_SELECT,
        top=top,
    )
    return [_to_chunk(r) for r in results]


def list_indexed_documents() -> list[str]:
    """Enumerate distinct documents via a facet query (free-tier friendly)."""
    results = search_client().search(search_text="*", facets=["doc_name,count:50"], top=0)
    facets = results.get_facets() or {}
    return [f["value"] for f in facets.get("doc_name", [])]


def comparison_search(query: str) -> dict[str, list[RetrievedChunk]]:
    """Per-document fan-out: guarantee every document contributes evidence.

    Sub-queries run concurrently (ThreadPoolExecutor) — for 4 policies that's
    a ~4× wall-clock speedup over sequential fan-out. The Search SDK is
    thread-safe; we serialize names → futures → ordered dict for stable order."""
    from concurrent.futures import ThreadPoolExecutor

    settings = get_settings()
    doc_names = list_indexed_documents()[: settings.compare_max_docs]
    if not doc_names:
        return {}

    def one(name: str) -> tuple[str, list[RetrievedChunk]]:
        safe = name.replace("'", "''")
        return name, hybrid_search(query, top=settings.compare_k_per_doc,
                                   doc_filter=f"doc_name eq '{safe}'")

    with ThreadPoolExecutor(max_workers=min(8, len(doc_names))) as pool:
        results = list(pool.map(one, doc_names))

    evidence = {name: chunks for name, chunks in results if chunks}
    log.info("comparison_fanout", documents=len(evidence), parallel=True)
    return evidence
