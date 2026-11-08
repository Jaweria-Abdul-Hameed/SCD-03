"""Adversarial challenge test suite for Milestone 2.

Empirically stress-tests handle_chat flow paths, type invariance, and API contracts:
1. Early abstention (empty retrieval or below relevance floor).
2. Normal grounded generation (including markdown fences & citation pruning).
3. Single failure retry (transient model syntax error recovered on retry).
4. Double failure fallback (malformed JSON, invalid schema, empty string).
5. Semantic cache contract (skips follow-ups, never caches abstentions/fallbacks).
6. Strict Pydantic ChatResponse and Answer schema invariance across all branches.
7. FastAPI /chat route behavior ensuring HTTP 200 with valid schema and zero HTTP 500s.
"""

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import api.app.retrieval.cache as cache_mod
import api.app.services.chat as chat_service
from api.app.config import settings
from api.app.main import app
from api.app.schemas import Answer, ChatRequest, ChatResponse, Citation

VALID_CHUNK = {
    "id": "c_academic_1",
    "text": "Degree requirements specify a minimum CGPA of 2.0 for graduation.",
    "metadata": {
        "source": "Academic Handbook 2026",
        "section": "Graduation Requirements",
        "page": 45,
    },
    "similarity": 0.88,
}

LOW_SIMILARITY_CHUNK = {
    "id": "c_unrelated_1",
    "text": "Campus cafeteria hours are 8am to 8pm.",
    "metadata": {
        "source": "Student Life Guide",
        "section": "Dining",
        "page": 3,
    },
    "similarity": 0.22,
}


@pytest.fixture(autouse=True)
def _mock_cache_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default fast in-memory mock for cache calls to prevent cluster socket timeouts."""
    monkeypatch.setattr(chat_service, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(
        chat_service,
        "cache_set",
        lambda q, emb, ans: bool(ans.answered_from_context),
    )


def _assert_schema_invariance(response: Any) -> None:
    """Rigorous structural & type invariance assertions on ChatResponse."""
    assert isinstance(response, ChatResponse), (
        f"Expected ChatResponse, got {type(response)}"
    )
    assert isinstance(response.request_id, str)
    assert len(response.request_id) > 0
    assert isinstance(response.cache_hit, bool)
    assert isinstance(response.latency_ms, float)
    assert response.latency_ms >= 0.0

    ans = response.answer
    assert isinstance(ans, Answer), f"Expected Answer, got {type(ans)}"
    assert isinstance(ans.reasoning, str)
    assert isinstance(ans.answer, str)
    assert isinstance(ans.citations, list)
    for cit in ans.citations:
        assert isinstance(cit, Citation)
        assert isinstance(cit.source, str)
        assert isinstance(cit.section, str)
        assert isinstance(cit.page, int)
        assert cit.page >= 1
    assert isinstance(ans.answered_from_context, bool)
    assert ans.confidence in ("high", "medium", "low")

    # Round-trip Pydantic serialization invariant
    dumped = response.model_dump()
    reconstructed = ChatResponse.model_validate(dumped)
    assert reconstructed == response


class MockProvider:
    """Configurable mock provider supporting sequential return values."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or [])
        self.generate_calls: list[str] = []
        self.embed_calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(texts)
        return [[0.05] * 768 for _ in texts]

    def generate(self, prompt: str) -> str:
        self.generate_calls.append(prompt)
        if self.responses:
            return self.responses.pop(0)
        return json.dumps(
            {
                "reasoning": "Default test reasoning",
                "answer": "Default test answer",
                "citations": [
                    {
                        "source": "Academic Handbook 2026",
                        "section": "Graduation Requirements",
                        "page": 45,
                    }
                ],
                "answered_from_context": True,
                "confidence": "high",
            }
        )


# =====================================================================
# 1. Early Abstention Flow Paths
# =====================================================================


