# RAHBAR — Grounded RAG on Kubernetes (CS4032 Assignment 03: RAGOps)

> **Software Construction and Development (CS4032) — Assignment 03 (RAGOps)**  
> **Authors:** Jaweria Abdul Hameed (`jaweriahameed06@gmail.com`) • Mohsin Khan (`mohsinkhan.devs@gmail.com`)  
> **Assignment Specification:** [assignment_03.md](assignment_03.md)  
> **Technical Report PDF:** [Report_CS4032_Assignment03.pdf](Report_CS4032_Assignment03.pdf)  
> **Kubernetes Guide:** [k8s/README.md](k8s/README.md)  
> **Evaluation Results Index:** [eval/results/README.md](eval/results/README.md)  
> **Paper Foundation:** *RAGOps: Operating and Managing Retrieval-Augmented Generation Pipelines* (Xu et al., 2026)

---

## Assignment 03 (RAGOps) Implementation Highlights

1. **Part A: Data Management & Verification (Paper §§4.2.1–4.2.4)**
   - 4 pre-chunking verification gates (`indexer/pipeline/verify.py`): `quality`, `completeness`, `recency`, and `uniqueness` (SHA-256 content hash + `0.94` cosine near-duplicate threshold via `NEAR_DUP_THRESHOLD`).
   - Failing documents are quarantined to `/corpus/quarantine/` with structured JSON verification reports; `0` polluted chunks enter Chroma.
   - Initial Batch A ingestion (`eval/results/verification_batch_a_initial.json`): `15` scanned, `15` passed (`6` superseded archived), **`480` chunks embedded** (`221` active / `259` superseded). Unchanged Batch A re-run (`eval/results/verification_batch_a.json`): `docs_scanned: 15`, `docs_skipped_unchanged: 15`, **`chunks_embedded: 0`**.
   - Batch B (`corpus/batch_b/`, `11` files; `eval/results/verification_batch_b.json`) caught `6` planted defective documents (`b04`–`b09`: exact duplicates `b04_exact_dup_scholarship.md` and `b05_exact_dup_research_grant.md`, near-duplicate `b06_near_dup_scholarship.md`, corrupt PDF `b07_corrupt_file.pdf`, truncated `b08_truncated_policy.md`, and missing metadata `b09_missing_metadata.md`); indexed `5` passing documents (`chunks_embedded: 6`); and `b10_academic_rules_handbook_nov2026.md` (`2026-11`) superseded active `2026-06` rules (`Academic_Rules_Handbook_2026.pdf`). Batch B idempotency re-run (`eval/results/verification_batch_b_rerun.json`): `5` skipped, `6` quarantined, **`chunks_embedded: 0`**.
   - Incremental update (`eval/results/a2_changed_document.json`: `Grading_page.html` updated `3 → 4` chunks, `chunks_deleted: 3`, `chunks_embedded: 4`), deletion (`eval/results/a2_deleted_document.json`: `Faculty_Entrepreneurship_Technical_Startups_Policy.pdf` `7 → 0` chunks, `chunks_deleted: 7`, `0` orphan chunks), and in-cluster version rollback via `k8s/rollback-job.yaml` (`python -m pipeline.rollback` under `indexer-sa`; `eval/results/rollback_academic_rules_handbook.json` + `traces/a2_rollback_traces.jsonl`: `academic_rules_handbook` rolled back `2026-11 → 2026-06`, archiving `2` chunks and restoring `39` chunks).

2. **Part B: 3-Level Offline Evaluation Suite (Paper §4.2.5 & Table 1)**
   - Single-command runner (`eval/run_ragops_eval.py`) using `eval/golden.jsonl` (`32` questions: `16` `answerable`, `11` `unanswerable`, `5` `hard`; `18` `human`, `14` `synthetic`) and `eval/module_pairs.jsonl` (`16` paraphrase + `16` unrelated pairs), reported below on the full `32`-question in-cluster suite (`eval/results/eval_baseline-final_20261127T203100Z.json` and `eval/results/baseline_k8s.json` = `eval_baseline_20261127T204204Z.json`).
   - **Level 1 (Module):** Cosine separation gap = `0.2891` (`0.7721` paraphrase mean vs `0.4830` unrelated mean), determinism max abs diff = `0.00000000` (`cosine = 1.0`), embedding time = `68.15 ms` / `96.83 ms` (Run 1 / Run 2 in `eval/results/eval_baseline-final_20261127T203100Z.json`) and `84.63 ms` (`eval/results/baseline_k8s.json`).
   - **Level 2 (Component):** `recall@3 = 0.5714`, `recall@5 = 0.7143`, `MRR = 0.4913`, `nDCG@5 = 0.5460` (`21` evaluated queries); query-typo noise test: `noisy_recall@3 = 0.6667` (`+0.0952`), `noisy_recall@5 = 0.7143` (`+0.0000`), `noisy_MRR = 0.5810` (`+0.0897`), `noisy_nDCG@5 = 0.6137` (`+0.0676`).
   - **Level 3 (E2E):**
     - Dual fixed-seed in-cluster run (`dolphin-mistral:latest` judge, `--stochasticity-runs 2`, `eval/results/eval_baseline-final_20261127T203100Z.json`): faithfulness = `0.8889` (`18` grounded answered), human agreement = **`100.0%` (`10/10`)**, abstention correctness = `1.0000` (`11/11`), injection resistance = `1.0000` (`1/1`), citation validity = `1.0000` (`18` citations), `p50 = 4950.85 ms`, `p95 = 7753.70 ms` (`7.75 s`; Run 2: `p50 = 5150.64 ms`, `p95 = 10199.15 ms`).
     - Canonical in-cluster baseline (`eval/results/baseline_k8s.json`, alias of `eval/results/eval_baseline_20261127T204204Z.json`, `dolphin-mistral`): faithfulness = `0.8889` (`18` grounded answered), human agreement = `100.0%` (`10/10`), abstention correctness = `1.0000` (`11/11`), injection resistance = `1.0000` (`1/1`), citation validity = `1.0000` (`18` citations), `p50 = 4616.17 ms`, `p95 = 9700.48 ms` (`9.70 s`).
   - **Stochasticity Analysis:** Fixed `seed=42` (`eval/results/eval_baseline-final_20261127T203100Z.json`) yielded `0.0000` variation across all Level 1 cosine/determinism, Level 2 retrieval/noise, and Level 3 quality metrics (with minor embed-timing/latency jitter: `Δ embed = +28.68 ms`, `Δ p50 = +199.79 ms`, `Δ p95 = +2445.45 ms`).

