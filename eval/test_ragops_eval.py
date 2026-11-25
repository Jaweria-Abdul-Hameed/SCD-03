"""Unit tests for Part B 3-level eval, Part C2 release gate, and Part E coverage checker."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval import coverage_check as cov_mod
from eval import release_gate as gate_mod
from eval import run_ragops_eval as eval_mod


def test_golden_jsonl_meets_part_b_quotas():
    golden = eval_mod.load_jsonl(Path("eval/golden.jsonl"))
    assert len(golden) >= 25
    answerable = [q for q in golden if q.get("category") == "answerable"]
    unanswerable = [q for q in golden if q.get("category") == "unanswerable"]
    hard = [q for q in golden if q.get("category") == "hard"]
    human = [q for q in golden if q.get("origin") == "human"]
    synth_reviewed = [
        q
        for q in golden
        if q.get("origin") == "synthetic" and q.get("reviewed_by_human") is True
    ]

    assert len(answerable) >= 15
    assert len(unanswerable) >= 5
    assert len(hard) >= 5
    assert len(human) >= 8
    assert len(synth_reviewed) >= 8
    for q in golden:
        assert q.get("origin") in ("human", "synthetic")
    for q in answerable:
        assert q.get("relevant_document")
        assert isinstance(q.get("relevant_page"), int) and q["relevant_page"] >= 1
    for q in unanswerable:
        assert q.get("must_abstain") is True


def test_module_pairs_jsonl_meets_quotas():
    pairs = eval_mod.load_jsonl(Path("eval/module_pairs.jsonl"))
    para = [p for p in pairs if p["label"] == "paraphrase"]
    unrel = [p for p in pairs if p["label"] == "unrelated"]
    assert len(para) >= 15
    assert len(unrel) >= 15


def test_live_queries_jsonl_meets_part_e_quotas():
    live = eval_mod.load_jsonl(Path("eval/live_queries.jsonl"))
    assert len(live) >= 40
    in_dom = [q for q in live if q.get("domain") == "in_domain"]
    uncov = [q for q in live if q.get("domain") == "uncovered"]
    assert len(in_dom) >= 25
    assert len(uncov) >= 12


def test_release_gate_pass_and_fail():
    baseline = {
        "level2_component": {"recall@5": 0.85},
        "level3_e2e": {
            "faithfulness": 0.90,
            "abstention_correctness": 1.0,
            "citation_validity": 1.0,
            "latency_p95_ms": 15000.0,
        },
    }
    thresholds = gate_mod.load_thresholds(Path("eval/gate_thresholds.yaml"))

    passing_cand = {
        "level2_component": {"recall@5": 0.84},
        "level3_e2e": {
            "faithfulness": 0.92,
            "abstention_correctness": 1.0,
            "citation_validity": 0.98,
            "latency_p95_ms": 18000.0,
        },
    }
    assert gate_mod.evaluate_gate(passing_cand, baseline, thresholds)["passed"] is True

    failing_cand = {
        "level2_component": {"recall@5": 0.60},
        "level3_e2e": {
            "faithfulness": 0.50,
            "abstention_correctness": 0.60,
            "citation_validity": 0.70,
            "latency_p95_ms": 60000.0,
        },
    }
    res = gate_mod.evaluate_gate(failing_cand, baseline, thresholds)
    assert res["passed"] is False
    assert all(not c["pass"] for c in res["checks"])


def test_coverage_check_returns_nonzero_when_below_threshold(tmp_path: Path):
    live = [{"id": "L1", "query": "How do alumni order duplicate transcripts?"}]
    gold = [{"id": "G1", "question": "What is the tuition fee per credit hour?"}]
    rep = cov_mod.compute_coverage(
        live,
        gold,
        ollama_host="unused",
        embed_model="nomic-embed-text",
        provider_mode="stub",
        sim_threshold=0.70,
        coverage_threshold=0.85,
    )
    assert rep["passed"] is False
    assert rep["uncovered_count"] == 1
    assert "alumni_and_degree_verification" in rep["uncovered_by_topic"]


def test_run_ragops_eval_end_to_end_stub(monkeypatch, tmp_path: Path):
    """Test single-command 3-level evaluation + stochasticity + gate with fake API."""
    golden = eval_mod.load_jsonl(Path("eval/golden.jsonl"))[:4]
    g_path = tmp_path / "g.jsonl"
    g_path.write_text("\n".join(json.dumps(x) for x in golden) + "\n", encoding="utf-8")

    def fake_chat(
        api_base: str, question: str, follow_up: bool = True, timeout: int = 180
    ):
        return {
            "trace_id": "t-1",
            "latency_ms": 120.0,
            "answer": {
                "reasoning": "Matched handbook clause.",
                "answer": "Students must maintain 80 percent attendance.",
                "citations": [
                    {
                        "source": "Academic_Rules_Handbook_2026.pdf",
                        "section": "1.21",
                        "page": 10,
                    }
                ],
                "answered_from_context": True,
                "confidence": "high",
            },
            "retrieved_chunks": [
                {
                    "id": "c1",
                    "text": "Students must maintain 80 percent attendance in all courses.",
                    "metadata": {
                        "source": "Academic_Rules_Handbook_2026.pdf",
                        "section": "1.21",
                        "page": 10,
                    },
                    "similarity": 0.91,
                }
            ],
            "guardrail_actions": [],
        }

    monkeypatch.setattr(eval_mod, "_call_chat", fake_chat)
    r1 = eval_mod.evaluate_once(
        api_base="http://fake",
        golden_path=g_path,
        pairs_path=Path("eval/module_pairs.jsonl"),
        ollama_host="unused",
        embed_model="nomic-embed-text",
        llm_model="llama3.2:3b",
        provider_mode="stub",
        use_llm_judge=False,
        judge_labels_path=None,
        seed=42,
        run_noise_test=True,
    )
    assert r1["level1_module"]["paraphrase_pairs"] == 16
    assert r1["level2_component"]["recall@5"] > 0
    assert r1["level3_e2e"]["citation_validity"] == 1.0


def test_cache_probe_counts_repeat_hits(monkeypatch, tmp_path: Path):
    """D3: the scored pass bypasses the cache; the probe must see the repeat call hit it."""
    golden = [
        q
        for q in eval_mod.load_jsonl(Path("eval/golden.jsonl"))
        if not q["must_abstain"]
    ][:3]
    g_path = tmp_path / "g.jsonl"
    g_path.write_text("\n".join(json.dumps(x) for x in golden) + "\n", encoding="utf-8")
    cache: set[str] = set()

    def fake_chat(
        api_base: str, question: str, follow_up: bool = True, timeout: int = 180
    ):
        hit = (not follow_up) and question in cache
        if not follow_up:
            cache.add(question)
        return {
            "trace_id": "t",
            "latency_ms": 5.0 if hit else 900.0,
            "cache_hit": hit,
            "answer": {"answer": "ok", "citations": [], "answered_from_context": True},
            "retrieved_chunks": [],
        }

    monkeypatch.setattr(eval_mod, "_call_chat", fake_chat)
    res = eval_mod.evaluate_once(
        api_base="http://fake",
        golden_path=g_path,
        pairs_path=Path("eval/module_pairs.jsonl"),
        ollama_host="unused",
        embed_model="nomic-embed-text",
        llm_model="llama3.2:3b",
        provider_mode="stub",
        use_llm_judge=False,
        judge_labels_path=None,
        seed=42,
        run_noise_test=False,
        cache_probe_n=2,
    )
    probe = res["level3_e2e"]["cache_probe"]
    assert probe["questions"] == 2
    assert probe["first_call_hits"] == 0
    assert probe["repeat_call_hits"] == 2
    assert probe["repeat_hit_rate"] == 1.0
    assert probe["overall_hit_rate"] == 0.5
    assert probe["hit_latency_p50_ms"] == 5.0
    # the scored Level 3 latency is untouched by the probe
    assert res["level3_e2e"]["latency_p50_ms"] == 900.0
