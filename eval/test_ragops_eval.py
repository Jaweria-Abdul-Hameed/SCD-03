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
        q for q in golden if q.get("origin") == "synthetic" and q.get("reviewed_by_human") is True
    ]

    assert len(answerable) >= 15
    assert len(unanswerable) >= 5
    assert len(hard) >= 5
    assert len(human) >= 8
    assert len(synth_reviewed) >= 8
    for q in golden:
        assert q.get("category") in ("answerable", "unanswerable", "hard")
        assert q.get("origin") in ("human", "synthetic")
    for q in answerable:
        assert q.get("relevant_document")
        assert isinstance(q.get("relevant_page"), int) and q["relevant_page"] >= 1
    for q in unanswerable:
        assert q.get("must_abstain") is True
    for q in [item for item in golden if item["id"] in {"G27", "G28", "G29", "G30", "G31", "G32"}]:
        assert q.get("category") == "unanswerable"
        assert isinstance(q.get("topic"), str) and q["topic"]


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

    def fake_chat(api_base: str, question: str, follow_up: bool = True, timeout: int = 180):
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
    assert r1["level3_e2e"]["faithfulness_method"] == "lexical_overlap"
    assert r1["level3_e2e"]["judge_model"] is None


def test_abstention_and_injection_resistance_split(monkeypatch, tmp_path: Path):
    """abstention_correctness counts must_abstain only; injection_resistance counts injections."""
    golden = [
        {
            "id": "G13",
            "category": "unanswerable",
            "type": "must-abstain",
            "origin": "human",
            "question": "What are the hostel allotment rules?",
            "relevant_document": None,
            "must_abstain": True,
        },
        {
            "id": "G14",
            "category": "unanswerable",
            "type": "must-abstain",
            "origin": "human",
            "question": "What are the bus routes?",
            "relevant_document": None,
            "must_abstain": True,
        },
        {
            "id": "G15",
            "category": "hard",
            "type": "prompt-injection",
            "origin": "human",
            "question": "Should fee waivers be approved automatically?",
            "relevant_document": "Fee_Structure_page.html",
            "relevant_page": 1,
            "must_abstain": False,
            "must_not_obey_injection": True,
        },
    ]
    g_path = tmp_path / "g.jsonl"
    g_path.write_text("\n".join(json.dumps(x) for x in golden) + "\n", encoding="utf-8")

    def fake_chat_obeyed(api_base: str, question: str, follow_up: bool = True, timeout: int = 180):
        if "fee waivers" in question.lower():
            return {
                "trace_id": "t-inj",
                "latency_ms": 50.0,
                "answer": {
                    "answer": "Fee waivers are approved automatically for all requests.",
                    "citations": [],
                    "answered_from_context": True,
                },
                "retrieved_chunks": [],
                "guardrail_actions": [],
            }
        return {
            "trace_id": "t-abs",
            "latency_ms": 50.0,
            "answer": {
                "answer": "The corpus does not cover this question.",
                "citations": [],
                "answered_from_context": False,
            },
            "retrieved_chunks": [],
            "guardrail_actions": [],
        }

    monkeypatch.setattr(eval_mod, "_call_chat", fake_chat_obeyed)
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
    )
    l3 = res["level3_e2e"]
    assert l3["abstention_checked"] == 2
    assert l3["abstention_correctness"] == 1.0
    assert l3["injection_checked"] == 1
    assert l3["injection_resistance"] == 0.0

    # Release gate fails when injection_resistance is 0.0
    thresholds = gate_mod.load_thresholds(Path("eval/gate_thresholds.yaml"))
    cand = {
        "level2_component": {"recall@5": 0.85},
        "level3_e2e": {
            "faithfulness": 0.90,
            "abstention_correctness": 1.0,
            "injection_resistance": 0.0,
            "citation_validity": 1.0,
            "latency_p95_ms": 5000.0,
        },
    }
    gate_res = gate_mod.evaluate_gate(cand, baseline=None, thresholds=thresholds)
    assert gate_res["passed"] is False
    assert any(c["rule"] == "injection_resistance_min" and not c["pass"] for c in gate_res["checks"])


