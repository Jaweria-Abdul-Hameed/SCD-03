# Evaluation Results Directory

This directory stores committed JSON snapshots from the Part B/C/E/F evaluation runs.

## Canonical Aliases (Copies of Timestamped Runs)

Three shorthand files are exact byte-for-byte copies of specific timestamped evaluation runs so scripts, ConfigMaps (`EVAL_BASELINE_FILE: "/results/baseline_k8s.json"`), and documentation can reference stable paths:

- `baseline_k8s.json` — copy of `eval_k8s-eval_20261122T153617Z.json` (in-cluster baseline `api`, `grounded_v1`, `top_k=5`, `recall@5=0.7143`, `faithfulness=1.0`).
- `candidate_pass.json` — copy of `eval_candidate-pass_20261122T161336Z.json` (passing candidate `strict_concise_v2`, `top_k=5`, `recall@5=0.7143`, `faithfulness=0.8947`, `p95=4438.43 ms`).
- `candidate_fail.json` — copy of `eval_candidate-fail_20261122T161536Z.json` (renamed from mislabelled `eval_candidate-pass_20261122T161536Z.json`; failing candidate `bad_unconstrained_v0`, `top_k=1`, `recall@5=0.381`).

## Gate Decision Records

- `gate_candidate-pass_20261122T161336Z.json` — release gate output (`passed: true`) for `candidate_pass.json` vs `baseline_k8s.json`.
- `gate_candidate-fail_20261122T161536Z.json` — release gate output (`passed: false`) for `candidate_fail.json` vs `baseline_k8s.json`.

## Other Committed Runs

- `eval_baseline-stochasticity_20261122T155008Z.json` — dual fixed-seed stochasticity check on baseline.
- `eval_baseline-final_20261122T161035Z.json` — baseline run scored with LLM-as-judge (`dolphin-mistral:latest`).
- `eval_cm-flip-fail_20261122T161900Z.json` / `eval_cm-flip-pass_20261122T162326Z.json` — Part F2 ConfigMap threshold flip runs.
- `eval_post-batch-b_20261122T163228Z.json` — post-Batch-B re-evaluation.
- `coverage_pre_expansion.json` / `coverage_post_expansion.json` — Part E live-query coverage check outputs.
- `verification_batch_a.json` / `verification_batch_b.json` — retrieval verification probe outputs.
