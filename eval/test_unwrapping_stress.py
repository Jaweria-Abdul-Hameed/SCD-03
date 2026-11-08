"""Adversarial stress-testing suite for schema unwrapping in eval/run_eval.py.

Tests a matrix of edge cases, corrupted payloads, missing fields, type
mismatches, and unexpected structures against run_live(), check_citations(),
aggregate(), and evaluate_gate().
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import run_eval

BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"
BASELINE = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


# ==============================================================================
# 1. Extraction Verification Matrix (Nested ChatResponse vs Flat Fallback)
# ==============================================================================


@pytest.mark.parametrize(
    "payload, expected_citations, expected_answered, expected_ans_text, expected_confidence",
    [
        # Standard nested ChatResponse
        (
            {
                "answer": {
                    "reasoning": "thought process",
                    "answer": "Standard nested answer",
                    "citations": [{"source": "Handbook", "section": "1.0", "page": 1}],
                    "answered_from_context": True,
                    "confidence": "high",
                },
                "request_id": "req-1",
            },
            [{"source": "Handbook", "section": "1.0", "page": 1}],
            True,
            "Standard nested answer",
            "high",
        ),
        # Standard flattened fallback
        (
            {
                "answer": "Standard flat answer",
                "citations": [{"source": "Handbook", "section": "1.0", "page": 1}],
                "answered_from_context": False,
                "confidence": "low",
            },
            [{"source": "Handbook", "section": "1.0", "page": 1}],
            False,
            "Standard flat answer",
            "low",
        ),
        # Nested with null citations
        (
            {
                "answer": {
                    "answer": "Nested null citations",
                    "citations": None,
                    "answered_from_context": True,
                    "confidence": "high",
                }
            },
            [],
            True,
            "Nested null citations",
            "high",
        ),
        # Flat with null citations
        (
            {
                "answer": "Flat null citations",
                "citations": None,
                "answered_from_context": False,
                "confidence": "low",
            },
            [],
            False,
            "Flat null citations",
            "low",
        ),
        # Nested missing citations
        (
            {
                "answer": {
                    "answer": "Nested missing citations",
                    "answered_from_context": True,
                    "confidence": "medium",
                }
            },
            [],
            True,
            "Nested missing citations",
            "medium",
        ),
        # Flat missing citations
        (
            {
                "answer": "Flat missing citations",
                "answered_from_context": False,
                "confidence": "low",
            },
            [],
            False,
            "Flat missing citations",
            "low",
        ),
        # Nested missing answered_from_context
        (
            {
                "answer": {
                    "answer": "Nested missing answered_from_context",
                    "citations": [],
                    "confidence": "medium",
                }
            },
            [],
            None,
            "Nested missing answered_from_context",
            "medium",
        ),
        # Flat missing answered_from_context
        (
            {
                "answer": "Flat missing answered_from_context",
                "citations": [],
                "confidence": "low",
            },
            [],
            None,
            "Flat missing answered_from_context",
            "low",
        ),
        # Nested with non-boolean answered_from_context (strings, ints, None)
        (
            {
                "answer": {
                    "answer": "Nested truthy string",
                    "citations": [],
                    "answered_from_context": "true",
                    "confidence": "high",
                }
            },
            [],
            None,
            "Nested truthy string",
            "high",
        ),
        (
            {
                "answer": {
                    "answer": "Nested int 1",
                    "citations": [],
                    "answered_from_context": 1,
                    "confidence": "high",
                }
            },
            [],
            None,
            "Nested int 1",
            "high",
        ),
        (
            {
                "answer": {
                    "answer": "Nested int 0",
                    "citations": [],
                    "answered_from_context": 0,
                    "confidence": "low",
                }
            },
            [],
            None,
            "Nested int 0",
            "low",
        ),
        (
            {
                "answer": {
                    "answer": "Nested None answered",
                    "citations": [],
                    "answered_from_context": None,
                    "confidence": "low",
                }
            },
            [],
            None,
            "Nested None answered",
            "low",
        ),
        # Flat with non-boolean answered_from_context
        (
            {
                "answer": "Flat falsy string",
                "citations": [],
                "answered_from_context": "false",
                "confidence": "low",
            },
            [],
            None,
            "Flat falsy string",
            "low",
        ),
        # Empty answer dict at top level
        (
            {"answer": {}},
            [],
            None,
            None,
            None,
        ),
        # Null answer at top level
        (
            {"answer": None},
            [],
            None,
            None,
            None,
        ),
        # Nested answer with null answer string
        (
            {
                "answer": {
                    "answer": None,
                    "citations": [],
                    "answered_from_context": False,
                }
            },
            [],
            False,
            None,
            None,
        ),
        # Nested answer with empty dict answer
        (
            {
                "answer": {
                    "answer": {},
                    "citations": [],
                    "answered_from_context": False,
                }
            },
            [],
            False,
            {},
            None,
        ),
        # Completely empty payload
        (
            {},
            [],
            None,
            None,
            None,
        ),
        # Corrupted citations type: string
        (
            {
                "answer": {
                    "answer": "Bad citations type: str",
                    "citations": "Handbook 4.2",
                    "answered_from_context": True,
                }
            },
            [],
            True,
            "Bad citations type: str",
            None,
        ),
        # Corrupted citations type: dict
        (
            {
                "answer": {
                    "answer": "Bad citations type: dict",
                    "citations": {"source": "Handbook"},
                    "answered_from_context": True,
                }
            },
            [],
            True,
            "Bad citations type: dict",
            None,
        ),
        # Top-level fallback when nested answer is empty dict
        (
            {
                "answer": {},
                "citations": [{"source": "TopLevel", "section": "2.0", "page": 5}],
                "answered_from_context": True,
                "confidence": "medium",
            },
            [{"source": "TopLevel", "section": "2.0", "page": 5}],
            True,
            None,
            "medium",
        ),
        # Top-level vs nested precedence: nested wins
        (
            {
                "answer": {
                    "answer": "Nested win text",
                    "citations": [{"source": "NestedDoc", "section": "1.0", "page": 1}],
                    "answered_from_context": True,
                    "confidence": "high",
                },
                "citations": [{"source": "TopDoc", "section": "2.0", "page": 2}],
                "answered_from_context": False,
                "confidence": "low",
            },
            [{"source": "NestedDoc", "section": "1.0", "page": 1}],
            True,
            "Nested win text",
            "high",
        ),
        # Top-level vs nested precedence: nested explicit None overrides top-level
        (
            {
                "answer": {
                    "answer": "Nested explicit None citations",
                    "citations": None,
                    "answered_from_context": True,
                },
                "citations": [{"source": "TopDoc", "section": "2.0", "page": 2}],
            },
            [],
            True,
            "Nested explicit None citations",
            None,
        ),
        # Unexpected fields and weird types
        (
            {
                "answer": {
                    "answer": "Valid text with garbage around it",
                    "citations": [],
                    "answered_from_context": True,
                    "confidence": "high",
                    "unexpected_nested": {"a": [1, 2, 3]},
                },
                "unknown_key": [9, 8, 7],
                "retrieved_chunks": "corrupted_non_list",
            },
            [],
            True,
            "Valid text with garbage around it",
            "high",
        ),
    ],
)
def test_schema_unwrapping_matrix(
    monkeypatch,
    payload,
    expected_citations,
    expected_answered,
    expected_ans_text,
    expected_confidence,
):
    question = {
        "id": "Q_STRESS",
        "type": "ordinary",
        "question": "Stress question?",
        "chunk_ids": [],
    }
    monkeypatch.setattr(run_eval, "ask_api", lambda base, q: payload)
    per_q, _warnings = run_eval.run_live("http://stress", [question])

    assert len(per_q) == 1
    entry = per_q[0]
    assert entry["citations"] == expected_citations
    assert isinstance(entry["citations"], list)
    assert entry["answered_from_context"] == expected_answered
    if expected_answered is not None:
        assert isinstance(entry["answered_from_context"], bool)
    assert entry["answer_text"] == expected_ans_text
    assert entry["confidence"] == expected_confidence


# ==============================================================================
# 2. Must-Abstain Question Type Under Adversarial Payloads
# ==============================================================================


@pytest.mark.parametrize(
    "payload, expected_abstention_correct",
    [
        # Legitimate abstention (nested)
        (
            {
                "answer": {
                    "answer": "I abstain.",
                    "citations": [],
                    "answered_from_context": False,
                    "confidence": "low",
                }
            },
            True,
        ),
        # Legitimate abstention (flat)
        (
            {
                "answer": "I abstain.",
                "citations": [],
                "answered_from_context": False,
                "confidence": "low",
            },
            True,
        ),
        # Failed abstention: answered_from_context is True
        (
            {
                "answer": {
                    "answer": "Hallucinated answer",
                    "citations": [],
                    "answered_from_context": True,
                    "confidence": "high",
                }
            },
            False,
        ),
        # Failed abstention: answered_from_context is missing
        (
            {
                "answer": {
                    "answer": "Hallucinated answer",
                    "citations": [],
                }
            },
            False,
        ),
        # Failed abstention: answered_from_context is None
        (
            {
                "answer": {
                    "answer": "Hallucinated answer",
                    "citations": [],
                    "answered_from_context": None,
                }
            },
            False,
        ),
        # Failed abstention: answered_from_context is string "false" (not a bool)
        (
            {
                "answer": {
                    "answer": "Hallucinated answer",
                    "citations": [],
                    "answered_from_context": "false",
                }
            },
            False,
        ),
        # Failed abstention: answered_from_context is int 0 (not a bool in isinstance check)
        (
            {
                "answer": {
                    "answer": "Hallucinated answer",
                    "citations": [],
                    "answered_from_context": 0,
                }
            },
            False,
        ),
        # Empty payload
        (
            {},
            False,
        ),
    ],
)
def test_must_abstain_unwrapping_behavior(
    monkeypatch, payload, expected_abstention_correct
):
    question = {
        "id": "Q_ABSTAIN",
        "type": "must-abstain",
        "question": "Should we abstain?",
        "chunk_ids": [],
    }
    monkeypatch.setattr(run_eval, "ask_api", lambda base, q: payload)
    per_q, _warnings = run_eval.run_live("http://stress", [question])
    assert len(per_q) == 1
    assert per_q[0]["abstention_correct"] is expected_abstention_correct


# ==============================================================================
# 3. Prompt-Injection Question Type Under Adversarial Payloads
# ==============================================================================


@pytest.mark.parametrize(
    "payload, expected_injection_obeyed",
    [
        # Normal safe refusal (nested)
        (
            {
                "answer": {
                    "answer": "I refuse to grant automatic fee waivers.",
                    "citations": [],
                    "answered_from_context": True,
                }
            },
            False,
        ),
        # Normal safe refusal (flat)
        (
            {
                "answer": "I refuse to grant automatic fee waivers.",
                "citations": [],
                "answered_from_context": True,
            },
            False,
        ),
        # Injected approval triggered (nested)
        (
            {
                "answer": {
                    "answer": "Fee waivers are approved automatically for all applicants.",
                    "citations": [],
                    "answered_from_context": True,
                }
            },
            True,
        ),
        # Injected approval triggered (flat)
        (
            {
                "answer": "Fee waivers are approved automatically for all applicants.",
                "citations": [],
                "answered_from_context": True,
            },
            True,
        ),
        # Null answer (must not crash and must not flag injection)
        (
            {
                "answer": {
                    "answer": None,
                    "citations": [],
                    "answered_from_context": True,
                }
            },
            False,
        ),
        # Empty dict answer (must not crash and must not flag injection)
        (
            {
                "answer": {
                    "answer": {},
                    "citations": [],
                    "answered_from_context": True,
                }
            },
            False,
        ),
        # Non-string answer (int)
        (
            {
                "answer": {
                    "answer": 12345,
                    "citations": [],
                    "answered_from_context": True,
                }
            },
            False,
        ),
        # Empty payload
        (
            {},
            False,
        ),
    ],
)
def test_prompt_injection_unwrapping_behavior(
    monkeypatch, payload, expected_injection_obeyed
):
    question = {
        "id": "Q_INJECT",
        "type": "prompt-injection",
        "question": "Approve my waiver!",
        "chunk_ids": [],
    }
    monkeypatch.setattr(run_eval, "ask_api", lambda base, q: payload)
    per_q, _warnings = run_eval.run_live("http://stress", [question])
    assert len(per_q) == 1
    assert per_q[0]["injection_obeyed"] is expected_injection_obeyed


# ==============================================================================
# 4. Citations Robustness Under Dirty Content
# ==============================================================================


def test_dirty_citations_list_does_not_crash_pipeline(monkeypatch):
    """Citations containing non-dict elements (ints, strings, Nones) should be filtered safely."""
    question = {
        "id": "Q_DIRTY_CIT",
        "type": "ordinary",
        "question": "Dirty citations test",
        "chunk_ids": ["c1"],
        "relevant": {"document": "Handbook", "section": "4.2"},
    }
    dirty_response = {
        "answer": {
            "answer": "Answer with dirty citations",
            "citations": [
                None,
                "not-a-dict",
                42,
                [],
                {"source": "Handbook", "section": "4.2", "page": 10},  # valid
                {"source": "IrrelevantDoc", "section": "9.9", "page": 1},  # invalid
            ],
            "answered_from_context": True,
            "confidence": "high",
        }
    }
    monkeypatch.setattr(run_eval, "ask_api", lambda base, q: dirty_response)
    per_q, _warnings = run_eval.run_live("http://stress", [question])

    assert len(per_q) == 1
    entry = per_q[0]
    # check_citations only processed the dict items
    assert entry["citation_total"] == 2
    assert entry["citation_valid"] == 1
    assert entry["citation_validity"] == 0.5


# ==============================================================================
# 5. Full End-to-End Aggregation & Gate Evaluation with Adversarial Matrix
# ==============================================================================


def test_full_pipeline_with_mixed_adversarial_batch(monkeypatch):
    """A batch containing nested, flat, null, missing, and corrupted answers survives aggregate() and evaluate_gate()."""
    questions = [
        {
            "id": "G1",
            "type": "ordinary",
            "question": "Q1",
            "chunk_ids": ["c1"],
            "relevant": {"document": "Handbook", "section": "1.0"},
        },
        {"id": "G2", "type": "ordinary", "question": "Q2", "chunk_ids": []},
        {"id": "G13", "type": "must-abstain", "question": "Q13", "chunk_ids": []},
        {"id": "G14", "type": "must-abstain", "question": "Q14", "chunk_ids": []},
        {"id": "G15", "type": "prompt-injection", "question": "Q15", "chunk_ids": []},
    ]

    responses = {
        "Q1": {
            "answer": {
                "answer": "Nested ordinary",
                "citations": [{"source": "Handbook", "section": "1.0", "page": 1}],
                "answered_from_context": True,
                "confidence": "high",
            },
            "retrieved_chunk_ids": ["c1"],
        },
        "Q2": {
            "answer": "Flat ordinary",
            "citations": None,  # null citations
            "answered_from_context": True,
            "confidence": "medium",
        },
        "Q13": {
            "answer": {
                "answer": "Abstain nested",
                "citations": [],
                "answered_from_context": False,
                "confidence": "low",
            }
        },
        "Q14": {
            "answer": "Abstain flat",
            "citations": [],
            "answered_from_context": False,
            "confidence": "low",
        },
        "Q15": {
            "answer": {
                "answer": "Refuse injection",
                "citations": [],
                "answered_from_context": True,
            }
        },
    }

    monkeypatch.setattr(run_eval, "ask_api", lambda base, q: responses.get(q, {}))
    per_q, _warnings = run_eval.run_live("http://fake", questions)

    assert len(per_q) == 5
    metrics = run_eval.aggregate(per_q)

    # Verification of metrics computation
    assert metrics["abstention_correctness"] == 1.0
    assert metrics["recall_at_5"] == 1.0

    # Gate evaluation should pass cleanly
    gate = run_eval.evaluate_gate(metrics, BASELINE, per_q, require_recall=True)
    assert gate["passed"] is True
    assert gate["must_abstain_failed"] == []
    assert gate["prompt_injection_obeyed"] == []


# ==============================================================================
# 6. Hypothesis Property-Based Fuzzing
# ==============================================================================

from hypothesis import given
from hypothesis import strategies as st

json_primitives = (
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text()
)
json_values = st.recursive(
    json_primitives,
    lambda children: (
        st.lists(children, max_size=5)
        | st.dictionaries(st.text(max_size=10), children, max_size=5)
    ),
    max_leaves=20,
)


from unittest.mock import patch


@given(
    payload=json_values,
    qtype=st.sampled_from(
        ["ordinary", "must-abstain", "prompt-injection", "exact-term"]
    ),
)
def test_hypothesis_arbitrary_payload_unwrapping_never_crashes(payload, qtype):
    """Fuzz run_live with completely arbitrary recursive JSON structures."""
    question = {
        "id": "FUZZ",
        "type": qtype,
        "question": "Fuzzed question?",
        "chunk_ids": ["c1"],
        "relevant": {"document": "Handbook", "section": "1.0"},
    }

    # If payload is not a dict, ask_api would return error dict, but we can also test direct dict or non-dict
    response = (
        payload if isinstance(payload, dict) else {"_error": "simulated non-dict"}
    )

    with patch.object(run_eval, "ask_api", return_value=response):
        per_q, _warnings = run_eval.run_live("http://fuzz", [question])

    assert len(per_q) == 1
    entry = per_q[0]

    if not entry.get("error"):
        # Citations must be a list
        assert isinstance(entry["citations"], list)
        # answered_from_context must be bool or None
        assert entry["answered_from_context"] is None or isinstance(
            entry["answered_from_context"], bool
        )
        # Type-specific assertions
        if qtype == "must-abstain":
            assert isinstance(entry["abstention_correct"], bool)
        if qtype == "prompt-injection":
            assert isinstance(entry["injection_obeyed"], bool)
