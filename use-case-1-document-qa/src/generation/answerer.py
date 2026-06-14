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
import re
from collections.abc import Iterator

from pydantic import ValidationError

from src.core.azure_clients import chat_client, chat_extra_kwargs, chat_model
from src.core.config import get_settings
from src.core.logging import get_logger
from src.core.model_caps import mark_unsupported, supports_structured_outputs
from src.generation.schemas import Citation, GroundedAnswer
from src.retrieval.searcher import RetrievedChunk

log = get_logger("answerer")

# Shared answer-quality contract — a direct answer first, then full structured
# detail, tables where they help, every fact cited. Used verbatim by both the
# structured-output prompt and the plain-streaming prompt so answers are
# consistently thorough regardless of which model path serves the turn.
_ANSWER_RULES = """GROUND TRUTH (non-negotiable)
- Use ONLY the numbered SOURCES below. Never use outside knowledge, training data, or assumptions.
- Put the source id in square brackets immediately after EVERY fact, e.g. [1] or [2][3]. Never write [1,3].
- Quote figures exactly as written — amounts, percentages, dates, ICD codes, clause/section numbers, sub-limits.
- When a value is genuinely absent from ALL sources, write exactly "Not documented" — WITHOUT a citation. Never invent a number.
- If the sources only partially answer, answer what they DO support, then state precisely what is missing.

━━━ ADAPT YOUR STRUCTURE TO THE QUESTION TYPE ━━━

◆ SUMMARISATION ("summarise", "describe", "give me an overview of", "what does the … say"):
  Do NOT lead with a single sentence — the structured extraction IS the answer.
  For medical reports extract ALL of: Patient name & MRN, Admission date, Discharge date, Length of stay,
  Primary diagnosis with ICD code, Secondary diagnoses, Procedure(s) performed (state "None documented" if absent),
  Attending physician, Discharge condition, Discharge medications, Follow-up instructions.
  For policy documents extract: effective date, insured parties, all benefit sections present, key limits.
  Organise as a "Field | Value [citation]" table — one row per field, cited per row.

◆ ELIGIBILITY / CLAIM CHECK ("is this eligible", "does this cover", "check if", "verify", "approve/deny"):
  Structure as four blocks:
  1. **Verdict** in bold (Eligible / Likely Eligible / Ineligible / Requires Investigation)
  2. Relevant policy terms (quoted exactly, cited)
  3. Claim data vs policy terms — line by line
  4. Out-of-pocket calculation if applicable: deductible → remaining balance → co-insurance → member liability
  5. Flags: anything that needs manual review or additional documents

◆ FIELD EXTRACTION ("list the", "extract", "what is the X and Y and Z from"):
  Return a two-column "Field | Value [citation]" table using the EXACT field names the user requested
  — in the ORDER they were asked — never rename, rephrase, or reorder them.
  After the table add a "Notes" row for any operationally relevant adjacent context.

◆ POLICY COVERAGE ("what is the limit / deductible / co-pay / benefit / coverage for"):
  1. One-sentence direct answer with headline figures in **bold**.
  2. Compact table of all figures (limit, deductible, co-pay/co-insurance, sub-limits).
  3. **Operational notes** (always include): waiting periods, in-network vs out-of-network differences,
     what triggers or waives the co-pay, per-incident vs annual caps, relevant exclusions.
     This section prevents claims errors — never omit it.

◆ COMPARISON ("compare", "difference between", "which is better", "across all policies"):
  One table: one row per plan/document, one column per dimension asked about. Cite per cell.
  Compare ONLY the dimensions the user asked for.
  Close with a 2–3 sentence synthesis naming the most material differences and the practical implication.

━━━ STYLE ━━━
- Write for insurance operations staff who need defensible, audit-ready answers.
- Precise, professional, thorough — no filler, no preamble, no restating the question.
- **Bold** headline numbers, verdicts, and key thresholds. Tables over prose for ≥3 values.
- Keep paragraphs short. Bullets for lists of conditions, exclusions, or steps."""