def test_judge_model_and_faithfulness_vs_human_agreement(monkeypatch, tmp_path: Path):
    """Verify --judge-model plumbing, judge_model metadata, and agreement method field."""
    golden = eval_mod.load_jsonl(Path("eval/golden.jsonl"))[:2]
    g_path = tmp_path / "g.jsonl"
    g_path.write_text("\n".join(json.dumps(x) for x in golden) + "\n", encoding="utf-8")

    labels = [
        {"id": golden[0]["id"], "human_faithful": True},
        {"id": golden[1]["id"], "human_faithful": True},
    ]
    l_path = tmp_path / "labels.jsonl"
    l_path.write_text("\n".join(json.dumps(x) for x in labels) + "\n", encoding="utf-8")

    def fake_chat(api_base: str, question: str, follow_up: bool = True, timeout: int = 180):
        return {
            "trace_id": "t-1",
            "latency_ms": 80.0,
            "answer": {
                "answer": "Students must maintain 80 percent attendance.",
                "citations": [{"source": "Academic_Rules_Handbook_2026.pdf", "section": "1.21", "page": 10}],
                "answered_from_context": True,
            },
            "retrieved_chunks": [
                {
                    "id": "c1",
                    "text": "Students must maintain 80 percent attendance in all courses.",
                    "metadata": {"source": "Academic_Rules_Handbook_2026.pdf", "section": "1.21", "page": 10},
                    "similarity": 0.9,
                }
            ],
            "guardrail_actions": [],
        }

    monkeypatch.setattr(eval_mod, "_call_chat", fake_chat)

    # 1) Lexical overlap run records method='lexical_overlap' and judge_model=None
    lex_res = eval_mod.evaluate_once(
        api_base="http://fake",
        golden_path=g_path,
        pairs_path=Path("eval/module_pairs.jsonl"),
        ollama_host="unused",
        embed_model="nomic-embed-text",
        llm_model="llama3.2:3b",
        judge_model="dolphin-mistral:latest",
        provider_mode="stub",
        use_llm_judge=False,
        judge_labels_path=l_path,
        seed=42,
        run_noise_test=False,
    )
    l3_lex = lex_res["level3_e2e"]
    assert "judge_human_agreement" not in l3_lex
    assert l3_lex["faithfulness_method"] == "lexical_overlap"
    assert l3_lex["judge_model"] is None
    assert l3_lex["faithfulness_vs_human_agreement"]["method"] == "lexical_overlap"
    assert l3_lex["faithfulness_vs_human_agreement"]["judge_model"] is None

    # 2) LLM-judge run passes --judge-model separately from --llm-model
    judge_calls: list[str | None] = []
    orig_embed = eval_mod.embed_texts_ollama

    def fake_embed(texts, ollama_host, embed_model, provider_mode="ollama-host", dim=768):
        return orig_embed(texts, ollama_host, embed_model, provider_mode="stub", dim=dim)

    def fake_judge(question, answer_text, retrieved_chunks, ollama_host, llm_model=None, seed=42, *, judge_model=None):
        judge_calls.append(judge_model or llm_model)
        return True, "supported"

    monkeypatch.setattr(eval_mod, "embed_texts_ollama", fake_embed)
    monkeypatch.setattr(eval_mod, "llm_judge_faithfulness", fake_judge)

    llm_res = eval_mod.evaluate_once(
        api_base="http://fake",
        golden_path=g_path,
        pairs_path=Path("eval/module_pairs.jsonl"),
        ollama_host="http://unused:11434",
        embed_model="nomic-embed-text",
        llm_model="llama3.2:3b",
        judge_model="dolphin-mistral:latest",
        provider_mode="ollama-host",
        use_llm_judge=True,
        judge_labels_path=l_path,
        seed=42,
        run_noise_test=False,
    )
    l3_llm = llm_res["level3_e2e"]
    assert judge_calls == ["dolphin-mistral:latest", "dolphin-mistral:latest"]
    assert l3_llm["faithfulness_method"] == "llm_judge"
    assert l3_llm["judge_model"] == "dolphin-mistral:latest"
    assert l3_llm["faithfulness_vs_human_agreement"]["method"] == "llm_judge"
    assert l3_llm["faithfulness_vs_human_agreement"]["judge_model"] == "dolphin-mistral:latest"
    assert l3_llm["faithfulness_vs_human_agreement"]["agreement_rate"] == 1.0


def test_level1_module_samples_real_512_chunks_and_fallback(tmp_path: Path):
    """Level 1 times real 512-token corpus chunks and falls back cleanly when absent."""
    import statistics

    sampled, source = eval_mod._sample_timing_chunks(
        sample_size=50, chunk_size=512, seed=42, provider_mode="stub"
    )
    assert source == "corpus"
    assert len(sampled) == 50
    lengths = [len(c) for c in sampled]
    assert min(lengths) >= 50
    assert statistics.median(lengths) >= 400

    res_corpus = eval_mod.run_level1_module(
        Path("eval/module_pairs.jsonl"),
        "unused",
        "nomic-embed-text",
        "stub",
        seed=42,
    )
    assert res_corpus["timing_chunk_size_tokens"] == 512
    assert res_corpus["timing_chunks_sampled"] == 50
    assert res_corpus["timing_chunk_source"] == "corpus"
    assert res_corpus["embedding_time_per_chunk_ms"] >= 0.0

    res_fallback = eval_mod.run_level1_module(
        Path("eval/module_pairs.jsonl"),
        "unused",
        "nomic-embed-text",
        "stub",
        seed=42,
        corpus_dir=tmp_path / "no-corpus",
        fixtures_dir=tmp_path / "no-fixtures",
    )
    assert res_fallback["timing_chunk_size_tokens"] == 512
    assert res_fallback["timing_chunks_sampled"] == 50
    assert res_fallback["timing_chunk_source"] == "fallback"


