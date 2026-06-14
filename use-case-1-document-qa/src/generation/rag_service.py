"""The RAG turn: plan → retrieve → self-grade → (corrective re-query) → gate →
generate. One correlation ID traces the whole turn through the logs.

Two execution shapes share the same pipeline:
- answer_question(): synchronous, returns the full ChatResponse.
- stream_answer(): generator yielding ('stage', payload) events for SSE so the
  UI can show an 'agentic trace' (planning → retrieving → grading → generating →
  done) in real time. Every intelligent step is still an Azure-AI call; the
  events are just observability over the same plan/retrieve/grade/generate pipeline."""
import re
import time
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

# Greetings / thanks / "who are you" shouldn't trigger a document search (which
# would otherwise return an awkward "insufficient context"). We answer those
# conversationally and point the user at what the assistant can actually do.
_SMALLTALK_RE = re.compile(
    r"^[\s\W]*(hi+|hey+|hello+|heya|hiya|yo|hola|namaste|howdy|sup|"
    r"good\s*(morning|afternoon|evening|day)|greetings|"
    r"thanks?|thank\s*you|thx|ty|cheers|"
    r"ok(ay)?|cool|nice|great|awesome|got\s*it|"
    r"how\s*are\s*you|who\s*are\s*you|what\s*can\s*you\s*do|what\s*do\s*you\s*do|"
    r"help|bye|goodbye|see\s*you)[\s\W]*$",
    re.IGNORECASE,
)
_SMALLTALK_REPLY = (
    "Hello! I'm your **insurance document assistant**. I answer questions grounded "
    "only in your uploaded policies, claims and medical reports — and I cite the exact "
    "source page for every fact.\n\n"
    "Here are a few things you can ask me:\n"
    "- *What is the annual outpatient limit, deductible and co-payment under the Gold Shield policy?*\n"
    "- *Extract the claimant name, policy number and claimed amount from the CF-102 claim form.*\n"
    "- *Compare the deductibles and annual limits across all policies.*"
)


def _is_smalltalk(text: str) -> bool:
    t = (text or "").strip()
    return 0 < len(t) <= 40 and bool(_SMALLTALK_RE.match(t))


def _smalltalk_answer() -> GroundedAnswer:
    return GroundedAnswer(answer_markdown=_SMALLTALK_REPLY, citations=[],
                          insufficient_context=False, confidence="high")


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


# Comparison intent is cheap to detect from surface cues; on a first turn there
# are no pronouns to resolve, so we skip the planner LLM call entirely.
_COMPARISON_HINTS = (
    "compare", "comparison", "versus", " vs ", " vs.", "difference between",
    "differences between", "across all", "across the", "all policies", "all the policies",
    "each policy", "between the", "side by side", "which policy", "highest", "lowest",
)


# Extraction / summarisation verbs signal that the question text itself is NOT a
# good search query — the planner must condense it to a short keyword phrase.
_NEEDS_PLANNING_RE = re.compile(
    r"\b(extract|summaris[ez]|describe|list the|give me|provide me|break down|"
    r"calculate|eligib|verify|check if|out-of-pocket|walk me|overview of)\b",
    re.IGNORECASE,
)


def _plan(history: list[dict], question: str) -> QueryPlan:
    """Resolve the question to a standalone query + intent.

    PERF: with no prior turn there's nothing to coreference, so we skip the
    planner's LLM round-trip and route intent with keywords — but ONLY for
    short, direct questions. Long or extraction-style questions send a bad
    embedding vector to the index and must be condensed by the planner first."""
    if not history and len(question) <= 120 and not _NEEDS_PLANNING_RE.search(question):
        q = f" {question.lower()} "
        intent = "comparison" if any(h in q for h in _COMPARISON_HINTS) else "simple"
        return QueryPlan(standalone_query=question.strip(), intent=intent)
    return plan_query(history, question)