3. **Part C: Change Experiment & Automated Release Gate (Paper §4.1(d), §§4.2.5–4.2.6)**
   - Isolated candidate collection (`rahbar_corpus_candidate`), Deployment (`api-candidate`), and Service (`api-candidate:8000`) via `k8s/indexer-candidate-job.yaml` and `k8s/candidate-deployment.yaml`, with like-for-like 32-question comparison recorded in `eval/results/c1_baseline_vs_candidates.json`.
   - Evaluated passing candidate (`COLLECTION_VERSION=candidate-v2`, `PROMPT_TEMPLATE=strict_concise_v2`, `TOP_K=5` in `eval/results/candidate_pass.json` and `eval/results/gate_candidate-pass_20261127T205104Z.json` against `eval/results/baseline_k8s.json`): `recall@5 = 0.7143` (drop `+0.0000` ≤ `0.0200`), faithfulness = `0.8000` (`80.00%`, `15` grounded), `p50 = 2735.12 ms`, `p95 = 6907.25 ms` (`-28.79%` vs `9700.48 ms`), abstention = `1.0000` (`11/11`), injection = `1.0000` (`1/1`), citation validity = `1.0000` (`18` citations) → **`GATE RESULT: PASS` (Exit `0`)**.
   - Evaluated degraded candidate (`TOP_K=1`, `PROMPT_TEMPLATE=bad_unconstrained_v0`, `COLLECTION_VERSION=candidate-fail-v0` via `k8s/candidate-fail-config.yaml` in `eval/results/candidate_fail.json` and `eval/results/gate_candidate-fail_20261127T205435Z.json`): `recall@5 = 0.3810` (`drop = +0.3333 > 0.0200` threshold) and `faithfulness = 0.7143` (`< 0.7500` threshold; `p95 = 6951.88 ms`) → **`GATE RESULT: FAIL` (Exit `1`)**.

4. **Part D: Observability, Traceability & Safety Rails (Paper §§3.2.3, 5.1)**
   - Every `/chat` request emits a structured JSONL trace record (`api/app/services/tracing.py`, `21` keys including `trace_id`, `timestamp`, `user_query`, `rewritten_query`, `embedding_model`, `embedding_version`, `collection_name`, `collection_version`, `retrieved_chunks`, `filters_applied`, `reranked_order`, `prompt_hash`, `full_prompt`, `model`, `parameters`, `response`, `citations`, `guardrail_actions`, `latency_per_stage`, `cache_hit`) to `stdout` and `TRACE_FILE` (`/traces/traces.jsonl`) with SHA-256 `prompt_hash`.
   - `scripts/trace_tool.py`: Reconstructs exact retrieved `<context>` blocks and `full_prompt`, and verifies the SHA-256 `prompt_hash` for any `trace_id` (root-cause trace documented in `traces/d5_root_cause_trace.jsonl` and `traces/d5_trace_tool_output.txt` for `8b0dbee2-c05c-4891-9e49-f71833d95eca`).
   - `scripts/summarize_traces.py`: Aggregates top-1 similarity distribution, abstention rate, cache hit rate, injection flags, and p50/p95 latency across 8 pipeline stages over a time window (`traces/metrics_summary_24h.json`: `322` queries, `31.68%` abstention rate (`102/322`), `9.63%` cache hit rate (`31/322`), `16` flagged injection attempts = `12` input + `4` retrieval, `p50 total = 2515.419 ms`, `p95 total = 8320.453 ms`).
   - Dual-rail prompt injection defense (`api/app/services/guardrails.py`): Input Rail (`I`) flagged `12` query-level attempts and Retrieval Rail (`R`) caught and redacted/excluded Batch B's poisoned document (`b11_library_fine_addendum_injected.md`, `4` triggers in `traces/traces.jsonl`).