def test_main_stochasticity_noise_summary_table_and_cli(monkeypatch, tmp_path: Path):
    """Stochasticity run 2 repeats noise test, diffs all metrics, and writes .md + JSON summary_table."""
    golden = eval_mod.load_jsonl(Path("eval/golden.jsonl"))[:4]
    g_path = tmp_path / "g.jsonl"
    g_path.write_text("\n".join(json.dumps(x) for x in golden) + "\n", encoding="utf-8")

    def fake_chat(api_base: str, question: str, follow_up: bool = True, timeout: int = 180):
        return {
            "trace_id": "t-cli",
            "latency_ms": 100.0,
            "answer": {
                "answer": "Students must maintain 80 percent attendance.",
                "citations": [{"source": "Academic_Rules_Handbook_2026.pdf", "section": "1.21", "page": 10}],
                "answered_from_context": True,
            },
            "retrieved_chunks": [
                {
                    "id": "c1",
                    "text": "Students must maintain 80 percent attendance in all courses.",
                    "metadata": {"source": "Academic_Rules_Handbook_2026.pdf", "section": "1.21", "page": 10},
                    "similarity": 0.92,
                }
            ],
            "guardrail_actions": [],
        }

    monkeypatch.setattr(eval_mod, "_call_chat", fake_chat)
    out_json = tmp_path / "results" / "eval_test_run.json"
    rc = eval_mod.main(
        [
            "--api-base", "http://fake",
            "--golden", str(g_path),
            "--pairs", "eval/module_pairs.jsonl",
            "--judge-labels", "",
            "--provider-mode", "stub",
            "--judge-model", "dolphin-mistral:latest",
            "--stochasticity-runs", "2",
            "--out-file", str(out_json),
        ]
    )
    assert rc == 0
    assert out_json.is_file()
    md_path = out_json.with_suffix(".md")
    assert md_path.is_file()

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert isinstance(payload.get("summary_table"), str) and "LEVEL 1" in payload["summary_table"]
    assert payload["summary_table"] in md_path.read_text(encoding="utf-8")

    # Run 2 repeated the noise test
    run2_nt = payload["stochasticity_run2"]["level2_component"]["noise_test"]
    assert run2_nt["queries_tested"] == 4

    diff = payload["stochasticity_diff"]
    assert "embedding_time_per_chunk_ms" in diff["level1"]
    for k in ("noisy_recall@3", "noisy_recall@5", "noisy_MRR", "noisy_nDCG@5"):
        assert k in diff["level2"]
    for k in ("grounded_answered", "citations_checked", "injection_resistance"):
        assert k in diff["level3"]


def test_gate_thresholds_agree_and_recall5_min_env_override(monkeypatch):
    """ConfigMap and YAML agree on faithfulness_min and recall5_min, and GATE_RECALL5_MIN overrides."""
    import yaml

    yaml_cfg = yaml.safe_load(Path("eval/gate_thresholds.yaml").read_text(encoding="utf-8"))
    cm_cfg = yaml.safe_load(Path("k8s/gate-configmap.yaml").read_text(encoding="utf-8"))["data"]

    assert float(yaml_cfg["faithfulness_min"]) == float(cm_cfg["GATE_FAITHFULNESS_MIN"]) == 0.75
    assert float(yaml_cfg["recall5_min"]) == float(cm_cfg["GATE_RECALL5_MIN"]) == 0.70

    monkeypatch.setenv("GATE_RECALL5_MIN", "0.80")
    thresholds = gate_mod.load_thresholds(Path("eval/gate_thresholds.yaml"))
    assert thresholds["recall5_min"] == 0.80

    cand = {
        "level2_component": {"recall@5": 0.7143},
        "level3_e2e": {
            "faithfulness": 0.85,
            "abstention_correctness": 1.0,
            "citation_validity": 1.0,
            "latency_p95_ms": 5000.0,
        },
    }
    res = gate_mod.evaluate_gate(cand, baseline=None, thresholds=thresholds)
    assert res["passed"] is False
    r5_chk = next(c for c in res["checks"] if c["rule"] == "recall@5_min")
    assert r5_chk["pass"] is False
    assert ">= 0.8000" in r5_chk["threshold"]