def test_early_abstention_on_empty_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When retriever yields no chunks, immediately abstain with low confidence."""
    provider = MockProvider()
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [])

    req = ChatRequest(question="What is the CGPA required?")
    resp = chat_service.handle_chat(req, "req-abstain-empty")

    _assert_schema_invariance(resp)
    assert resp.answer.answered_from_context is False
    assert resp.answer.answer == "The corpus does not cover this question."
    assert resp.answer.confidence == "low"
    assert resp.answer.citations == []
    assert resp.cache_hit is False
    assert len(provider.generate_calls) == 0, (
        "LLM must not be queried when retrieval is empty"
    )


def test_early_abstention_below_relevance_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When chunks fail to clear the relevance floor, abstain before LLM generation."""
    provider = MockProvider()
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(
        chat_service, "retrieve", lambda *a, **k: [dict(LOW_SIMILARITY_CHUNK)]
    )

    req = ChatRequest(question="What is the CGPA required?")
    resp = chat_service.handle_chat(req, "req-abstain-floor")

    _assert_schema_invariance(resp)
    assert resp.answer.answered_from_context is False
    assert resp.answer.confidence == "low"
    assert resp.answer.citations == []
    assert resp.cache_hit is False
    assert len(provider.generate_calls) == 0, (
        "LLM must not be queried when below relevance floor"
    )


def test_relevance_floor_boundary_conditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test boundary condition right below and right at RELEVANCE_FLOOR."""
    floor = settings.RELEVANCE_FLOOR
    provider = MockProvider()
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)

    # 1. Just below floor -> should abstain
    below_chunk = dict(VALID_CHUNK, similarity=floor - 0.0001)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [below_chunk])
    resp_below = chat_service.handle_chat(
        ChatRequest(question="Test below"), "req-below"
    )
    _assert_schema_invariance(resp_below)
    assert resp_below.answer.answered_from_context is False
    assert len(provider.generate_calls) == 0

    # 2. Exactly at floor -> should proceed to generation
    at_chunk = dict(VALID_CHUNK, similarity=floor)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [at_chunk])
    resp_at = chat_service.handle_chat(ChatRequest(question="Test at floor"), "req-at")
    _assert_schema_invariance(resp_at)
    assert resp_at.answer.answered_from_context is True
    assert len(provider.generate_calls) == 1


# =====================================================================
# 2. Normal Generation & Robust Parsing
# =====================================================================


def test_normal_generation_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Normal grounded generation returns ChatResponse conforming strictly to schema."""
    provider = MockProvider(
        [
            json.dumps(
                {
                    "reasoning": "Section 45 states CGPA 2.0 is required.",
                    "answer": "Minimum CGPA for graduation is 2.0.",
                    "citations": [
                        {
                            "source": "Academic Handbook 2026",
                            "section": "Graduation Requirements",
                            "page": 45,
                        }
                    ],
                    "answered_from_context": True,
                    "confidence": "high",
                }
            )
        ]
    )
    cache_store: dict[str, Any] = {}
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [dict(VALID_CHUNK)])
    monkeypatch.setattr(
        chat_service,
        "cache_set",
        lambda q, emb, ans: (
            cache_store.__setitem__(q, ans) or True
            if ans.answered_from_context
            else False
        ),
    )

    req = ChatRequest(question="What CGPA do I need to graduate?")
    resp = chat_service.handle_chat(req, "req-normal-1")

    _assert_schema_invariance(resp)
    assert resp.answer.answered_from_context is True
    assert resp.answer.confidence == "high"
    assert len(resp.answer.citations) == 1
    assert resp.answer.citations[0].source == "Academic Handbook 2026"
    assert resp.cache_hit is False
    assert req.question in cache_store, "Valid grounded answer must be cached"