def _retrieve_agentic(plan: QueryPlan):
    """Generator: retrieve → (self-grade → corrective re-query). Yields
    ('stage', payload) trace events, then ('chunks', list) as the final item.

    The 'grading'/'graded' pair is ALWAYS emitted so the UI shows a stable
    four-step reasoning timeline. PERF: the LLM critic itself runs only on a
    simple-intent turn whose first-pass retrieval is THIN
    (< agentic_grade_when_chunks_below). Strong retrievals — the common case —
    pass an instant local check with no extra round-trip. Disabled via AGENTIC_RAG=false."""
    settings = get_settings()
    chunks = _retrieve(plan.intent, plan.standalone_query)

    # Emit the search summary first so the UI's four steps light up strictly
    # top-to-bottom (search → verify), then the evidence-check step.
    yield "retrieved", {
        "chunk_count": len(chunks),
        "top_score": max((c.score for c in chunks), default=0.0),
        "documents": sorted({c.doc_name for c in chunks}),
    }
    yield "grading", {"message": "Checking the retrieved passages cover the question…"}
    weak = plan.intent == "simple" and len(chunks) < settings.agentic_grade_when_chunks_below
    if not (settings.agentic_rag and settings.agentic_max_retries > 0 and weak):
        reason = (f"{len(chunks)} passages across the corpus" if plan.intent == "comparison"
                  else f"strong match · {len(chunks)} passages")
        yield "graded", {"sufficient": True, "reason": reason}
        yield "chunks", chunks
        return

    # Thin retrieval → spend one LLM call to critique + propose a better query.
    grade = grade_retrieval(plan.standalone_query, chunks)
    if grade.sufficient:
        yield "graded", {"sufficient": True, "reason": grade.reason or "evidence sufficient"}
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
        if _is_smalltalk(question):
            return ChatResponse(session_id=session_id, standalone_query=question,
                                intent="chitchat", answer=_smalltalk_answer(), sources=[])
        plan = _plan(history, question)
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
        # Greeting / small-talk: reply conversationally, no retrieval, no trace.
        if _is_smalltalk(question):
            yield "planned", {"standalone_query": question, "intent": "chitchat"}
            yield "generating", {"message": "Replying…"}
            yield "token", {"delta": _SMALLTALK_REPLY}
            resp = ChatResponse(session_id=session_id, standalone_query=question,
                                intent="chitchat", answer=_smalltalk_answer(), sources=[])
            yield "done", resp.model_dump()
            return

        _t0 = time.perf_counter()
        yield "planning", {"message": "Rewriting your question into a standalone query…"}
        plan = _plan(history, question)
        yield "planned", {"standalone_query": plan.standalone_query, "intent": plan.intent}

        yield "retrieving", {
            "message": ("Fanning out across every uploaded document (comparison mode)…"
                        if plan.intent == "comparison"
                        else "Running hybrid search (BM25 + vector + RRF)…")
        }
        # Retrieve → agentically self-grade → corrective re-query if weak.
        # Non-'chunks' events are the live trace for the grading/refining steps.
        # The generator now emits 'retrieved' (search summary) itself, before the
        # grading events, so the trace lights up strictly top-to-bottom.
        _t_plan = time.perf_counter()
        chunks: list[RetrievedChunk] = []
        for stage, payload in _retrieve_agentic(plan):
            if stage == "chunks":
                chunks = payload
            else:
                yield stage, payload
        _t_ret = time.perf_counter()
        log.info("retrieved", count=len(chunks),
                 top_score=max((c.score for c in chunks), default=0.0))

        yield "generating", {"message": "Grounding the answer in the retrieved sources…"}
        # Token-by-token streaming via OpenAI Structured-Outputs streaming.
        # The 'token' events let the UI render the answer as it's produced.
        final_answer: GroundedAnswer | None = None
        for event_type, payload in stream_answer_tokens(question, history, chunks):
            if event_type == "token":
                yield "token", {"delta": payload}
            elif event_type == "final":
                final_answer = payload  # type: ignore[assignment]
        # Per-stage timing so latency is attributable at a glance in the backend
        # console: plan_ms (LLM rewrite; ~0 on a first turn) · retrieve_ms (query
        # embedding + Azure Search — a cold embedding deployment shows up HERE) ·
        # generate_ms (Gemini token stream).
        log.info("turn_timing", intent=plan.intent,
                 plan_ms=int((_t_plan - _t0) * 1000),
                 retrieve_ms=int((_t_ret - _t_plan) * 1000),
                 generate_ms=int((time.perf_counter() - _t_ret) * 1000))
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
