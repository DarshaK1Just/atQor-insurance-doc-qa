"""The RAG turn: plan → retrieve (simple or comparison fan-out) → gate →
generate. One correlation ID traces the whole turn through the logs.

Two execution shapes share the same pipeline:
- answer_question(): synchronous, returns the full ChatResponse.
- stream_answer(): generator yielding ('stage', payload) events for SSE so the
  UI can show an 'agentic trace' (planning → retrieving → generating → done)
  in real time. Every intelligent step is still an Azure-AI call; the events
  are just observability over the same plan/retrieve/generate pipeline."""
from collections.abc import Iterator
from typing import Any

import structlog

from src.core.config import get_settings
from src.core.logging import get_logger, new_correlation_id
from src.generation.answerer import generate_answer, stream_answer_tokens
from src.generation.schemas import ChatResponse, GroundedAnswer, SourceChunk
from src.retrieval.query_planner import plan_query
from src.retrieval.searcher import RetrievedChunk, comparison_search, hybrid_search

log = get_logger("rag_service")


def _to_sources(chunks: list[RetrievedChunk]) -> list[SourceChunk]:
    return [SourceChunk(source_id=n, **vars(chunk)) for n, chunk in enumerate(chunks, start=1)]


def _retrieve(plan_intent: str, query: str) -> list[RetrievedChunk]:
    if plan_intent == "comparison":
        evidence = comparison_search(query)
        return [chunk for doc_chunks in evidence.values() for chunk in doc_chunks]
    return hybrid_search(query, top=get_settings().top_k)


def answer_question(session_id: str, question: str, history: list[dict]) -> ChatResponse:
    correlation_id = new_correlation_id("chat")
    structlog.contextvars.bind_contextvars(session_id=session_id, correlation_id=correlation_id)
    try:
        plan = plan_query(history, question)
        chunks = _retrieve(plan.intent, plan.standalone_query)
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

    Stages: 'planning' → 'planned' → 'retrieving' → 'retrieved' → 'generating'
    → 'done'. Each event is a typed dict; the API layer JSON-encodes them onto
    the SSE wire. Cancellation is cooperative via the consuming generator."""
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
        chunks = _retrieve(plan.intent, plan.standalone_query)
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
