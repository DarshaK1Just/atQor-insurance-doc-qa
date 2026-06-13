"""Grounded answer generation.

Two execution shapes share the same prompt/schema:
- generate_answer()        — synchronous, returns a finished GroundedAnswer.
- stream_answer_tokens()   — async-style generator yielding token deltas as the
                             model produces them, then the final parsed answer.

Hallucination defence, free-tier edition (no semantic reranker on Free Search):
1. Hybrid BM25+vector+RRF maximises the chance the truth is in context.
2. Pre-gate: zero results / RRF floor → refuse before spending answer tokens.
3. Prompt: answer ONLY from numbered sources, cite every fact as [n], say so
   when sources are insufficient. Temperature 0.1.
4. Schema gate: the model itself judges `insufficient_context` — an LLM
   groundedness self-assessment, returned as a typed field, not parsed prose.

Two model strategies, auto-selected:
- Models supporting Structured Outputs (gpt-4o family) → schema-enforced parse
  WITH partial-object streaming so `answer_markdown` deltas arrive token-by-token.
- Other deployments (e.g. Kimi-k2.6) → JSON-mode + manual parse on completion."""
import json
from collections.abc import Iterator

from pydantic import ValidationError

from src.core.azure_clients import openai_client
from src.core.config import get_settings
from src.core.logging import get_logger
from src.core.model_caps import mark_unsupported, supports_structured_outputs
from src.generation.schemas import GroundedAnswer
from src.retrieval.searcher import RetrievedChunk

log = get_logger("answerer")

_SYSTEM = """You are an insurance document assistant for internal operations staff.
Answer the user's question using ONLY the numbered sources below. Rules:
- Every factual statement MUST carry the id of its source in square brackets, e.g. [1] or [2][3]. Never combine ids like [1,3].
- Quote exact figures (amounts, percentages, dates, clause numbers) verbatim from the sources.
- If the sources do not contain enough information to answer, set insufficient_context=true and say so plainly in answer_markdown. Do NOT use outside knowledge. Do NOT guess.
- For comparison questions, answer with a markdown table comparing each document, citing per cell.
- In the citations array, include one entry per source you actually used, with a short verbatim quote and the page number shown in that source's header.

Reply with ONLY a JSON object matching this schema:
{
  "answer_markdown": "...",
  "citations": [{"source_id": int, "doc_name": str, "page": int, "quote": str}],
  "insufficient_context": bool,
  "confidence": "high" | "medium" | "low"
}
"""

_REFUSAL = GroundedAnswer(
    answer_markdown=("I don't have enough information in the uploaded documents to answer that. "
                     "Try uploading the relevant document or rephrasing the question."),
    citations=[], insufficient_context=True, confidence="low",
)


