"""RAG evaluation harness — runs the golden set against the live API and scores
each answer with an LLM judge (groundedness + relevance, 1-5), plus
deterministic checks (expected substring, refusal correctness, citation
presence). Results print as a markdown table for the README.

Run (API up, sample documents ingested):  python evals/evaluate.py"""
import json
import statistics
import sys
import uuid
from pathlib import Path

import requests
from pydantic import BaseModel, Field

from src.core.azure_clients import openai_client
from src.core.config import get_settings

GOLDEN = Path(__file__).resolve().parent / "golden_set.jsonl"


class JudgeScore(BaseModel):
    groundedness: int = Field(ge=1, le=5, description="5 = every claim supported by the sources")
    relevance: int = Field(ge=1, le=5, description="5 = directly and completely answers the question")
    rationale: str


def _judge(question: str, sources: str, answer: str) -> JudgeScore:
    settings = get_settings()
    completion = openai_client().beta.chat.completions.parse(
        model=settings.azure_openai_chat_deployment,
        temperature=0,
        messages=[
            {"role": "system",
             "content": "You are a strict RAG evaluator. Score the ANSWER for groundedness "
                        "(claims supported by SOURCES) and relevance (answers the QUESTION) on 1-5."},
            {"role": "user",
             "content": f"QUESTION:\n{question}\n\nSOURCES:\n{sources[:8000]}\n\nANSWER:\n{answer}"},
        ],
        response_format=JudgeScore,
    )
    return completion.choices[0].message.parsed or JudgeScore(groundedness=1, relevance=1, rationale="parse failure")


def _ask(session_id: str, message: str) -> dict:
    response = requests.post(f"{get_settings().api_base_url}/chat",
                             json={"session_id": session_id, "message": message}, timeout=180)
    response.raise_for_status()
    return response.json()


def main() -> int:
    rows, groundedness_scores, relevance_scores, passes = [], [], [], 0
    cases = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]

    for case in cases:
        session_id = f"eval-{uuid.uuid4().hex[:8]}"
        try:
            if case.get("followup"):  # follow-up chains: first turn primes the context
                _ask(session_id, case["question"])
                data = _ask(session_id, case["followup"])
            else:
                data = _ask(session_id, case["question"])
        except requests.RequestException as exc:
            rows.append((case["id"], case["type"], "ERROR", "-", "-", str(exc)[:60]))
            continue

        answer = data["answer"]
        text = answer["answer_markdown"]
        refused = answer["insufficient_context"]

        if case["expect_refusal"]:
            passed = refused
            grounded, relevant = "-", "-"
        else:
            passed = (not refused) and case["expect_contains"].lower() in text.lower() \
                     and len(answer["citations"]) > 0
            sources = "\n\n".join(s["content"] for s in data["sources"])
            score = _judge(case.get("followup") or case["question"], sources, text)
            groundedness_scores.append(score.groundedness)
            relevance_scores.append(score.relevance)
            grounded, relevant = str(score.groundedness), str(score.relevance)

        passes += passed
        rows.append((case["id"], case["type"], "PASS" if passed else "FAIL", grounded, relevant,
                     text[:60].replace("\n", " ")))

    print("\n| id | type | result | groundedness | relevance | answer (head) |")
    print("|---|---|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(str(c) for c in row) + " |")
    print(f"\nPassed {passes}/{len(cases)}"
          + (f" · mean groundedness {statistics.mean(groundedness_scores):.2f}"
             f" · mean relevance {statistics.mean(relevance_scores):.2f}"
             if groundedness_scores else ""))
    return 0 if passes == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