5. **Part E: Drift & Query Coverage Checking (Paper §4.1(e), §4.2.7)**
   - Live query coverage tool (`eval/coverage_check.py`): measures cosine similarity of `eval/live_queries.jsonl` (`42` queries) against `eval/golden.jsonl` (`--sim-threshold 0.70`, `--coverage-threshold 0.85`; threshold calibrated in `eval/results/coverage_threshold_analysis.json`).
   - Pre-expansion baseline failed gate (`eval/results/coverage_pre_expansion.json`): **`59.52%` coverage (`25/42`)**, `17` uncovered queries grouped into `4` named topics (`alumni_and_degree_verification`, `campus_facilities_and_services`, `career_services_and_internships`, `international_exchange_and_transfers`) plus `other_uncovered` (`L03`, `L25`, `L26`) → **FAIL (Exit `1`)**.
   - Expanded `eval/golden.jsonl` by `6` questions (`26 → 32`, `G27`–`G32`); coverage rose to **`85.71%` (`36/42`)** (`eval/results/coverage_post_expansion.json`) → **PASS (Exit `0`)**.
   - E3 Batch B drift diff (`eval/results/e3_drift_batch_b_diff.json`): compares `eval/results/baseline_k8s.json` (`eval_baseline_20261127T204204Z.json`) with `eval/results/eval_post-batch-b_20261127T212505Z.json` (`eval/results/gate_post-batch-b_20261127T212505Z.json` failed `recall@5_max_drop_vs_baseline`: `recall@3` `0.5714 → 0.6190`, `recall@5` `0.7143 → 0.6190`, `23` changed questions documented; re-scoring against `relevant_document_after_batch_b` restores `recall@5` to **`0.9524`** on `21` queries and **`1.0000`** on `20` queries excluding `G18`).

6. **Part F: Kubernetes Native Architecture & Zero-Downtime Rollout (Paper §§4.1(e–f), 5.1)**
   - Runs natively on Minikube with Calico CNI in namespace `rahbar` (`k8s/base/namespace.yaml`).
   - Single-writer isolation: `indexer-sa` (`indexer` Job, `indexer-batch-b`, `indexer-candidate`, `indexer-rollback`, and `reindex` CronJob with `concurrencyPolicy: Forbid`) owns all Chroma writes; `api-sa` (`api` and `api-candidate`) opens Chroma read-only (`get_collection` + `collection.query(...)` in `api/app/retrieval/retriever.py`), with network paths enforced by Calico `NetworkPolicy` (`k8s/base/networkpolicy.yaml`).
   - ConfigMap live-edit gate flip (`k8s/gate-configmap.yaml`): patched `GATE_P95_LATENCY_MAX_MS: "500.0"` → `eval-job` FAILED (`eval/results/eval_cm-flip-fail_20261122T161900Z.json`); restored to `"45000.0"` → `eval-job` PASSED (`eval/results/eval_cm-flip-pass_20261122T162326Z.json`) without container rebuild.
   - Candidate gate block (`docs/evidence/ragops/f3_candidate_blocked.txt`): `eval-job-candidate` (`eval/results/gate_candidate-fail_20261127T205435Z.json`) failed (`recall@5 = 0.3810`, `faithfulness = 0.7143`) and blocked promotion while `deployment/api` remained undisturbed at revision `1`.
   - Manifest-committed candidate promotion (`k8s/patches/promote-candidate.yaml`, `PROMPT_TEMPLATE=strict_concise_v2`) via zero-downtime rolling update (`maxUnavailable: 0`, `kubectl rollout status deployment/api -n rahbar`) and instant rollback (`kubectl rollout undo deployment/api -n rahbar`, verified in `docs/evidence/ragops/f3_rollout_undo.txt` and `traces/f3_rollback_traces.jsonl`) restoring pinned Pod-template versions (`COLLECTION_VERSION=v1`, `PROMPT_TEMPLATE=grounded_v1`, `TOP_K=5`).
   - F4/F5 cluster evidence: per-replica `ragops_trace` JSONL logs (`docs/evidence/ragops/f4_kubectl_logs_traces.txt`), Prometheus `/metrics` (`docs/evidence/ragops/f4_metrics_port_forward.txt`), and container resource measurements (`docs/evidence/ragops/f5_resource_measurements.txt`: `api` `3.0m` p50 CPU / `78.0Mi` p50 mem; `chroma-0` `7.0m` / `158.5Mi` under eval and `10.0m` / `150.0Mi` under 480-chunk index; `indexer-candidate` `760.5m` p50 / `998m` max CPU and `176.5Mi` p50 / `198Mi` max mem; `eval-job` `1.0m` / `30.0Mi`; `redis` `4.0m` / `4.0Mi`; `ui` `1.0m` / `2.0Mi`).

---

## Overview

**RAHBAR** is a grounded question-answering service that answers **only from a verified university document corpus**, cites its sources, abstains when evidence is absent, and operates with full RAGOps lifecycle controls on Kubernetes.

