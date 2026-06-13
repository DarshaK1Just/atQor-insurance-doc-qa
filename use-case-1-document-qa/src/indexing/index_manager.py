"""Azure AI Search index-as-code (idempotent) + push upsert.

Schema is citation-grade: one search document per chunk, with doc/page/section
metadata that survives all the way to the UI. Vectors are stored:false (never
read back; halves storage on the 50 MB free tier). Push model chosen over the
indexer/skillset pipeline so chunk metadata stays under our control (README)."""
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

from src.core.azure_clients import search_client, search_index_client
from src.core.config import get_settings
from src.core.logging import get_logger

log = get_logger("index_manager")


def ensure_index() -> None:
    """Create the index if missing (idempotent; safe to call on startup)."""
    settings = get_settings()
    index = SearchIndex(
        name=settings.search_index_name,
        fields=[
            SimpleField(name="chunk_id", type=SearchFieldDataType.String, key=True, filterable=True),
            SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SimpleField(name="doc_name", type=SearchFieldDataType.String, filterable=True,
                        facetable=True),
            SimpleField(name="doc_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SimpleField(name="page_start", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
            SimpleField(name="page_end", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
            SimpleField(name="synthetic_pages", type=SearchFieldDataType.Boolean, filterable=True),
            SearchableField(name="heading_path", type=SearchFieldDataType.String),
            SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="en.microsoft"),
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                stored=False,
                vector_search_dimensions=settings.embed_dimensions,
                vector_search_profile_name="vector-profile",
            ),
            SimpleField(name="upload_ts", type=SearchFieldDataType.DateTimeOffset,
                        filterable=True, sortable=True),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
            profiles=[VectorSearchProfile(name="vector-profile", algorithm_configuration_name="hnsw")],
        ),
    )
    existing = {idx for idx in search_index_client().list_index_names()}
    if settings.search_index_name not in existing:
        search_index_client().create_index(index)
        log.info("index_created", index=settings.search_index_name)


def upsert_chunks(documents: list[dict]) -> None:
    results = search_client().upload_documents(documents=documents)
    failed = [r.key for r in results if not r.succeeded]
    if failed:
        raise RuntimeError(f"Index upsert failed for {len(failed)} chunks: {failed[:5]}")
    log.info("chunks_indexed", count=len(documents))


def delete_document_chunks(doc_id: str) -> None:
    """Idempotent re-ingest support: remove a document's existing chunks."""
    client = search_client()
    results = client.search(search_text="*", filter=f"doc_id eq '{doc_id}'", select="chunk_id", top=1000)
    keys = [{"chunk_id": r["chunk_id"]} for r in results]
    if keys:
        client.delete_documents(documents=keys)
        log.info("chunks_deleted", doc_id=doc_id, count=len(keys))
