"""The RAG turn: plan → retrieve → self-grade → (corrective re-query) → gate →
generate. One correlation ID traces the whole turn through the logs.

Two execution shapes share the same pipeline:
- answer_question(): synchronous, returns the full ChatResponse.
- stream_answer(): generator yielding ('stage', payload) events for SSE so the
  UI can show an 'agentic trace' (planning → retrieving → grading → generating →
  done) in real time. Every intelligent step is still an Azure-AI call; the
  events are just observability over the same plan/retrieve/grade/generate pipeline."""
from collections.abc import Iterator
from typing import Any

import structlog

from src.core.config import get_settings
from src.core.logging import get_logger, new_correlation_id
from src.generation.answerer import generate_answer, stream_answer_tokens
from src.generation.schemas import ChatResponse, GroundedAnswer, SourceChunk
from src.retrieval.query_planner import QueryPlan, plan_query
from src.retrieval.retrieval_grader import grade_retrieval
from src.retrieval.searcher import RetrievedChunk, comparison_search, hybrid_search

log = get_logger("rag_service")


def _to_sources(chunks: list[RetrievedChunk]) -> list[SourceChunk]:
    return [SourceChunk(source_id=n, **vars(chunk)) for n, chunk in enumerate(chunks, start=1)]


def _retrieve(plan_intent: str, query: str) -> list[RetrievedChunk]:
    if plan_intent == "comparison":
        evidence = comparison_search(query)
        return [chunk for doc_chunks in evidence.values() for chunk in doc_chunks]
    return hybrid_search(query, top=get_settings().top_k)


def _merge(primary: list[RetrievedChunk], extra: list[RetrievedChunk], cap: int) -> list[RetrievedChunk]:
    """Union by chunk_id, highest hybrid score first, capped."""
    seen = {c.chunk_id for c in primary}
    merged = primary + [c for c in extra if c.chunk_id not in seen]
    merged.sort(key=lambda c: c.score, reverse=True)
    return merged[:cap]


def _retrieve_agentic(plan: QueryPlan):
    """Generator: retrieve → (self-grade → corrective re-query). Yields
    ('stage', payload) trace events, then ('chunks', list) as the final item.

    The grade step is an agentic decision implemented on raw Azure SDK calls.
    Comparison intent already fans out across every document, so grading is
    applied only to simple-intent turns. Disabled via AGENTIC_RAG=false."""
    settings = get_settings()
    chunks = _retrieve(plan.intent, plan.standalone_query)

    if not (settings.agentic_rag and plan.intent == "simple" and settings.agentic_max_retries > 0):
        yield "chunks", chunks
        return

    yield "grading", {"message": "Assessing whether the retrieved evidence answers the question…"}
    grade = grade_retrieval(plan.standalone_query, chunks)
    if grade.sufficient:
        yield "graded", {"sufficient": True, "reason": grade.reason}
        yield "chunks", chunks
        return

    # Corrective re-query: widen and merge so we never lose the first-pass hits.
    yield "refining", {"refined_query": grade.refined_query, "reason": grade.reason}
    extra = hybrid_search(grade.refined_query, top=settings.agentic_recall_k)
    before = len(chunks)
    chunks = _merge(chunks, extra, cap=settings.agentic_recall_k)
    log.info("agentic_requery", refined_query=grade.refined_query,
             added=len(chunks) - before, total=len(chunks))
    yield "graded", {"sufficient": False, "refined_query": grade.refined_query,
                     "added": max(0, len(chunks) - before), "chunk_count": len(chunks)}
    yield "chunks", chunks


def answer_question(session_id: str, question: str, history: list[dict]) -> ChatResponse:
    correlation_id = new_correlation_id("chat")
    structlog.contextvars.bind_contextvars(session_id=session_id, correlation_id=correlation_id)
    try:
        plan = plan_query(history, question)
        chunks: list[RetrievedChunk] = []
        for stage, payload in _retrieve_agentic(plan):
            if stage == "chunks":
                chunks = payload
        log.info("retrieved", count=len(chunks),
                 top_score=max((c.score for c in chunks), default=0.0))
        answer = generate_answer(question, history, chunks)
        if answer.insufficient_context:
            answer.citations = []
        return ChatResponse(
            session_id=session_id,
            standalone_query=plan.standalone_query,
            intent=plan.intent,
            answer=answer,
            sources=_to_sources(chunks),
        )
    finally:
        structlog.contextvars.clear_contextvars()


def stream_answer(session_id: str, question: str,
                  history: list[dict]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ('stage_name', payload) events for the UI's agentic trace.

    Stages: 'planning' → 'planned' → 'retrieving' → ['grading' → ('refining' →)
    'graded'] → 'retrieved' → 'generating' → 'token'* → 'done'. The grading
    stages appear only on agentic simple-intent turns. Each event is a typed
    dict; the API layer JSON-encodes them onto the SSE wire. Cancellation is
    cooperative via the consuming generator."""
    correlation_id = new_correlation_id("chat")
    structlog.contextvars.bind_contextvars(session_id=session_id, correlation_id=correlation_id)
    try:
        yield "planning", {"message": "Rewriting your question into a standalone query…"}
        plan = plan_query(history, question)
        yield "planned", {"standalone_query": plan.standalone_query, "intent": plan.intent}

        yield "retrieving", {
            "message": ("Fanning out across every uploaded document (comparison mode)…"
                        if plan.intent == "comparison"
                        else "Running hybrid search (BM25 + vector + RRF)…")
        }
        # Retrieve → agentically self-grade → corrective re-query if weak.
        # Non-'chunks' events are the live trace for the grading/refining steps.
        chunks: list[RetrievedChunk] = []
        for stage, payload in _retrieve_agentic(plan):
            if stage == "chunks":
                chunks = payload
            else:
                yield stage, payload
        log.info("retrieved", count=len(chunks),
                 top_score=max((c.score for c in chunks), default=0.0))
        yield "retrieved", {
            "chunk_count": len(chunks),
            "top_score": max((c.score for c in chunks), default=0.0),
            "documents": sorted({c.doc_name for c in chunks}),
        }

        yield "generating", {"message": "Grounding the answer in the retrieved sources…"}
        # Token-by-token streaming via OpenAI Structured-Outputs streaming.
        # The 'token' events let the UI render the answer as it's produced.
        final_answer: GroundedAnswer | None = None
        for event_type, payload in stream_answer_tokens(question, history, chunks):
            if event_type == "token":
                yield "token", {"delta": payload}
            elif event_type == "final":
                final_answer = payload  # type: ignore[assignment]
        assert final_answer is not None, "stream_answer_tokens must yield a 'final' event"
        if final_answer.insufficient_context:
            final_answer.citations = []

        response = ChatResponse(
            session_id=session_id,
            standalone_query=plan.standalone_query,
            intent=plan.intent,
            answer=final_answer,
            sources=_to_sources(chunks),
        )
        yield "done", response.model_dump()
    finally:
        structlog.contextvars.clear_contextvars()