- **Corpus:** Public FAST-NUCES documents listed in [corpus/MANIFEST.md](corpus/MANIFEST.md) (`15` Batch A documents, `390` pages; PDFs/HTML are not committed — run `scripts/fetch_corpus.py` to download into `corpus/raw/`), plus `11` committed Batch B test documents in `corpus/batch_b/` (planted defects, version superseding, and prompt-injection test). Deliberately absent topic: transport/hostel rules (the service must abstain). Details: [docs/CORPUS.md](docs/CORPUS.md).
- **Single-writer & embedding pin:** Only the indexer Jobs (`indexer-sa`) write to Chroma (`chroma:8000`); the API pods (`api-sa`) only read it, and both read `EMBED_MODEL=nomic-embed-text` (`768` dimensions) from `rahbar-config` (`k8s/base/configmap.yaml`). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/adr/0004-embedding-pin.md](docs/adr/0004-embedding-pin.md).
- **Evaluation:**
  - **Assignment 03 (RAGOps 3-level suite):** `eval/golden.jsonl` (`32` questions), `eval/module_pairs.jsonl` (`32` pairs), `eval/run_ragops_eval.py`, `eval/release_gate.py`, `eval/gate_thresholds.yaml`, and `eval/coverage_check.py`, with committed result snapshots and gate decisions under `eval/results/` ([eval/results/README.md](eval/results/README.md)).
  - **Legacy CI regression gate:** `eval/golden.yaml` (`15` questions), `eval/run_eval.py`, `eval/baseline.json`, and `eval/results.json` (plus fixture gate `eval/golden.fixture.yaml` + `eval/baseline.fixture.json` used by `.github/workflows/ci.yml` `e2e-eval` and checked by `scripts/check_submission.py`).

---

## Prerequisites

- Docker, `kubectl` (v1.31+ with built-in `kubectl kustomize`), `minikube` (v1.34+ with Docker driver)
- Ollama on your host (`ollama-host` mode, default in `k8s/overlays/host-gpu-ollama`) with the three models pulled:
  ```bash
  ollama pull llama3.2:3b
  ollama pull nomic-embed-text
  ollama pull dolphin-mistral:latest
  ```
- Python 3.12 (for `scripts/check_submission.py`, `pytest`, and local evaluation/trace/coverage scripts)

---

## How to Run Each Part (A–F)

### Part A — Data Management, Verification & Incremental Update

Run ingestion inside Kubernetes (`indexer-sa` is the sole Chroma writer; never index from a laptop against cluster Chroma). Ensure the cluster and `pvc-helper` are up (see Part F Steps 1–3 first).

1. **Fetch Batch A and copy it to the `corpus-data` PVC before running the Job:**
   ```bash
   python scripts/fetch_corpus.py
   kubectl exec pvc-helper -n rahbar -- mkdir -p /corpus/raw
   kubectl cp corpus/raw/. rahbar/pvc-helper:/corpus/raw/
   ```
2. **Run initial Batch A verification & indexing Job** (substitute `:SHA` with `:local`; never apply raw `k8s/base/indexer-job.yaml` without substitution):
   - **Bash:**
     ```bash
     TAG=local
     kubectl delete job indexer -n rahbar --ignore-not-found
     sed "s/:SHA/:$TAG/g" k8s/base/indexer-job.yaml | kubectl apply -f -
     kubectl wait --for=condition=complete job/indexer -n rahbar --timeout=600s
     kubectl logs job/indexer -n rahbar
     ```
   - **Windows PowerShell:**
     ```powershell
     $tag = "local"
     kubectl delete job indexer -n rahbar --ignore-not-found
     (Get-Content k8s/base/indexer-job.yaml) -replace ':SHA', ":$tag" | kubectl apply -f -
     kubectl wait --for=condition=complete job/indexer -n rahbar --timeout=600s
     kubectl logs job/indexer -n rahbar
     ```
3. **Verify idempotent re-run on unchanged corpus (`chunks_embedded: 0`):**
   ```bash
   kubectl create job --from=cronjob/reindex reindex-unchanged-1 -n rahbar
   kubectl wait --for=condition=complete job/reindex-unchanged-1 -n rahbar --timeout=300s
   kubectl logs job/reindex-unchanged-1 -n rahbar
   ```
4. **Ingest Batch B (`corpus/batch_b/`) in additive mode (`--additive`):**
   ```bash
   kubectl cp corpus/batch_b/. rahbar/pvc-helper:/corpus/batch_b
   kubectl delete job indexer-batch-b -n rahbar --ignore-not-found
   kubectl apply -f k8s/indexer-batch-b-job.yaml
   kubectl wait --for=condition=complete job/indexer-batch-b -n rahbar --timeout=180s
   kubectl logs job/indexer-batch-b -n rahbar
   ```
5. **Restore an archived superseded document version (`k8s/rollback-job.yaml`):**
   ```bash
   kubectl delete job indexer-rollback -n rahbar --ignore-not-found
   kubectl apply -f k8s/rollback-job.yaml
   kubectl wait --for=condition=complete job/indexer-rollback -n rahbar --timeout=180s
   kubectl logs job/indexer-rollback -n rahbar
   ```
6. **Local CLI flags (development against local Chroma/Ollama):**
   ```bash
   # Ingestion + 4-gate verification (from repo root)
   python indexer/main.py --corpus-dir corpus/raw --data-root corpus --print-summary --report-out eval/results/verification_batch_a.json
   python indexer/main.py --corpus-dir corpus/batch_b --data-root corpus --additive --print-summary --report-out eval/results/verification_batch_b.json
   ```
   - **Rollback CLI (Bash):**
     ```bash
     PYTHONPATH=indexer python -m pipeline.rollback --doc-id academic_rules_handbook --to-version 2026-06 --data-root corpus
     ```
   - **Rollback CLI (Windows PowerShell):**
     ```powershell
     $env:PYTHONPATH="indexer"; python -m pipeline.rollback --doc-id academic_rules_handbook --to-version 2026-06 --data-root corpus
     ```

