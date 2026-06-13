"""Query planning — one structured-output LLM call that does two jobs:
1. Multi-turn coreference resolution: condense (chat history + new question)
   into a standalone search query ("the deductible for that same policy" →
   "deductible for Gold Shield Health Policy").
2. Intent routing: simple retrieval vs multi-document comparison fan-out.

Two model strategies, auto-selected:
- Azure OpenAI gpt-4o / gpt-4o-mini → Structured Outputs (response_format=schema)
- Other deployments (e.g. Kimi-k2.6 served via Azure AI Foundry serverless) →
  JSON-mode prompt + manual validation against the same Pydantic schema.
Either way the LLM does the contextualization — no pronoun regexes in Python."""
import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from src.core.azure_clients import openai_client
from src.core.config import get_settings
from src.core.logging import get_logger

log = get_logger("query_planner")


class QueryPlan(BaseModel):
    standalone_query: str = Field(description="Self-contained search query with all references resolved")
    intent: Literal["simple", "comparison"] = Field(
        description="'comparison' only when the user asks to compare/contrast across multiple documents")


_SYSTEM = (
    "You rewrite the user's latest question into a standalone search query for an "
    "insurance document index, resolving pronouns and references using the conversation. "
    "Set intent='comparison' ONLY if the question asks to compare or aggregate across "
    "multiple documents/policies (e.g. 'compare deductibles across all policies'). "
    "Otherwise intent='simple'. Reply with ONLY a JSON object matching this schema: "
    '{"standalone_query": "...", "intent": "simple" | "comparison"}'
)


def _build_messages(history: list[dict], question: str) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": _SYSTEM}]
    for turn in history[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})
    return messages


def _try_structured(messages: list[dict], model: str) -> QueryPlan | None:
    """Preferred path: Azure OpenAI Structured Outputs (zero parsing)."""
    try:
        completion = openai_client().beta.chat.completions.parse(
            model=model, temperature=0, messages=messages, response_format=QueryPlan,
        )
        return completion.choices[0].message.parsed
    except Exception as exc:
        log.info("structured_outputs_unsupported", error=type(exc).__name__,
                 hint="Falling back to JSON-mode (model likely doesn't support Structured Outputs).")
        return None


def _json_mode(messages: list[dict], model: str) -> QueryPlan | None:
    """Fallback for models without Structured Outputs (e.g. Kimi-k2.6)."""
    try:
        completion = openai_client().chat.completions.create(
            model=model, temperature=0, messages=messages,
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content or "{}"
        return QueryPlan.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError, Exception) as exc:
        log.warning("json_mode_parse_failed", error=str(exc))
        return None


def plan_query(history: list[dict], question: str) -> QueryPlan:
    settings = get_settings()
    messages = _build_messages(history, question)
    model = settings.azure_openai_chat_deployment

    plan = _try_structured(messages, model) or _json_mode(messages, model)
    if plan is None:  # both paths failed — degrade gracefully to raw question
        plan = QueryPlan(standalone_query=question, intent="simple")
    log.info("query_planned", standalone_query=plan.standalone_query, intent=plan.intent)
    return plan