def test_generation_with_markdown_fences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handles LLMs that wrap JSON output in ```json ... ``` codeblocks."""
    fenced_output = (
        "```json\n"
        + json.dumps(
            {
                "reasoning": "Parsed from markdown fence.",
                "answer": "Graduation requires 2.0 CGPA.",
                "citations": [
                    {
                        "source": "Academic Handbook 2026",
                        "section": "Graduation Requirements",
                        "page": 45,
                    }
                ],
                "answered_from_context": True,
                "confidence": "medium",
            }
        )
        + "\n```"
    )
    provider = MockProvider([fenced_output])
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [dict(VALID_CHUNK)])

    resp = chat_service.handle_chat(
        ChatRequest(question="CGPA requirement?"), "req-fenced"
    )
    _assert_schema_invariance(resp)
    assert resp.answer.answered_from_context is True
    assert resp.answer.confidence == "medium"


# =====================================================================
# 3. Validation Retry & Double Failure Fallback Flow Paths
# =====================================================================


def test_single_failure_recovers_on_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attempt 0 returns corrupt JSON; retry (attempt 1) succeeds and returns Answer."""
    valid_json = json.dumps(
        {
            "reasoning": "Recovered on retry.",
            "answer": "Minimum CGPA is 2.0.",
            "citations": [
                {
                    "source": "Academic Handbook 2026",
                    "section": "Graduation Requirements",
                    "page": 45,
                }
            ],
            "answered_from_context": True,
            "confidence": "high",
        }
    )
    provider = MockProvider(["{broken json: not valid syntax...", valid_json])
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [dict(VALID_CHUNK)])

    resp = chat_service.handle_chat(
        ChatRequest(question="CGPA requirement?"), "req-retry-success"
    )

    _assert_schema_invariance(resp)
    assert resp.answer.answered_from_context is True
    assert resp.answer.reasoning == "Recovered on retry."
    assert len(provider.generate_calls) == 2, (
        "Must retry exactly once on validation failure"
    )


def test_double_failure_fallback_on_garbage_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attempt 0 and Attempt 1 both return invalid JSON -> safe canned fallback."""
    provider = MockProvider(
        [
            "I apologize, but as an AI language model I cannot answer.",
            "Still cannot parse this output format properly.",
        ]
    )
    cache_store: dict[str, Any] = {}
    cache_set_calls: list[Any] = []

    def mock_cache_set(q: str, emb: list[float], ans: Answer) -> bool:
        cache_set_calls.append(ans)
        # Mirror cache.cache_set rule: refuse ungrounded answers
        if not cache_mod.cacheable(ans):
            return False
        cache_store[q] = ans
        return True

    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [dict(VALID_CHUNK)])
    monkeypatch.setattr(chat_service, "cache_set", mock_cache_set)

    resp = chat_service.handle_chat(
        ChatRequest(question="CGPA requirement?"), "req-double-fail"
    )

    _assert_schema_invariance(resp)
    assert resp.answer.answered_from_context is False
    assert resp.answer.answer == "The corpus does not cover this question."
    assert "validation twice" in resp.answer.reasoning
    assert resp.answer.confidence == "low"
    assert resp.answer.citations == []
    assert len(provider.generate_calls) == 2
    # Verify cacheability check
    assert cache_mod.cacheable(resp.answer) is False
    assert len(cache_store) == 0, "Fallback abstention must never be cached"


def test_double_failure_fallback_on_schema_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attempt 0 and Attempt 1 return JSON but violate Answer schema types."""
    invalid_schema_1 = json.dumps(
        {"reasoning": 12345, "answer": True, "citations": "none"}
    )
    invalid_schema_2 = json.dumps(
        {"only_field": "missing reasoning, answer, citations, etc."}
    )

    provider = MockProvider([invalid_schema_1, invalid_schema_2])
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [dict(VALID_CHUNK)])

    resp = chat_service.handle_chat(
        ChatRequest(question="CGPA requirement?"), "req-double-schema-fail"
    )

    _assert_schema_invariance(resp)
    assert resp.answer.answered_from_context is False
    assert resp.answer.confidence == "low"
    assert "validation twice" in resp.answer.reasoning