### Part B — 3-Level Offline Evaluation Suite & Unit Tests

1. **Run offline unit tests (stub provider, no cluster or Ollama required):**
   - **Windows PowerShell:**
     ```powershell
     $env:LLM_PROVIDER="stub"; $env:EMBED_MODEL="nomic-embed-text"; pytest api/tests indexer/tests eval/
     ```
   - **Bash:**
     ```bash
     LLM_PROVIDER=stub EMBED_MODEL=nomic-embed-text pytest api/tests indexer/tests eval/
     ```
   *(CI also enforces ≥60% coverage on `api/app` via `pytest api/tests indexer/tests --cov=api/app --cov-fail-under=60`.)*

2. **Run the 3-level evaluation suite locally against a port-forwarded API (`eval/run_ragops_eval.py`):**
   ```bash
   # In terminal 1:
   kubectl port-forward svc/api 8000:8000 -n rahbar

   # In terminal 2:
   python eval/run_ragops_eval.py \
     --api-base http://127.0.0.1:8000 \
     --golden eval/golden.jsonl \
     --pairs eval/module_pairs.jsonl \
     --judge-labels eval/judge_human_labels.jsonl \
     --ollama-host 127.0.0.1:11434 \
     --embed-model nomic-embed-text \
     --llm-model llama3.2:3b \
     --judge-model dolphin-mistral:latest \
     --provider-mode ollama-host \
     --llm-judge \
     --seed 42 \
     --stochasticity-runs 2 \
     --label baseline-final \
     --out-dir eval/results
   ```
   This outputs both a timestamped JSON file (`eval/results/eval_<label>_<ts>.json`) and a sibling Markdown summary table (`eval/results/eval_<label>_<ts>.md`). To run inside Kubernetes as a Job, apply `k8s/eval-job.yaml` (see Part F).

### Part C — Change Experiment & Automated Release Gate

1. **Run the standalone release gate (`eval/release_gate.py`) against `eval/gate_thresholds.yaml`:**
   ```bash
   # Passing candidate (strict_concise_v2, TOP_K=5) -> exits 0
   python eval/release_gate.py \
     --candidate eval/results/candidate_pass.json \
     --baseline eval/results/baseline_k8s.json \
     --config eval/gate_thresholds.yaml \
     --out eval/results/gate_candidate-pass.json

   # Failing candidate (bad_unconstrained_v0, TOP_K=1) -> exits 1
   python eval/release_gate.py \
     --candidate eval/results/candidate_fail.json \
     --baseline eval/results/baseline_k8s.json \
     --config eval/gate_thresholds.yaml \
     --out eval/results/gate_candidate-fail.json
   ```
   Supported environment overrides (mirrored in `k8s/gate-configmap.yaml`): `GATE_RECALL5_MAX_DROP_PP`, `GATE_RECALL5_MIN`, `GATE_FAITHFULNESS_MIN`, `GATE_P95_LATENCY_MAX_MS`, `GATE_ABSTENTION_MIN_DELTA`, `GATE_ABSTENTION_MIN`, `GATE_INJECTION_RESISTANCE_MIN`, `GATE_CITATION_VALIDITY_MIN`.

2. **Evaluate and enforce the gate in one pass (`eval/run_ragops_eval.py`):**
   Pass `--gate-config eval/gate_thresholds.yaml --baseline eval/results/baseline_k8s.json --gate-out eval/results/gate_candidate.json --enforce-gate`.

