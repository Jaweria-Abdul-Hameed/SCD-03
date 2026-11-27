# Evaluation Results Directory

This directory stores committed JSON and Markdown snapshots from the Part A/B/C/E/F evaluation runs.

## Canonical Aliases (Copies of Current In-Cluster 32-Question Runs)

Three shorthand files are exact byte-for-byte copies of specific timestamped in-cluster (`llm_judge` with `dolphin-mistral`, 32-question `eval/golden.jsonl`) evaluation runs so scripts, ConfigMaps (`EVAL_BASELINE_FILE: "/results/baseline_k8s.json"`), and documentation can reference stable paths:

- `baseline_k8s.json` — copy of `eval_baseline_20261127T204204Z.json` (in-cluster `http://api:8000`, `rahbar_corpus`, `v1`, `grounded_v1`, `top_k=5`, `recall@5=0.7143`, `faithfulness=0.8889`, `abstention_correctness=1.0`, `injection_resistance=1.0`, `citation_validity=1.0`, `p95=9700.48 ms`).
- `candidate_pass.json` — copy of `eval_candidate-pass_20261127T205104Z.json` (in-cluster `http://api-candidate:8000`, `rahbar_corpus_candidate`, `candidate-v2`, `strict_concise_v2`, `top_k=5`, `recall@5=0.7143`, `faithfulness=0.8000`, `abstention_correctness=1.0`, `injection_resistance=1.0`, `citation_validity=1.0`, `p95=6907.25 ms`).
- `candidate_fail.json` — copy of `eval_candidate-fail_20261127T205435Z.json` (in-cluster `http://api-candidate:8000`, `rahbar_corpus_candidate`, `candidate-fail-v0`, `bad_unconstrained_v0`, `top_k=1`, `recall@5=0.3810`, `faithfulness=0.7143`, `abstention_correctness=1.0`, `injection_resistance=1.0`, `citation_validity=1.0`, `p95=6951.88 ms`).

Sibling summary Markdown tables: `eval_baseline_20261127T204204Z.md`, `eval_candidate-pass_20261127T205104Z.md`, and `eval_candidate-fail_20261127T205435Z.md`.

## Gate Decision Records & C1 Comparison

- `gate_baseline_20261127T204204Z.json` — standalone release gate record (`passed: true`) for `eval_baseline_20261127T204204Z.json`.
- `gate_candidate-pass_20261127T205104Z.json` — release gate output (`passed: true`) for `candidate_pass.json` vs `baseline_k8s.json`.
- `gate_candidate-fail_20261127T205435Z.json` — release gate output (`passed: false`; failed `recall@5_max_drop_vs_baseline` and `faithfulness_min`) for `candidate_fail.json` vs `baseline_k8s.json`.
- `c1_baseline_vs_candidates.json` — like-for-like Part C1 comparison covering all three evaluation levels, config variants, deltas vs `baseline_k8s.json`, per-question differences, and release gate decisions.

## Other Current Committed Runs (32-Question Golden Set & Part A/E Artifacts)

- `eval_baseline-final_20261127T203100Z.json` / `.md` and `gate_baseline-final_20261127T203100Z.json` — Part B dual fixed-seed stochasticity run (`--stochasticity-runs 2`, `llm_judge` with `dolphin-mistral:latest`).
- `coverage_pre_expansion.json` / `coverage_post_expansion.json` / `coverage_threshold_analysis.json` — Part E live-query coverage check outputs and `0.70` similarity threshold analysis.
- `verification_batch_a_initial.json` / `verification_batch_a.json` / `verification_batch_b.json` / `verification_batch_b_rerun.json` — Part A ingestion and verification reports.
- `a2_changed_document.json` / `a2_deleted_document.json` / `rollback_academic_rules_handbook.json` — Part A2 update, delete, and rollback records.
- `e3_drift_batch_b_diff.json` — Part E3 Batch B drift diff (comparing historical Nov 22 baseline vs post-Batch-B run).

## Historical Runs (Nov 22, 26-Question Golden Set)

Kept for historical comparison against the initial 26-question golden set:

- `eval_k8s-eval_20261122T153617Z.json` — historical Nov 22 in-cluster baseline (`lexical_overlap`, 26 questions, `faithfulness=1.0`, `p95=5881.03 ms`).
- `eval_candidate-pass_20261122T161336Z.json` and `gate_candidate-pass_20261122T161336Z.json` — historical Nov 22 passing candidate (`lexical_overlap`, 26 questions, `faithfulness=0.8947`, `p95=4438.43 ms`).
- `eval_candidate-fail_20261122T161536Z.json` and `gate_candidate-fail_20261122T161536Z.json` — historical Nov 22 failing candidate (renamed from mislabelled `eval_candidate-pass_20261122T161536Z.json`; `lexical_overlap`, 26 questions, `recall@5=0.381`).
- `eval_baseline-stochasticity_20261122T155008Z.json` — historical Nov 22 dual fixed-seed stochasticity check on baseline (`llama3.2:3b` judge).
- `eval_baseline-final_20261122T161035Z.json` — historical Nov 22 local port-forward baseline run scored with LLM-as-judge (`dolphin-mistral:latest`, 26 questions, `p95=12101 ms`).
- `eval_cm-flip-fail_20261122T161900Z.json` / `eval_cm-flip-pass_20261122T162326Z.json` — historical Nov 22 Part F2 ConfigMap threshold flip runs.
- `eval_post-batch-b_20261122T163228Z.json` — historical Nov 22 post-Batch-B re-evaluation.