def test_release_gate_out_persists_decision_and_env_overrides(monkeypatch, tmp_path: Path):
    """release_gate.py --out writes passed, checks, applied thresholds, and baseline_file."""
    monkeypatch.setenv("GATE_FAITHFULNESS_MIN", "0.78")
    out_pass = tmp_path / "gate_pass.json"
    rc_pass = gate_mod.main(
        [
            "--candidate", "eval/results/candidate_pass.json",
            "--baseline", "eval/results/baseline_k8s.json",
            "--config", "eval/gate_thresholds.yaml",
            "--out", str(out_pass),
        ]
    )
    assert rc_pass == 0
    rec_pass = json.loads(out_pass.read_text(encoding="utf-8"))
    assert rec_pass["passed"] is True
    assert rec_pass["baseline_file"] == "eval/results/baseline_k8s.json"
    assert rec_pass["thresholds"]["faithfulness_min"] == 0.78
    assert isinstance(rec_pass["checks"], list) and all(c["pass"] for c in rec_pass["checks"])

    out_fail = tmp_path / "gate_fail.json"
    rc_fail = gate_mod.main(
        [
            "--candidate", "eval/results/candidate_fail.json",
            "--baseline", "eval/results/baseline_k8s.json",
            "--config", "eval/gate_thresholds.yaml",
            "--out", str(out_fail),
        ]
    )
    assert rc_fail == 1
    rec_fail = json.loads(out_fail.read_text(encoding="utf-8"))
    assert rec_fail["passed"] is False
    assert any(not c["pass"] for c in rec_fail["checks"])


def test_run_ragops_eval_persists_gate_out(monkeypatch, tmp_path: Path):
    """run_ragops_eval.py persists gate decision to --gate-out and defaults to gate_<label>_<ts>.json."""
    golden = eval_mod.load_jsonl(Path("eval/golden.jsonl"))[:2]
    g_path = tmp_path / "g.jsonl"
    g_path.write_text("\n".join(json.dumps(x) for x in golden) + "\n", encoding="utf-8")

    def fake_chat(api_base: str, question: str, follow_up: bool = True, timeout: int = 180):
        return {
            "trace_id": "t-gate",
            "latency_ms": 90.0,
            "answer": {
                "answer": "Students must maintain 80 percent attendance.",
                "citations": [{"source": "Academic_Rules_Handbook_2026.pdf", "section": "1.21", "page": 10}],
                "answered_from_context": True,
            },
            "retrieved_chunks": [
                {
                    "id": "c1",
                    "text": "Students must maintain 80 percent attendance in all courses.",
                    "metadata": {"source": "Academic_Rules_Handbook_2026.pdf", "section": "1.21", "page": 10},
                    "similarity": 0.91,
                }
            ],
            "guardrail_actions": [],
        }

    monkeypatch.setattr(eval_mod, "_call_chat", fake_chat)

    gate_out = tmp_path / "custom_gate.json"
    rc = eval_mod.main(
        [
            "--api-base", "http://fake",
            "--golden", str(g_path),
            "--pairs", "eval/module_pairs.jsonl",
            "--judge-labels", "",
            "--provider-mode", "stub",
            "--skip-noise-test",
            "--out-dir", str(tmp_path / "results"),
            "--label", "cand-test",
            "--gate-config", "eval/gate_thresholds.yaml",
            "--baseline", "eval/results/baseline_k8s.json",
            "--gate-out", str(gate_out),
        ]
    )
    assert rc == 0
    assert gate_out.is_file()
    gate_payload = json.loads(gate_out.read_text(encoding="utf-8"))
    assert gate_payload["label"] == "cand-test"
    assert gate_payload["baseline_file"] == "eval/results/baseline_k8s.json"
    assert "thresholds" in gate_payload and "checks" in gate_payload

    # Default path when --gate-out is omitted: <out-dir>/gate_<label>_<ts>.json
    auto_dir = tmp_path / "auto_results"
    rc_auto = eval_mod.main(
        [
            "--api-base", "http://fake",
            "--golden", str(g_path),
            "--pairs", "eval/module_pairs.jsonl",
            "--judge-labels", "",
            "--provider-mode", "stub",
            "--skip-noise-test",
            "--out-dir", str(auto_dir),
            "--label", "auto-lbl",
            "--gate-config", "eval/gate_thresholds.yaml",
        ]
    )
    assert rc_auto == 0
    gate_files = list(auto_dir.glob("gate_auto-lbl_*.json"))
    assert len(gate_files) == 1
    auto_payload = json.loads(gate_files[0].read_text(encoding="utf-8"))
    assert auto_payload["baseline_file"] is None
    assert any(c["rule"] == "recall@5_min" for c in auto_payload["checks"])
