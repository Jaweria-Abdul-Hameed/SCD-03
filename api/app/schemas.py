"""Pydantic v2 schemas — the Answer contract (assignment §3.4).

This model is both the contract sent to the LLM (as a JSON schema /
``format=``) and the validator in code. Structure can be enforced;
truth cannot — hence validation + retry + canned fallback in services.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """One citation. Must exactly match a retrieved chunk's metadata."""

    source: str = Field(
        ..., description="Source document, e.g. 'Academic Rules Handbook Jun 2026'"
    )
    section: str = Field(..., description="Section / clause of the source, e.g. '4.2'")
    page: int = Field(
        ..., ge=1, description="1-based page number in the source document"
    )


class Answer(BaseModel):
    reasoning: str = Field(
        ..., description="Chain of thought; stripped before display to the user"
    )
    answer: str = Field(..., description="The answer shown to the user")
    citations: list[Citation] = Field(
        default_factory=list, description="Citations, each matching a retrieved chunk"
    )
    answered_from_context: bool = Field(
        ...,
        description="true when the answer was found in the evidence and is stated in `answer`; false only when the corpus does not cover the question",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Confidence in the answer"
    )


class ChatRequest(BaseModel):
    question: str = Field(
        ..., min_length=3, max_length=500, description="User question, 3-500 characters"
    )
    follow_up: bool = Field(
        default=False, description="Follow-up question: skip the semantic cache"
    )
    include_old_versions: bool = Field(
        default=False,
        description="If true, retrieve superseded chunks too (explicit old-version query)",
    )


class ChatResponse(BaseModel):
    answer: Answer = Field(..., description="Validated, grounded answer")
    request_id: str = Field(
        ..., description="Request ID from X-Request-ID header or generated UUID"
    )
    cache_hit: bool = Field(
        default=False, description="True if this answer came from the semantic cache"
    )
    latency_ms: float = Field(..., description="Total request latency in milliseconds")
    retrieved_chunk_ids: list[str] = Field(
        default_factory=list,
        description="Ids of the chunks retrieved for this request, best first. "
        "Lets eval/run_eval.py compute true recall@k instead of a citation proxy. "
        "Empty on a semantic-cache hit (no retrieval ran).",
    )
