"""Typed contracts shared by generation, API and UI. Citations are a typed
Structured Outputs schema emitted by the model — never regex-parsed from prose."""
from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    source_id: int = Field(description="The [n] number of the source the fact came from")
    doc_name: str
    page: int = Field(description="Page number where the cited text appears")
    quote: str = Field(description="Short verbatim snippet from the source supporting the fact")


class GroundedAnswer(BaseModel):
    answer_markdown: str = Field(
        description="The answer in markdown, with inline [n] citation markers after each fact")
    citations: list[Citation]
    insufficient_context: bool = Field(
        description="True when the sources do not contain enough information to answer")
    confidence: Literal["high", "medium", "low"]


class ChatRequest(BaseModel):
    session_id: str
    message: str


class SourceChunk(BaseModel):
    source_id: int
    chunk_id: str
    doc_id: str
    doc_name: str
    doc_type: str
    page_start: int
    page_end: int
    synthetic_pages: bool
    heading_path: str
    content: str
    score: float


class ChatResponse(BaseModel):
    session_id: str
    standalone_query: str
    intent: str
    answer: GroundedAnswer
    sources: list[SourceChunk]