def _format_sources(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for n, chunk in enumerate(chunks, start=1):
        page = (f"section '{chunk.heading_path}'" if chunk.synthetic_pages
                else f"page {chunk.page_start}" + (f"-{chunk.page_end}" if chunk.page_end != chunk.page_start else ""))
        blocks.append(f"[{n}] {chunk.doc_name} ({chunk.doc_type}), {page}\n{chunk.content}")
    return "\n\n---\n\n".join(blocks)


def _build_messages(question: str, history: list[dict], chunks: list[RetrievedChunk]) -> list[dict]:
    messages = [{"role": "system", "content": _SYSTEM}]
    for turn in history[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({
        "role": "user",
        "content": f"SOURCES:\n\n{_format_sources(chunks)}\n\nQUESTION: {question}",
    })
    return messages


def _validate(answer: GroundedAnswer | None, n_chunks: int) -> GroundedAnswer:
    if answer is None:
        return _REFUSAL.model_copy()
    # Defensive: drop citations pointing at sources that were not provided.
    answer.citations = [c for c in answer.citations if 1 <= c.source_id <= n_chunks]
    return answer


# ── synchronous path ──────────────────────────────────────────────────────────
def generate_answer(question: str, history: list[dict],
                    chunks: list[RetrievedChunk]) -> GroundedAnswer:
    settings = get_settings()
    if not chunks or max(c.score for c in chunks) < settings.rrf_floor:
        log.info("refused_pre_generation", reason="no_relevant_chunks")
        return _REFUSAL.model_copy()

    messages = _build_messages(question, history, chunks)
    model = settings.azure_openai_chat_deployment

    # 1. Try Structured Outputs (preferred) — skipped if the deployment is known
    #    not to support it (see model_caps), avoiding a wasted round-trip.
    answer = None
    if supports_structured_outputs():
        try:
            completion = openai_client().beta.chat.completions.parse(
                model=model, temperature=0.1, messages=messages, response_format=GroundedAnswer,
            )
            answer = completion.choices[0].message.parsed
        except Exception as exc:
            mark_unsupported()
            log.info("structured_outputs_unsupported", error=type(exc).__name__,
                     hint="Falling back to JSON-mode for grounded answer.")
            answer = None

    # 2. Fallback: JSON-mode + manual parse.
    if answer is None:
        try:
            completion = openai_client().chat.completions.create(
                model=model, temperature=0.1, messages=messages,
                response_format={"type": "json_object"},
            )
            raw = completion.choices[0].message.content or "{}"
            answer = GroundedAnswer.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            log.warning("json_mode_parse_failed", error=str(exc))
            answer = None

    answer = _validate(answer, len(chunks))
    log.info("answer_generated", insufficient=answer.insufficient_context,
             confidence=answer.confidence, citations=len(answer.citations))
    return answer


# ── streaming path ────────────────────────────────────────────────────────────
def stream_answer_tokens(question: str, history: list[dict],
                         chunks: list[RetrievedChunk]) -> Iterator[tuple[str, object]]:
    """Yield ('token', delta_str) events as the model emits answer_markdown
    tokens, then ('final', GroundedAnswer) when complete. Falls back to a
    single 'final' event on JSON-mode models (no incremental parsing there)."""
    settings = get_settings()
    if not chunks or max(c.score for c in chunks) < settings.rrf_floor:
        log.info("refused_pre_generation", reason="no_relevant_chunks")
        yield "final", _REFUSAL.model_copy()
        return

    messages = _build_messages(question, history, chunks)
    model = settings.azure_openai_chat_deployment

    # 1. Try Structured-Outputs streaming. Partial parsed objects arrive as the
    #    model emits JSON tokens; we forward `answer_markdown` deltas to the UI.
    #    Skipped entirely once the deployment is known not to support it.
    if supports_structured_outputs():
        try:
            with openai_client().beta.chat.completions.stream(
                model=model, temperature=0.1, messages=messages, response_format=GroundedAnswer,
            ) as stream:
                previous = ""
                for event in stream:
                    etype = getattr(event, "type", "")
                    # OpenAI Python SDK 1.40+ emits 'content.delta' with .snapshot=GroundedAnswer
                    if etype == "content.delta":
                        snapshot = getattr(event, "snapshot", None)
                        if snapshot is None:
                            continue
                        current = getattr(snapshot, "answer_markdown", "") or ""
                        if len(current) > len(previous):
                            yield "token", current[len(previous):]
                            previous = current
                final = stream.get_final_completion().choices[0].message.parsed
                yield "final", _validate(final, len(chunks))
                return
        except Exception as exc:
            mark_unsupported()
            log.info("structured_streaming_unsupported", error=type(exc).__name__,
                     hint="Falling back to non-streaming JSON-mode answer.")

    # 2. Fallback path (Kimi-k2.6 etc.): TWO-CALL streaming.
    #    a) Stream a plain-text answer (with [n] citation markers) token-by-token.
    #    b) Run a tiny JSON-mode follow-up to extract structured Citations.
    #    This keeps real per-token streaming for the user even when Structured
    #    Outputs streaming isn't supported by the deployment.
    yield from _stream_with_extract_fallback(question, history, chunks)


_PLAIN_SYSTEM = """You are an insurance document assistant for internal operations staff.
Answer the user's question using ONLY the numbered sources below. Rules:
- Every factual statement MUST carry the id of its source in square brackets, e.g. [1] or [2][3].
- Quote exact figures (amounts, percentages, dates, clause numbers) verbatim from the sources.
- If the sources do not contain enough information to answer, say so plainly — DO NOT guess.
- For comparison questions, answer with a markdown table comparing each document, citing per cell.
- Write naturally as prose/markdown — do NOT output JSON.
"""

_EXTRACT_SYSTEM = """You convert a grounded answer + its sources into a JSON object with this shape:
{
  "citations": [{"source_id": int, "doc_name": str, "page": int, "quote": str}],
  "insufficient_context": bool,
  "confidence": "high" | "medium" | "low"
}
- One citation per [n] marker actually used in the answer.
- 'quote' = a short verbatim snippet from that source supporting the answer (under 200 chars).
- 'page' = the page number printed in that source's header.
- 'insufficient_context' = true if the answer says it cannot answer.
Reply with ONLY the JSON object.
"""


def _stream_with_extract_fallback(question: str, history: list[dict],
                                  chunks: list[RetrievedChunk]) -> Iterator[tuple[str, object]]:
    settings = get_settings()
    model = settings.azure_openai_chat_deployment

    messages = [{"role": "system", "content": _PLAIN_SYSTEM}]
    for turn in history[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({
        "role": "user",
        "content": f"SOURCES:\n\n{_format_sources(chunks)}\n\nQUESTION: {question}",
    })

    # Pass 1: stream plain markdown answer
    answer_text = ""
    try:
        stream = openai_client().chat.completions.create(
            model=model, temperature=0.1, messages=messages, stream=True,
        )
        for chunk_evt in stream:
            if not chunk_evt.choices:
                continue
            delta = chunk_evt.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                answer_text += piece
                yield "token", piece
    except Exception as exc:
        log.warning("plain_streaming_failed", error=str(exc))
        # Fully synchronous last-resort path:
        answer = generate_answer(question, history, chunks)
        yield "final", answer
        return

    # Pass 2: tiny structured extract (citations, insufficient_context, confidence)
    sources_block = _format_sources(chunks)
    try:
        extract_resp = openai_client().chat.completions.create(
            model=model, temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": f"ANSWER:\n{answer_text}\n\nSOURCES:\n{sources_block}"},
            ],
        )
        raw = extract_resp.choices[0].message.content or "{}"
        extracted = json.loads(raw)
        answer = GroundedAnswer(
            answer_markdown=answer_text,
            citations=extracted.get("citations") or [],
            insufficient_context=bool(extracted.get("insufficient_context", False)),
            confidence=extracted.get("confidence") or "medium",
        )
    except Exception as exc:
        log.warning("citation_extract_failed", error=str(exc))
        answer = GroundedAnswer(
            answer_markdown=answer_text, citations=[],
            insufficient_context=False, confidence="medium",
        )

    yield "final", _validate(answer, len(chunks))