_SYSTEM = f"""You are a senior insurance analyst assisting operations staff. Answer the user's question using ONLY the numbered sources below.

{_ANSWER_RULES}

For the structured fields: set insufficient_context=true only when the sources cannot answer; include one citation per source you actually used (short verbatim quote + the page number shown in that source's header).

Reply with ONLY a JSON object matching this schema:
{{
  "answer_markdown": "...",
  "citations": [{{"source_id": int, "doc_name": str, "page": int, "quote": str}}],
  "insufficient_context": bool,
  "confidence": "high" | "medium" | "low"
}}
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
    model = chat_model()
    max_tok = settings.max_answer_tokens or None

    # 1. Try Structured Outputs (preferred) — skipped if the deployment is known
    #    not to support it (see model_caps), avoiding a wasted round-trip.
    answer = None
    if supports_structured_outputs():
        try:
            completion = chat_client().beta.chat.completions.parse(
                model=model, temperature=0.1, messages=messages,
                response_format=GroundedAnswer,
                **({"max_tokens": max_tok} if max_tok else {}),
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
            completion = chat_client().chat.completions.create(
                model=model, temperature=0.1, messages=messages,
                response_format={"type": "json_object"},
                **({"max_tokens": max_tok} if max_tok else {}),
                **chat_extra_kwargs(),
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
    model = chat_model()
    max_tok = settings.max_answer_tokens or None

    # 1. Try Structured-Outputs streaming. Partial parsed objects arrive as the
    #    model emits JSON tokens; we forward `answer_markdown` deltas to the UI.
    #    Skipped entirely once the deployment is known not to support it.
    if supports_structured_outputs():
        try:
            with chat_client().beta.chat.completions.stream(
                model=model, temperature=0.1, messages=messages,
                response_format=GroundedAnswer,
                **({"max_tokens": max_tok} if max_tok else {}),
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


_PLAIN_SYSTEM = f"""You are a senior insurance analyst assisting operations staff. Answer the user's question using ONLY the numbered SOURCES provided.

{_ANSWER_RULES}

Write clean Markdown prose and tables — do NOT output JSON.
"""

# Citation markers like [1], [2][3]. We map these to the retrieved chunks in
# Python — no second LLM call — so pages and quotes are accurate by construction.
_MARKER_RE = re.compile(r"\[(\d+)\]")
_INSUFFICIENT_HINTS = (
    "don't have enough", "do not have enough", "not contain", "cannot answer",
    "can't answer", "no information", "insufficient", "unable to answer",
    "not enough information", "isn't enough", "is not enough",
)


def _snippet(text: str, limit: int = 240) -> str:
    """A short verbatim lead snippet from a chunk, trimmed on a sentence boundary."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    dot = cut.rfind(". ")
    return (cut[: dot + 1] if dot > 80 else cut).rstrip() + "…"


def _citations_from_markers(answer_text: str, chunks: list[RetrievedChunk]) -> list[Citation]:
    """Build one citation per distinct [n] marker the model actually used, in
    order of first appearance. Page + quote come from the chunk metadata."""
    out: list[Citation] = []
    seen: set[int] = set()
    for m in _MARKER_RE.finditer(answer_text):
        n = int(m.group(1))
        if n in seen or not (1 <= n <= len(chunks)):
            continue
        seen.add(n)
        c = chunks[n - 1]
        out.append(Citation(source_id=n, doc_name=c.doc_name,
                            page=c.page_start, quote=_snippet(c.content)))
    return out


def _confidence(n_cited: int, insufficient: bool) -> str:
    if insufficient:
        return "low"
    return "high" if n_cited >= 2 else ("medium" if n_cited == 1 else "low")


def _stream_with_extract_fallback(question: str, history: list[dict],
                                  chunks: list[RetrievedChunk]) -> Iterator[tuple[str, object]]:
    model = chat_model()
    max_tok = get_settings().max_answer_tokens or None

    messages = [{"role": "system", "content": _PLAIN_SYSTEM}]
    for turn in history[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({
        "role": "user",
        "content": f"SOURCES:\n\n{_format_sources(chunks)}\n\nQUESTION: {question}",
    })

    # Pass 1: stream the plain markdown answer token-by-token.
    answer_text = ""
    try:
        stream = chat_client().chat.completions.create(
            model=model, temperature=0.1, messages=messages, stream=True,
            **({"max_tokens": max_tok} if max_tok else {}),
            **chat_extra_kwargs(),
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

    # Pass 2 is now PURE PYTHON — map [n] markers to the retrieved chunks. This
    # removes the second LLM round-trip that doubled answer latency, and yields
    # more accurate citations (real pages/quotes, not model-guessed ones).
    insufficient = (not answer_text.strip()) or any(
        h in answer_text.lower() for h in _INSUFFICIENT_HINTS)
    citations = [] if insufficient else _citations_from_markers(answer_text, chunks)
    answer = GroundedAnswer(
        answer_markdown=answer_text or _REFUSAL.answer_markdown,
        citations=citations,
        insufficient_context=insufficient,
        confidence=_confidence(len(citations), insufficient),
    )
    yield "final", _validate(answer, len(chunks))