def test_double_failure_fallback_on_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attempt 0 and Attempt 1 return empty strings."""
    provider = MockProvider(["", "   \n\t  "])
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [dict(VALID_CHUNK)])

    resp = chat_service.handle_chat(
        ChatRequest(question="CGPA requirement?"), "req-double-empty-fail"
    )

    _assert_schema_invariance(resp)
    assert resp.answer.answered_from_context is False
    assert resp.answer.confidence == "low"


# =====================================================================
# 4. Semantic Cache Contract & Abstention Isolation
# =====================================================================


def test_cache_hit_returns_stored_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When question hits semantic cache, returns stored Answer with cache_hit=True."""
    cached_ans = Answer(
        reasoning="Cached from previous run",
        answer="Minimum CGPA is 2.0 (from cache).",
        citations=[
            Citation(
                source="Academic Handbook 2026",
                section="Graduation Requirements",
                page=45,
            )
        ],
        answered_from_context=True,
        confidence="high",
    )
    provider = MockProvider()
    retrieve_mock = MagicMock()
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(chat_service, "retrieve", retrieve_mock)
    monkeypatch.setattr(chat_service, "cache_get", lambda *a, **k: cached_ans)

    req = ChatRequest(question="What is the graduation CGPA?")
    resp = chat_service.handle_chat(req, "req-cache-hit")

    _assert_schema_invariance(resp)
    assert resp.cache_hit is True
    assert resp.answer == cached_ans
    assert retrieve_mock.call_count == 0, "Retrieval must be skipped on cache hit"
    assert len(provider.generate_calls) == 0, "Generation must be skipped on cache hit"


def test_follow_up_bypasses_cache_lookup_and_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Follow-up questions must skip cache lookup and cache writing."""
    provider = MockProvider()
    cache_get_mock = MagicMock(return_value=None)
    cache_set_mock = MagicMock()
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [dict(VALID_CHUNK)])
    monkeypatch.setattr(chat_service, "cache_get", cache_get_mock)
    monkeypatch.setattr(chat_service, "cache_set", cache_set_mock)

    req = ChatRequest(question="And what about probation?", follow_up=True)
    resp = chat_service.handle_chat(req, "req-follow-up")

    _assert_schema_invariance(resp)
    assert resp.cache_hit is False
    assert cache_get_mock.call_count == 0, (
        "cache_get must not be called for follow_up=True"
    )
    assert cache_set_mock.call_count == 0, (
        "cache_set must not be called for follow_up=True"
    )


# =====================================================================
# 5. FastAPI /chat Route Integration & HTTP Status Verification
# =====================================================================


def test_api_chat_route_returns_200_and_nested_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end /chat route check ensuring HTTP 200 and schema unwrap integrity."""
    provider = MockProvider()
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [dict(VALID_CHUNK)])

    with TestClient(app) as client:
        r = client.post(
            "/chat",
            json={"question": "What is the CGPA for graduation?"},
            headers={"X-Request-ID": "custom-trace-id-123"},
        )
        assert r.status_code == 200
        body = r.json()

        # Schema verification
        assert body["request_id"] == "custom-trace-id-123"
        assert body["cache_hit"] is False
        assert isinstance(body["latency_ms"], (int, float))

        # Nested answer verification
        assert isinstance(body["answer"], dict)
        ans = body["answer"]
        assert ans["answered_from_context"] is True
        assert ans["confidence"] in ("high", "medium", "low")
        assert isinstance(ans["citations"], list)
        assert len(ans["citations"]) == 1
        assert ans["citations"][0]["source"] == "Academic Handbook 2026"


def test_api_chat_route_never_returns_500_on_model_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that even catastrophic model output returns HTTP 200 with canned fallback."""
    provider = MockProvider(["<<<SYNTAX ERROR>>>", "<html>502 Bad Gateway</html>"])
    monkeypatch.setattr(chat_service, "get_provider", lambda: provider)
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [dict(VALID_CHUNK)])

    with TestClient(app) as client:
        r = client.post("/chat", json={"question": "What happens on model explosion?"})
        assert r.status_code == 200, "Must never return HTTP 500 on bad model output"
        body = r.json()
        assert body["answer"]["answered_from_context"] is False
        assert body["answer"]["answer"] == "The corpus does not cover this question."
        assert body["answer"]["confidence"] == "low"