3. **Run the isolated cluster candidate experiment (`api-candidate` + `eval-job-candidate`):**
   ```bash
   # Index candidate collection (`rahbar_corpus_candidate`) & deploy `api-candidate`
   kubectl apply -f k8s/indexer-candidate-job.yaml
   kubectl wait --for=condition=complete job/indexer-candidate -n rahbar --timeout=600s
   kubectl apply -f k8s/candidate-deployment.yaml
   kubectl rollout status deployment/api-candidate -n rahbar --timeout=180s

   # Run evaluation Job against `http://api-candidate:8000` (passing gate)
   kubectl delete job eval-job-candidate -n rahbar --ignore-not-found
   kubectl apply -f k8s/eval-job-candidate.yaml
   kubectl wait --for=condition=complete job/eval-job-candidate -n rahbar --timeout=600s
   kubectl logs job/eval-job-candidate -n rahbar

   # Reproduce failing candidate gate (`TOP_K=1`, `bad_unconstrained_v0`), then restore
   kubectl apply -f k8s/candidate-fail-config.yaml
   kubectl rollout restart deployment/api-candidate -n rahbar
   kubectl rollout status deployment/api-candidate -n rahbar --timeout=180s
   kubectl delete job eval-job-candidate -n rahbar --ignore-not-found
   kubectl apply -f k8s/eval-job-candidate.yaml
   kubectl logs job/eval-job-candidate -n rahbar
   kubectl apply -f k8s/candidate-deployment.yaml
   ```

### Part D — Observability, Traceability & Guardrail Summarization

1. **Inspect a single trace record & verify its SHA-256 `prompt_hash` (`scripts/trace_tool.py`):**
   ```bash
   python scripts/trace_tool.py <trace_id> --trace-file traces/traces.jsonl
   ```
   Or inspect directly from live `api` pod logs:
   ```bash
   kubectl logs deployment/api -n rahbar | python scripts/trace_tool.py <trace_id> --trace-file -
   ```
2. **Summarize trace metrics over a time window (`scripts/summarize_traces.py`):**
   ```bash
   python scripts/summarize_traces.py --trace-file traces/traces.jsonl --window 24h --out traces/metrics_summary_24h.json
   ```
   (`--window` accepts durations like `30m`, `24h`, `7d`, or `all`.)
3. **Tail traces on the PVC and inspect Prometheus `/metrics`:**
   ```bash
   kubectl exec pvc-helper -n rahbar -- tail -n 5 /traces/traces.jsonl
   kubectl cp rahbar/pvc-helper:/traces/traces.jsonl traces/traces.jsonl
   kubectl port-forward svc/api 8000:8000 -n rahbar
   curl http://127.0.0.1:8000/metrics
   ```

### Part E — Drift & Query Coverage Checking

1. **Check live query coverage against `eval/golden.jsonl` (`eval/coverage_check.py`):**
   ```bash
   python eval/coverage_check.py \
     --live-queries eval/live_queries.jsonl \
     --golden eval/golden.jsonl \
     --sim-threshold 0.70 \
     --coverage-threshold 0.85 \
     --out eval/results/coverage_post_expansion.json
   ```
   Exits `0` when coverage ≥ `--coverage-threshold`, or `1` when below threshold. Add `--provider-mode stub` for offline/CI runs without Ollama.

### Part F — Kubernetes Deployment, Live Gate Flip, Promotion & Rollback

See [k8s/README.md](k8s/README.md) for the complete cluster walkthrough. Summary of exact commands:

1. **Check submission mechanics & start Minikube with Calico CNI:**
   ```bash
   python scripts/check_submission.py
   minikube start --driver=docker --cni=calico --memory=6144 --cpus=4
   minikube addons enable metrics-server
   minikube addons enable ingress
   ```
2. **Build and load all 4 `:local` images into Minikube (`api`, `ui`, `indexer`, `eval`):**
   ```bash
   docker build -t ghcr.io/rahbar/api:local ./api
   docker build -t ghcr.io/rahbar/ui:local ./ui
   docker build -t ghcr.io/rahbar/indexer:local ./indexer
   docker build -f eval/Dockerfile -t ghcr.io/rahbar/eval:local .

   minikube image load ghcr.io/rahbar/api:local
   minikube image load ghcr.io/rahbar/ui:local
   minikube image load ghcr.io/rahbar/indexer:local
   minikube image load ghcr.io/rahbar/eval:local
   ```
   *(Or `make images-local` on Bash/Make.)*

3. **Deploy base manifests, PVCs, `pvc-helper`, and `host-gpu-ollama` overlay (substituting `:SHA`):**
   - **Bash:**
     ```bash
     TAG=local
     kubectl apply -f k8s/base/namespace.yaml
     kubectl apply -f k8s/base/serviceaccounts.yaml
     kubectl apply -f k8s/base/ragops-pvcs.yaml
     kubectl apply -f k8s/pvc-helper-pod.yaml
     kubectl kustomize k8s/overlays/host-gpu-ollama | sed "s/:SHA/:$TAG/g" | kubectl apply -f -
     kubectl wait --for=condition=Ready pod/pvc-helper -n rahbar --timeout=120s
     ```
   - **Windows PowerShell:**
     ```powershell
     $tag = "local"
     kubectl apply -f k8s/base/namespace.yaml
     kubectl apply -f k8s/base/serviceaccounts.yaml
     kubectl apply -f k8s/base/ragops-pvcs.yaml
     kubectl apply -f k8s/pvc-helper-pod.yaml
     (kubectl kustomize k8s/overlays/host-gpu-ollama) -replace ':SHA', ":$tag" | kubectl apply -f -
     kubectl wait --for=condition=Ready pod/pvc-helper -n rahbar --timeout=120s
     ```

4. **Populate corpus and run indexing (Part A Steps 1–2), then seed `/results/baseline_k8s.json`:**
   ```bash
   kubectl apply -f k8s/gate-configmap.yaml
   kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"EVAL_LABEL":"baseline"}}'
   kubectl delete job eval-job -n rahbar --ignore-not-found
   kubectl apply -f k8s/eval-job.yaml
   kubectl wait --for=condition=complete job/eval-job -n rahbar --timeout=600s
   kubectl exec pvc-helper -n rahbar -- sh -c 'cp "$(ls -t /results/eval_baseline_*.json | head -n1)" /results/baseline_k8s.json'
   kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"EVAL_LABEL":"k8s-eval"}}'
   ```

5. **Run live evaluation Job (`k8s/eval-job.yaml`) and candidate evaluation Job (`k8s/eval-job-candidate.yaml`):**
   ```bash
   # Live API evaluation
   kubectl delete job eval-job -n rahbar --ignore-not-found
   kubectl apply -f k8s/eval-job.yaml
   kubectl wait --for=condition=complete job/eval-job -n rahbar --timeout=600s
   kubectl logs job/eval-job -n rahbar

   # Candidate API evaluation (after applying k8s/indexer-candidate-job.yaml + k8s/candidate-deployment.yaml)
   kubectl delete job eval-job-candidate -n rahbar --ignore-not-found
   kubectl apply -f k8s/eval-job-candidate.yaml
   kubectl wait --for=condition=complete job/eval-job-candidate -n rahbar --timeout=600s
   kubectl logs job/eval-job-candidate -n rahbar
   ```

6. **ConfigMap live-edit gate flip (no image rebuild):**
   ```bash
   kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"GATE_P95_LATENCY_MAX_MS":"500.0"}}'
   kubectl delete job eval-job -n rahbar --ignore-not-found
   kubectl apply -f k8s/eval-job.yaml
   kubectl logs job/eval-job -n rahbar

   kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"GATE_P95_LATENCY_MAX_MS":"45000.0"}}'
   kubectl delete job eval-job -n rahbar --ignore-not-found
   kubectl apply -f k8s/eval-job.yaml
   kubectl wait --for=condition=complete job/eval-job -n rahbar --timeout=600s
   ```

7. **Zero-downtime promotion (`k8s/patches/promote-candidate.yaml`) and instant rollback:**
   ```bash
   kubectl patch deployment/api -n rahbar --patch-file k8s/patches/promote-candidate.yaml
   kubectl rollout status deployment/api -n rahbar --timeout=300s

   # Instant rollback (restores prior ReplicaSet image & pinned collection/embed/prompt env)
   kubectl rollout undo deployment/api -n rahbar
   kubectl rollout status deployment/api -n rahbar --timeout=300s
   ```

8. **Verify cluster state, query via `port-forward` / Ingress, and copy PVC artifacts locally:**
   ```bash
   kubectl get all,pvc,configmap,cronjob,job -n rahbar
   kubectl logs deployment/api -n rahbar --tail=10
   kubectl port-forward svc/api 8000:8000 -n rahbar
   kubectl cp rahbar/pvc-helper:/traces/traces.jsonl traces/traces.jsonl
   kubectl cp rahbar/pvc-helper:/results eval/results
   ```

---

## Apply order (clean clone)

Follow Steps 1–4 of **Part F** above (`host-gpu-ollama` overlay, or `incluster-ollama` below), then verify the live API through `port-forward` or Ingress (`Host: rahbar.local` in `k8s/base/ingress.yaml`):

```bash
kubectl get pods -n rahbar            # api should be 3/3 READY
kubectl port-forward svc/api 8000:8000 -n rahbar

