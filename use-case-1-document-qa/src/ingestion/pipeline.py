"""Ingestion pipeline orchestrator: upload → extract → classify → chunk →
embed → index, with per-stage status updates and a correlation ID through every
log line. Runs as a FastAPI background task; the IngestionPipeline interface is
the seam where a queue-backed implementation slots in at production scale."""
from datetime import datetime, timezone
from pathlib import Path

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.azure_clients import openai_client
from src.core.config import get_settings
from src.core.logging import get_logger, new_correlation_id
from src.indexing.chunker import chunk_markdown
from src.indexing.embedder import embed_texts
from src.indexing.index_manager import delete_document_chunks, upsert_chunks
from src.indexing.page_mapper import PageMapper
from src.ingestion.blob_store import blob_store
from src.ingestion.extractor import ExtractionError, extract_document
from src.ingestion.status_store import status_store

log = get_logger("pipeline")

_DOC_TYPES = ("policy", "claim_form", "medical_report", "other")


@retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3), reraise=True)
def _llm_classify(content: str) -> str:
    """JSON-mode classification. Same prompt for any deployment; the response_format
    forces the model to emit {"label": "..."} which we parse robustly."""
    import json as _json
    settings = get_settings()
    system = (
        "You classify the PRIMARY PURPOSE of an insurance-related document. "
        "Pick exactly ONE label from this set: " + ", ".join(_DOC_TYPES) + ".\n\n"
        "Disambiguation rules — apply in this order:\n"
        "1. If the document is a CLINICAL NARRATIVE written by a healthcare provider "
        "(discharge summary, hospital report, lab result, doctor's notes, radiology "
        "report) → 'medical_report'. Indicators: hospital/clinic letterhead, patient "
        "demographics, 'Diagnosis', 'Clinical Course', 'Procedures', signed by an "
        "MD/physician. Note: medical reports OFTEN mention insurance or claims in a "
        "billing note — that does NOT make them claim forms.\n"
        "2. If the document is a STANDARD INSURANCE FORM submitted by a claimant to "
        "request reimbursement (typically called 'Claim Form', 'CF-' prefix, with "
        "fields for claimant name, policy number, claim amount, date of service, "
        "claimant signature) → 'claim_form'.\n"
        "3. If the document is a BINDING POLICY CONTRACT issued by an insurer "
        "defining coverage (declarations page, schedule of benefits, exclusions, "
        "premium, signed by an officer of the insurer) → 'policy'.\n"
        "4. Otherwise → 'other'.\n\n"
        "Reply with ONLY a JSON object of the form: {\"label\": \"medical_report\"}."
    )
    response = openai_client().chat.completions.create(
        model=settings.azure_openai_chat_deployment,
        temperature=0,
        max_tokens=60,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content[:2500]},
        ],
    )
    raw = (response.choices[0].message.content or "{}").strip()
    try:
        label = (_json.loads(raw).get("label") or "").strip().lower()
    except _json.JSONDecodeError:
        label = raw.lower()
    if label in _DOC_TYPES:
        return label
    # Some models prefix with extra prose; salvage by substring match.
    for candidate in _DOC_TYPES:
        if candidate in label:
            return candidate
    return _classify_via_keywords(content)


def _classify_doc_type(content: str) -> str:
    """LLM document-type classification at ingest (no filename heuristics).
    Retries transient OpenAI failures; only falls back to 'other' after exhaustion.

    JSON-mode is used (not bare text) so non-OpenAI deployments like Kimi-k2.6
    on Azure AI Foundry — which often ignore 'reply with the label only'
    instructions and emit a sentence — give us a parseable answer."""
    try:
        return _llm_classify(content)
    except Exception as exc:
        log.warning("classification_failed_after_retries", error=str(exc))
        return "other"


def _classify_via_keywords(content: str) -> str:
    """Last-resort hint based on document structure. Only used when JSON parse
    fails entirely — i.e. the LLM produced something we couldn't read.

    Order matters: medical reports often mention 'claim' in a billing note, so
    we look for clinical-narrative signals BEFORE claim-form signals."""
    head = content[:3000].lower()
    medical_signals = ("discharge summary", "clinical course", "attending physician",
                       "medical center", "diagnosis", "post-operative")
    if sum(1 for s in medical_signals if s in head) >= 2:
        return "medical_report"
    if ("claim form" in head or "cf-102" in head
            or "claim amount" in head and "claimant" in head):
        return "claim_form"
    if "policy" in head and ("deductible" in head or "schedule of benefits" in head
                              or "exclusions" in head):
        return "policy"
    return "other"


def process_document(doc_id: str, path: Path) -> None:
    """Full pipeline for one document. Designed to be idempotent per doc_id."""
    correlation_id = new_correlation_id("ingest")
    structlog.contextvars.bind_contextvars(doc_id=doc_id, correlation_id=correlation_id)
    try:
        status_store.update(doc_id, "extracting")
        blob_store.upload_original(doc_id, path)
        extraction = extract_document(path, correlation_id)
        blob_store.upload_extract(doc_id, extraction.content)
        (get_settings().data_dir / "extracts" / f"{doc_id}.md").write_text(
            extraction.content, encoding="utf-8")

        status_store.update(doc_id, "classifying", pages=extraction.page_count)
        doc_type = _classify_doc_type(extraction.content)

        status_store.update(doc_id, "chunking", doc_type=doc_type)
        chunks = chunk_markdown(extraction.content)
        if not chunks:
            raise ExtractionError("No extractable text found (empty OCR result).")
        mapper = PageMapper(extraction.page_spans)

        status_store.update(doc_id, "indexing", chunks=len(chunks))
        vectors = embed_texts([c.text for c in chunks])
        upload_ts = datetime.now(timezone.utc).isoformat()
        # IMPORTANT: use the ORIGINAL upload name (preserved by status_store),
        # not the on-disk filename (which is the doc_id + ext). Without this,
        # citations and comparison fan-out group by opaque IDs instead of
        # friendly document names.
        record = status_store.get(doc_id) or {}
        doc_name = record.get("doc_name") or path.name
        delete_document_chunks(doc_id)
        documents = []
        for n, (chunk, vector) in enumerate(zip(chunks, vectors)):
            page_start, page_end = mapper.page_range(chunk.start_offset, chunk.end_offset)
            documents.append({
                "chunk_id": f"{doc_id}-c{n:04d}",
                "doc_id": doc_id,
                "doc_name": doc_name,
                "doc_type": doc_type,
                "page_start": page_start,
                "page_end": page_end,
                "synthetic_pages": extraction.synthetic_pages,
                "heading_path": chunk.heading_path,
                "content": chunk.text,
                "content_vector": vector,
                "upload_ts": upload_ts,
            })
        upsert_chunks(documents)
        status_store.update(doc_id, "ready", chunks=len(chunks))
        log.info("ingestion_complete", chunks=len(chunks), pages=extraction.page_count)
    except Exception as exc:
        log.error("ingestion_failed", error=str(exc))
        status_store.update(doc_id, "failed", detail=str(exc))
    finally:
        structlog.contextvars.clear_contextvars()
