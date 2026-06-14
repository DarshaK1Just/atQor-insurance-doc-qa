"""Agentic retrieval self-grading + query correction (Corrective-RAG).

After the first hybrid search, an LLM judges whether the retrieved evidence can
actually answer the question. If not, it proposes a *refined* search query and
the RAG loop searches again (widened) before generating. That's a genuine
agentic decision — "is this enough, and if not, how do I search better?" —
implemented directly on the Azure OpenAI SDK, no orchestration framework.

Kimi-compatible: Structured Outputs when the deployment supports it, JSON mode
otherwise (shared capability cache). Any failure degrades to `sufficient=True`
so the loop can never block or slow down answer generation."""
import json

from pydantic import BaseModel, Field, ValidationError

from src.core.azure_clients import chat_client, chat_extra_kwargs, chat_model
from src.core.logging import get_logger
from src.core.model_caps import mark_unsupported, supports_structured_outputs
from src.retrieval.searcher import RetrievedChunk

log = get_logger("retrieval_grader")

_MAX_PREVIEW_CHARS = 320


class RetrievalGrade(BaseModel):
    sufficient: bool = Field(
        description="True if the numbered sources contain enough information to answer the question")
    refined_query: str | None = Field(
        default=None,
        description="If not sufficient, an improved search query (synonyms / broader / more specific); "
                    "otherwise echo the original query")
    reason: str = Field(default="", description="One short clause explaining the judgement")


_SYSTEM = (
    "You are the retrieval critic in a RAG pipeline for insurance documents. "
    "Given a search query and the snippets it retrieved, decide whether those snippets "
    "contain enough information to answer the query. If they do NOT, write a better search "
    "query (add synonyms, expand abbreviations, or broaden/narrow the focus) that is more likely "
    "to surface the right passages. Reply with ONLY a JSON object matching this schema: "
    '{"sufficient": bool, "refined_query": "...", "reason": "..."}'
)


def _previews(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no snippets were retrieved)"
    lines = []
    for n, c in enumerate(chunks, start=1):
        head = c.heading_path or c.doc_name
        body = " ".join(c.content.split())[:_MAX_PREVIEW_CHARS]
        lines.append(f"[{n}] {c.doc_name} — {head}: {body}")
    return "\n".join(lines)


def _messages(query: str, chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"QUERY: {query}\n\nRETRIEVED SNIPPETS:\n{_previews(chunks)}"},
    ]


def grade_retrieval(query: str, chunks: list[RetrievedChunk]) -> RetrievalGrade:
    """Judge retrieval sufficiency and propose a refined query. Never raises —
    on any error it returns `sufficient=True` so generation proceeds unblocked."""
    model = chat_model()
    messages = _messages(query, chunks)
    grade: RetrievalGrade | None = None

    if supports_structured_outputs():
        try:
            completion = chat_client().beta.chat.completions.parse(
                model=model, temperature=0, messages=messages, response_format=RetrievalGrade,
            )
            grade = completion.choices[0].message.parsed
        except Exception as exc:
            mark_unsupported()
            log.info("grader_structured_unsupported", error=type(exc).__name__)

    if grade is None:
        try:
            completion = chat_client().chat.completions.create(
                model=model, temperature=0, messages=messages,
                response_format={"type": "json_object"}, **chat_extra_kwargs(),
            )
            grade = RetrievalGrade.model_validate(json.loads(completion.choices[0].message.content or "{}"))
        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            log.warning("grader_failed_open", error=str(exc))
            return RetrievalGrade(sufficient=True, refined_query=query, reason="grader unavailable")

    # Never return an empty/null refined query (some models emit null for it).
    if not (grade.refined_query or "").strip():
        grade.refined_query = query
    log.info("retrieval_graded", sufficient=grade.sufficient, refined_query=grade.refined_query)
    return grade