# In another terminal:
curl http://127.0.0.1:8000/readyz
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Can a student register for a course after failing its prerequisite?"}'
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the hostel allotment rules for first-year students?"}'
```

*(If creating `rahbar-secret` for a hosted LLM provider, run `kubectl create secret generic rahbar-secret -n rahbar --from-literal=LLM_API_KEY="<your-key>"` after applying the overlay; never apply any `*-secret.yaml` placeholder over it.)*

## Alternative: Ollama inside the cluster (`ollama-incluster`)

If the cluster cannot reach Ollama on your laptop, apply `k8s/overlays/incluster-ollama` instead of `k8s/overlays/host-gpu-ollama`. It adds an Ollama Deployment + PVC (`LLM_PROVIDER=ollama-incluster`, `OLLAMA_NUM_THREAD=4`, `LLM_TIMEOUT_S=400`, and NetworkPolicies allowing `api`/`indexer` → `ollama:11434`), requiring an 8 GB / 6 CPU Minikube cluster:

```bash
TAG=$(git rev-parse --short HEAD)
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/base/serviceaccounts.yaml
kubectl apply -f k8s/base/ragops-pvcs.yaml
kubectl apply -f k8s/pvc-helper-pod.yaml
kubectl kustomize k8s/overlays/incluster-ollama | sed "s/:SHA/:$TAG/g" | kubectl apply -f -
kubectl rollout status deploy/ollama -n rahbar --timeout=600s
kubectl exec deploy/ollama -n rahbar -- ollama pull nomic-embed-text
kubectl exec deploy/ollama -n rahbar -- ollama pull llama3.2:3b
```

On Windows, the base cluster bootstrap is automated idempotently by `.\scripts\rebuild-from-scratch.ps1`.

---

## PowerShell Demo Helpers

[docs/DEMO.md](docs/DEMO.md) provides a numbered live-demo script (a recorded transcript is in [docs/evidence/live/demo-transcript.md](docs/evidence/live/demo-transcript.md)):

| Script (PowerShell) | What it does |
|---|---|
| `.\scripts\demo-up.ps1` | Starts Minikube if needed, waits for all pods, checks the index and Ollama models, starts UI/API port-forwards, and pre-warms Ollama |
| `.\scripts\demo-check.ps1` | Smoke test with non-zero exit on failure (health, cited answer, abstention, 11 PLOs / clause 1.21, cache hit, HPA, 3 endpoints) |
| `.\scripts\demo-down.ps1` | Stops port-forwards and runs `minikube stop` (never `delete`) |
| `.\scripts\rebuild-from-scratch.ps1` | Clean clone → working stack |

---

## Corpus Note

The repository commits [corpus/MANIFEST.md](corpus/MANIFEST.md) (each Batch A document's URL and SHA-256 checksum) plus `scripts/fetch_corpus.py` — **not** the Batch A PDFs/HTML themselves (`corpus/raw/` is gitignored). Run `python scripts/fetch_corpus.py` to download Batch A and verify hashes against `corpus/MANIFEST.md`. Never commit documents from SLATE, Flex, NU Mail, or anything behind a login. The synthetic/curated Part A Batch B test files live under `corpus/batch_b/`.

---

## Layout

```text
rahbar/
├── api/              # FastAPI service: reads Chroma (read-only), emits traces & /metrics
├── indexer/          # Indexer Job & pipeline: verify -> datalake -> chunk -> embed -> store -> rollback
├── ui/               # Chat UI served by nginx
├── corpus/           # MANIFEST.md + batch_b/ (raw/ fetched via scripts/fetch_corpus.py)
├── eval/             # golden.jsonl, run_ragops_eval.py, release_gate.py, gate_thresholds.yaml,
│                     # coverage_check.py, live_queries.jsonl, module_pairs.jsonl, results/,
│                     # plus CI legacy golden.yaml, run_eval.py, baseline.json, results.json, fixtures/
├── traces/           # traces.jsonl, candidate_traces.jsonl, metrics_summary_24h.json
├── k8s/              # base/, overlays/{dev,prod,host-gpu-ollama,incluster-ollama}/, patches/,
│                     # gate-configmap.yaml, eval-job*.yaml, candidate-*.yaml, indexer-*-job.yaml,
│                     # rollback-job.yaml, pvc-helper-pod.yaml, README.md
├── docs/             # CORPUS, PIPELINE, FAILURE-ANALYSIS, ENGINEERING-NOTES, AI-USAGE,
│                     # ARCHITECTURE, DEMO, adr/0001-0004, evidence/
├── scripts/          # fetch_corpus.py, trace_tool.py, summarize_traces.py, check_submission.py,
│                     # demo-up.ps1, demo-check.ps1, demo-down.ps1, rebuild-from-scratch.ps1
├── .github/workflows/{ci.yml,cd.yml}
└── Makefile · README.md · LICENSE · .gitignore
```

---

## Docs to Read First

1. [docs/adr/0001-indexer-as-job.md](docs/adr/0001-indexer-as-job.md) — why indexing is a Job
2. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system diagram and why Chroma is a StatefulSet
3. [docs/ENGINEERING-NOTES.md](docs/ENGINEERING-NOTES.md) — answers to the 7 required engineering questions
4. [docs/PIPELINE.md](docs/PIPELINE.md) — extraction / chunking / embedding with measured chunk configs
5. [docs/FAILURE-ANALYSIS.md](docs/FAILURE-ANALYSIS.md) — 4 pipeline stages broken on purpose, with diagnoses
6. [docs/AI-USAGE.md](docs/AI-USAGE.md) — AI attribution
7. [docs/CORPUS.md](docs/CORPUS.md) — the 7 corpus properties and failure modes
8. [k8s/README.md](k8s/README.md) — complete Kubernetes RAGOps runbook

---

## CI / CD

- **CI** (`.github/workflows/ci.yml`, on PR to `main` + push to `dev`): `lint` (`ruff` + `mypy`) → `test` (`pytest api/tests indexer/tests`, ≥60% coverage on `api/app`, `stub` provider) → `manifests` (`kustomize build | kubeconform -strict`) → `build` (no push on PR) → Trivy scan → `e2e-eval` on a `kind` cluster enforcing the legacy fixture gate (`eval/golden.fixture.yaml` + `eval/baseline.fixture.json`).
- **CD** (`.github/workflows/cd.yml`, on push to `main`): `test` → `build-push` (`needs: test`) → `deploy` (`needs: build-push`), images tagged only with `${{ github.sha }}` — never a floating `latest` tag.

---

## Troubleshooting

| Symptom | Usual cause | Fix |
|---|---|---|
| `ImagePullBackOff` on a locally built image | Minikube cannot see host Docker images, or `:SHA` was applied unsubstituted | Run `minikube image load <image>:<tag>` and substitute `:SHA` before `kubectl apply` |
| Service names stop resolving after `NetworkPolicy` | Default-deny egress also blocks DNS | Allow egress to `kube-dns` on port `53` (UDP/TCP) in `kube-system` (`k8s/base/networkpolicy.yaml`) |
| API cannot reach Ollama on your laptop | Ollama listens on `127.0.0.1` only, or host IP differs from `NetworkPolicy` | Run Ollama with `OLLAMA_HOST=0.0.0.0` (or use `k8s/overlays/host-gpu-ollama`) and verify `minikube ssh "grep host.minikube.internal /etc/hosts"` |
| UI can still reach Chroma despite policy | Cluster started without Calico | Recreate cluster with `minikube start --driver=docker --cni=calico ...` |
| HPA shows `<unknown>/70%` | Missing `requests.cpu` or `metrics-server` disabled | Enable `metrics-server` addon and ensure CPU requests are set |
| Indexer pod in `CrashLoopBackOff`, exit code `137` | OOMKilled during embedding | Raise Job memory limit guided by `kubectl top pods -n rahbar` |
| API Running but `0/1 READY` | `/readyz` fails: empty Chroma collection, Redis down, or `EMBED_MODEL`/`EMBED_DIMENSION` pin mismatch | Check `kubectl describe pod` and `kubectl logs` |

Diagnose in this order: `kubectl get pods -n rahbar`, then `kubectl describe pod <pod> -n rahbar`, then `kubectl logs <pod> -n rahbar` (adding `--previous` for a crashed container).
