# CS4032 Assignment 03 (RAGOps) — Remediation Task List

Audit of the repository against `assignment_03.md` (audited 2026-11-27).
Tasks are ordered into four execution phases so that work Claude can do alone comes first and manual steps are batched together. Within each phase, tasks stay grouped by assignment section.
Tasks tagged **[CLUSTER]** need the minikube cluster running.

---

## Phase 1 — Claude can do these alone (no cluster, no manual action)

> Code, manifest, data-file and documentation fixes. Decision applied: for the single-writer task in Part F ("Enforce or document single-writer access honestly"), document the real mechanism in `k8s/README.md` rather than implementing Chroma auth.

### Part A: Data management — verify and update

- [x] Fix the completeness-check reason in `indexer/pipeline/verify.py` for unreadable files: `b07_corrupt_file.pdf` currently reports `truncated_or_page_mismatch: declared page_count=0 != extracted_pages=0` (0 equals 0). Emit a correct reason such as `missing_required_metadata: page_count unavailable (extraction failed)` and add a unit test in `indexer/tests/test_part_a_ragops.py`.
- [x] Extend the `vector_store_chunks_by_document` block that `indexer/pipeline/__main__.py` / `store.py` writes into each verification report so every document shows `{active, superseded, total}` chunk counts by `doc_id`/`source`. Today `Academic_Rules_Handbook_2026.pdf: 39` appears after Batch B with no proof that those chunks are `superseded=True` and excluded from retrieval.
- [x] Create `k8s/rollback-job.yaml`: a Job running `python -m pipeline.rollback --doc-id academic_rules_handbook --to-version 2026-06` under `serviceAccountName: indexer-sa`, label `app: indexer`, mounting `corpus-data` and `eval-results`, and writing its JSON result to `/results/rollback_academic_rules_handbook.json`. Rollback writes to Chroma, so running it from a laptop would break the "only the ingestion Job writes" rule.

### Part B: Offline testing at three levels

- [x] In `eval/run_ragops_eval.py`, split the abstention metric. `abstention_correctness` currently counts the prompt-injection question G15 (`must_not_obey_injection`) in its denominator (6 = 5 unanswerable + 1 injection). Report `abstention_correctness` over `must_abstain` questions only, and add a separate `injection_resistance` metric. Update `eval/release_gate.py` to keep gating on the corrected field.
- [x] Add a `--judge-model` argument to `eval/run_ragops_eval.py` (separate from `--llm-model`), pass it to `llm_judge_faithfulness()`, and write `faithfulness_method` and `judge_model` into `level3_e2e` of every result file. Today no committed result file records which model judged faithfulness, so the "dolphin-mistral:latest, 90% agreement" claim cannot be traced to a file.
- [x] Rename `judge_human_agreement` to `faithfulness_vs_human_agreement`, and add a `method` field when the lexical scorer is used. At the moment lexical-overlap runs also report "judge" agreement, e.g. `eval_candidate-pass_20261122T161336Z.json`.
- [ ] Bind each label in `eval/judge_human_labels.jsonl` to the exact answer it judged by adding `trace_id` and `answer_text`. Compute agreement only where the evaluated answer text matches the labelled one; labels keyed only by question id are silently reused on different answers across runs.
- [x] Change Level 1 "embedding time per chunk" in `run_level1_module()` to time real corpus chunks, e.g. 50 chunks sampled from the indexed collection or from `corpus/`, at `CHUNK_SIZE=512`. It currently times the short paraphrase-pair sentences, yet the report calls it "per 512-token chunk".
- [x] Make the stochasticity second run in `main()` repeat the whole suite including the noise test (`run_noise_test=True` for run 2), and extend `compute_stochasticity_diff()` to cover every reported metric: `embedding_time_per_chunk_ms`, all four `noisy_*` metrics, `grounded_answered`, `citations_checked`.
- [ ] For golden questions with more than one `relevant_pages` entry, compute nDCG@5 and recall against all relevant pages instead of a single binary target in `_retrieval_metrics_for_query()`. Otherwise document clearly in the code and report that recall@k is a hit rate.
- [x] Write the printed summary table to disk next to the JSON. For example, `eval/results/eval_<label>_<ts>.md`, or a `summary_table` string field in the JSON, so "writes a timestamped result file with a summary table" is met by the file itself.
- [x] Fix the category taxonomy in `eval/golden.jsonl`: G27–G32 have `category` set to topic names (`alumni_and_degree_verification`, …). Set `category: "unanswerable"` and move the topic to a new `topic` field, so the 15/5/5 answerable/unanswerable/hard counts can be computed from the file.
- [ ] Add `scripts/golden_stats.py` (or a `--stats` flag) that prints and asserts the golden-set requirements: ≥25 total, ≥15 answerable with doc+page, ≥5 unanswerable, ≥5 hard, ≥8 `human`, ≥8 synthetic with `reviewed_by_human: true`. Commit its output to `eval/results/golden_stats.txt`.

### Part C: Change experiment and release gate

- [x] Make `eval/gate_thresholds.yaml` and `k8s/gate-configmap.yaml` agree: `faithfulness_min` is `0.80` in the YAML but `GATE_FAITHFULNESS_MIN` is `"0.75"` in the ConfigMap, and the report quotes 0.75. Pick one value, justify it, and use it in both files.
- [x] Add `recall5_min` to `eval/gate_thresholds.yaml`, a `GATE_RECALL5_MIN` entry in `load_thresholds()`'s `env_map` in `eval/release_gate.py`, and the key in `k8s/gate-configmap.yaml`. The no-baseline branch uses `recall5_min` (default 0.70), but the ConfigMap cannot change it.
- [x] Persist the gate decision. Add `--gate-out` to `eval/run_ragops_eval.py` and `--out` to `eval/release_gate.py` to write `eval/results/gate_<label>_<ts>.json` containing `passed`, every check, the thresholds actually applied (YAML plus env overrides), and the baseline file used. All committed result files currently have no gate record.
- [x] Rename the mislabelled result file `eval/results/eval_candidate-pass_20261122T161536Z.json` to `eval_candidate-fail_20261122T161536Z.json`. It is the failing candidate (`recall@5 0.381`, `top_k=1`, `bad_unconstrained_v0`). Also state in a short `eval/results/README.md` that `candidate_pass.json`, `candidate_fail.json` and `baseline_k8s.json` are copies of specific timestamped runs.
- [x] Commit the failing candidate's configuration, e.g. `k8s/candidate-fail-config.yaml` as a ConfigMap patch with `PROMPT_TEMPLATE=bad_unconstrained_v0`, `TOP_K=1`, `COLLECTION_VERSION=candidate-fail-v0`. Only the passing candidate config is committed, but `traces/candidate_traces.jsonl` shows the failing one changed two parameters.

### Part E: Drift and coverage checking

- [x] Commit an E3 drift diff, `eval/results/e3_drift_batch_b_diff.json`, comparing `baseline_k8s.json` with `eval_post-batch-b_20261122T163228Z.json` across all three levels. List every golden question whose retrieval hit or answer changed, with the cause, e.g. ground truth still pointing at the now-superseded `Academic_Rules_Handbook_2026.pdf`.

### Part F: Kubernetes

- [x] Make a fresh cluster reproducible from `k8s/README.md`. Add the missing image build and load steps for `ghcr.io/rahbar/api:local`, `ghcr.io/rahbar/indexer:local` and `ghcr.io/rahbar/eval:local` (`docker build ...` and `minikube image load ...`), or add a `make images-local` target. `candidate-deployment.yaml`, `indexer-batch-b-job.yaml`, `indexer-candidate-job.yaml` and `eval-job.yaml` use `:local` images that nothing builds.
- [x] Fix step 2 of `k8s/README.md`. `kubectl apply -k k8s/overlays/host-gpu-ollama` applies the literal `:SHA` image tags without the `sed` substitution, so pods go to `ImagePullBackOff`. Use `kubectl kustomize k8s/overlays/host-gpu-ollama | sed "s/:SHA/:$TAG/g" | kubectl apply -f -` or a single shared tag.
- [x] Add the missing `k8s/pvc-helper-pod.yaml`, a busybox Pod mounting `corpus-data`, `traces-data` and `eval-results`. `k8s/README.md` uses `pvc-helper` for `kubectl cp` of Batch B and for reading traces, but no manifest creates it.
- [x] Fix the ingest ordering conflict. The overlay creates `job/indexer` before the corpus is copied to the PVC (the Job fails with exit 2), and `k8s/README.md` then runs `kubectl apply -f k8s/base/indexer-job.yaml`, which has the `:SHA` tag and is already applied. The root `README.md` says not to re-apply it. Document one order: copy corpus → (re)create indexer Job → wait.
- [x] Add a documented step that seeds the gate baseline on the PVC (`/results/baseline_k8s.json`), e.g. run the eval Job once with `EVAL_LABEL=baseline` and copy its result to that name via `pvc-helper`. Without it, `eval-job.yaml` silently skips `--baseline` and the "recall@5 drop vs baseline" and "abstention not lower than baseline" rules never run.
- [x] Add `k8s/eval-job-candidate.yaml`, a Job named `eval-job-candidate` with `EVAL_TARGET_API=http://api-candidate:8000` and `EVAL_LABEL=candidate` set as container `env` overriding the ConfigMap. Today evaluating the candidate needs a hand edit of `rahbar-gate-config`, which is described only in a YAML comment.
- [x] Update `k8s/eval-job.yaml` so the in-cluster gate scores faithfulness with the calibrated judge: pass `--llm-judge --judge-model "$EVAL_JUDGE_MODEL"` and add `EVAL_JUDGE_MODEL: "dolphin-mistral:latest"` to `k8s/gate-configmap.yaml`. Currently every in-cluster run uses lexical overlap, scores near 1.0, and makes the faithfulness gate ineffective.
- [x] Fix `eval/Dockerfile` line `RUN pip install --no-cache-dir pydantic>=2.9 ...`: the unquoted `>=` is parsed by `/bin/sh` as output redirection, so versions are unpinned and stray files are created. Quote each requirement (or use a `requirements.txt`), and remove the unused `COPY api/requirements.txt`.
- [x] Move `CHROMA_COLLECTION`, `COLLECTION_VERSION` and `EMBED_VERSION` (and `PROMPT_TEMPLATE`) for the live API into explicit `env:` entries in the pod template of `k8s/base/api-deployment.yaml`. Values that come only from `envFrom: rahbar-config` are not part of a ReplicaSet revision, so `kubectl rollout undo` cannot restore the previous collection or embedding version.
- [x] Commit the promotion as a manifest change: a patch file such as `k8s/patches/promote-candidate.yaml` that sets the tested candidate's `PROMPT_TEMPLATE` (and collection, if part of the change) on `deployment/api`. Document it in `k8s/README.md` with `kubectl rollout status deployment/api`. The current promotion is an imperative `kubectl set env` that leaves committed manifests out of sync with the cluster.
- [x] Document in `k8s/README.md` how traces and results are copied from the PVCs into the repo, e.g. `kubectl cp rahbar/pvc-helper:/traces/traces.jsonl traces/traces.jsonl` and `kubectl cp rahbar/pvc-helper:/results eval/results`.
- [ ] Address concurrent trace writes. `traces-data` is a single `ReadWriteOnce` PVC appended to by 3 `api` replicas and `api-candidate` through one file. Either set a per-pod `TRACE_FILE` with the downward API (`metadata.name`), or document in `k8s/README.md` why single-node minikube and line-buffered appends are acceptable.
- [x] Enforce or document single-writer access honestly. The `allow-api` NetworkPolicy permits `api → chroma:8000`, and ServiceAccounts do not control Chroma HTTP writes, so only the API code keeps the API from writing. Either add Chroma token auth with the write token mounted only into indexer Jobs, or state the real mechanism in the `k8s/README.md` single-writer section.

### Part G: Report

- [ ] Correct the course title in `report/report.html` and `README.md` from "Software Quality Engineering" to "Software Construction and Development (CS4032)".
- [ ] Fix the character-encoding corruption in `report/report.html` and the regenerated PDF: `Â§`, `â€“`, `â€”` and `�` appear throughout (pages 1–16 of `Report_CS4032_Assignment03.pdf`). Save as UTF-8 with `<meta charset="utf-8">` and re-render.
- [ ] Rebuild Table 1 (Figure 3 mapping) with exactly the seven stages the assignment names: ingest, verify, update data lake, update retrieval sources, offline testing, live testing, check coverage. Use the columns "what the pipeline does", "file that does it" and "what is missing". The current table uses different stages (Chunk & Vector Index, Generation, Observability…) and has "Design Delta" instead of "what is missing".
- [ ] Fix Table 7 (trace schema) to list every D1 field the assignment requires, including `latency_per_stage` and `cache_hit`, which are in the traces but missing from the table, plus `full_prompt` and `parameters`. Drop the "16-field" wording unless the count is exact.
- [ ] Correct Table 9 (K8s workloads). ServiceAccounts are not "Privileged Chroma writer" / "Zero write access"; describe the real single-writer mechanism (Job + code path + NetworkPolicy, or Chroma auth if added). Add the F3 evidence: candidate blocked (rollout history) and the trace after undo showing the previous collection and embedding version.
- [ ] Rewrite short answer (a) to name the problem verification did **not** catch: `b11_library_fine_addendum_injected.md` passed all four checks and was indexed. Say what would catch it, e.g. an injection-pattern content check at verification time. Also state which single check caught the most problems (uniqueness, 3 of 6).
- [ ] Rewrite short answer (b) with an example from your own results instead of hypothetical scenarios. For example, Level 1 is identical (`cosine_gap 0.2891`) in `baseline_k8s.json` and the failing candidate, while recall@5 falls 0.7143 → 0.3810. Or Level 1 is unchanged after Batch B while recall@5 drops to 0.6190.
- [ ] Tighten short answers (d) and (e) with your own evidence: (d) judge agreement 0.30 (llama3.2:3b) vs 0.90 (dolphin-mistral), and in-cluster lexical faithfulness sitting at 1.0; (e) the concrete deviations from the paper (e.g. batch Jobs instead of online evaluation, lexical fallback judge, coverage measured on synthetic live queries).
- [ ] Rewrite short answer (f) as a table of Kubernetes object → RAGOps responsibility. Cover Job, CronJob, Deployment (live), Deployment + Service (candidate), StatefulSet, each PVC, both ConfigMaps, NetworkPolicy and ServiceAccount, and explicitly name the object(s) that keep the vector store single-writer.
- [ ] Remove the appendix sentence "Every screenshot below captures authentic terminal output…" until it is true, i.e. after the screenshots are replaced in the Submission section below.

### Submission: Repository, README & Screenshots

- [ ] Add a "How to run each part (A–F)" section to the root `README.md`, with the exact command(s) per part: indexer Job / Batch B Job / rollback Job, `run_ragops_eval.py`, `release_gate.py`, trace tool and `summarize_traces.py`, `coverage_check.py`, and the eval Job / candidate / rollout commands. The root README currently has a results summary and Assignment 02 apply steps, but no per-part commands.
- [ ] Remove the corrupted control characters in `README.md`: backspace `\x08` and bell `\x07` bytes appear in "(04–09)", "(10)", "(11)", "api-candidate:8000" and "api-sa", and `rahbar` / `rahbar_corpus_candidate` lost their leading `r`. Use backticks for code names.
- [ ] Update `README.md` links that point to files now deleted from the working tree (`SCD_Assignment03_RAGOps_Implementation_Checklist.md` / `.pdf`). Replace the stale Assignment 02 facts in the body ("`eval/golden.yaml` (15 questions)", "`make eval` runs `run_eval.py`") with the Assignment 03 equivalents.

---

## Phase 2 — Cluster runs (autonomous; cluster + Ollama pre-started)

> Minikube (`--cni=calico`) and host Ollama (`llama3.2:3b`, `nomic-embed-text`, `dolphin-mistral:latest`) are started locally; build and deploy/update the images using the fixed Phase 1 instructions. Rebuilding the Chroma collection and running the A2 changed/deleted demos on the PVC are pre-approved — restore the edited and deleted Batch A documents before the Part B re-run.

### Part E: Drift and coverage checking

- [ ] Handle golden labels made stale by Batch B by keeping Batch A ground truth in `relevant_document`, adding optional `relevant_document_after_batch_b` annotations where `b10` supersedes `Academic_Rules_Handbook_2026.pdf`, and documenting the stale labels as an explicit E3 drift finding. Re-run the suite after updating and commit the result.
- [ ] Commit the pre-expansion golden snapshot `eval/golden_pre_expansion.jsonl` (G01–G26). Re-run `eval/coverage_check.py --golden eval/golden_pre_expansion.jsonl --out eval/results/coverage_pre_expansion.json` so the "before" result can be reproduced. The current `eval/golden.jsonl` already holds 32 questions.
- [ ] Derive and commit a justification for the 0.70 similarity threshold: the distribution of `max_similarity` for `domain: in_domain` vs `domain: uncovered` queries in `eval/live_queries.jsonl`, saved as `eval/results/coverage_threshold_analysis.json`. The report states τ = 0.70 with no justification.

### Part A: Data management — verify and update

- [ ] **[CLUSTER]** Commit the first-ingest Batch A verification report (the run where `chunks_embedded > 0`) as `eval/results/verification_batch_a_initial.json`. The committed `verification_batch_a.json` is the unchanged re-run (`docs_skipped_unchanged: 15`), so no committed file shows A1 checks on a first ingest.
- [ ] **[CLUSTER]** Re-run `k8s/indexer-batch-b-job.yaml` on the unchanged Batch B folder and commit the report as `eval/results/verification_batch_b_rerun.json`, showing `chunks_embedded: 0`. The assignment says "Run both batches through A1 and A2", and there is no A2 evidence for Batch B.
- [ ] **[CLUSTER]** A2 changed-document demo: edit one document in `/corpus/raw` on the PVC, re-run the indexer Job, and commit `eval/results/a2_changed_document.json` with `docs_updated: 1`, the `chunks_deleted`/`chunks_embedded` counts for that document only, and unchanged chunk counts for every other document (before/after by doc id).
- [ ] **[CLUSTER]** A2 deleted-document demo: remove one document from `/corpus/raw`, run the non-additive indexer Job, and commit `eval/results/a2_deleted_document.json` showing `docs_deleted: 1` and a chunk count of `0` for that doc id in Chroma (no orphans).
- [ ] **[CLUSTER]** A2 rollback demo: apply `k8s/rollback-job.yaml`, commit its result JSON, and commit two traces of the same version-sensitive question (before and after rollback) to `traces/a2_rollback_traces.jsonl`, showing `document_version` move from `2026-11` back to `2026-06`.

### Part B: Offline testing at three levels

- [ ] **[CLUSTER]** Re-run the full Part B suite in-cluster with the final 32-question `eval/golden.jsonl`, `--llm-judge --judge-model dolphin-mistral:latest --stochasticity-runs 2`, and commit the timestamped result. Every committed Part B/C result file uses the old 26-question set (`total_questions: 26`), so the committed golden file and results disagree.

### Part C: Change experiment and release gate

- [ ] **[CLUSTER]** Re-run baseline and both candidates in the same environment (in-cluster eval Job), with the same golden set and the same faithfulness method. Commit a C1 comparison file `eval/results/c1_baseline_vs_candidates.json` covering all three levels. The report currently compares a local LLM-judge baseline (`eval_baseline-final`, port-forward `127.0.0.1:18000`, p95 12.1 s) against in-cluster lexical candidates.

### Part D: Observability and traceability

- [ ] **[CLUSTER]** Generate live-style trace traffic that goes through the semantic cache: repeated non-follow-up queries, since the eval runner sends `follow_up=True`, which skips the cache. Every one of the 487 committed traces has `cache_hit: false`, and `traces/metrics_summary_24h.json` reports `cache_hit_rate: 0.0`. Commit the new traces and re-run `scripts/summarize_traces.py`.
- [ ] **[CLUSTER]** Re-generate `traces/metrics_summary_24h.json` after the final runs, and also commit a human-readable copy, e.g. `traces/metrics_summary_24h.txt`, of the D3 output: top-1 similarity distribution, abstention rate, cache hit rate, p95 per stage, injection attempts flagged.

### Part F: Kubernetes

- [ ] **[CLUSTER]** F3 gate-stop evidence: after the failing candidate's eval Job exits non-zero, capture `kubectl get job eval-job-candidate` (Failed) and `kubectl rollout history deployment/api` (no new revision). Commit both to `docs/evidence/ragops/f3_candidate_blocked.txt`.
- [ ] **[CLUSTER]** F3 bad-release-and-undo evidence with a release that changes collection/version and actually serves traffic, e.g. `COLLECTION_VERSION=candidate-fail-v0`, `TOP_K=1`. Query it, run `kubectl rollout undo deployment/api`, query again, and commit both trace lines to `traces/f3_rollback_traces.jsonl`, showing `rahbar_corpus` / `v1` / `nomic-embed-text:v1.5` after the undo. The current broken-image demo never changed the collection, and trace `25003554` cited in the report is not in any committed trace file.
- [ ] **[CLUSTER]** F4 evidence: commit `docs/evidence/ragops/f4_kubectl_logs_traces.txt` (`kubectl logs deploy/api -n rahbar --tail=3` showing JSON trace lines) and `docs/evidence/ragops/f4_metrics_port_forward.txt` (`kubectl port-forward svc/api 8000:8000` plus `curl localhost:8000/metrics`, showing the RAGOps counters and histograms). Add both commands to `k8s/README.md`.
- [ ] **[CLUSTER]** F5: take fresh measurements with `kubectl top pods -n rahbar --containers`, sampled during `indexer-batch-b`, `eval-job`, and `api`/`chroma` under eval load. Commit them to `docs/evidence/ragops/f5_resource_measurements.txt`. The existing `docs/evidence/live/kubectl-top-*.txt` files come from the Assignment 02 `run_eval.py` run, and no eval-job pod was ever measured.

---

## Phase 3 — Report and manifest updates that need Phase 2 results

> Claude can do these alone once the Phase 2 result files are committed.

### Part D: Observability and traceability

- [ ] Choose a genuinely **wrong** answer for D5 from the re-run Part B results, i.e. a retrieval miss or an unfaithful answer, not the correct hostel abstention (trace `bcb5f6cf`). Commit that single trace line to `traces/d5_root_cause_trace.jsonl` and the `scripts/trace_tool.py <trace_id>` output to `traces/d5_trace_tool_output.txt`.

### Part F: Kubernetes

- [ ] Set requests/limits for `eval-job.yaml`, `indexer-batch-b-job.yaml`, `indexer-candidate-job.yaml`, `candidate-deployment.yaml`, `api-deployment.yaml` and `chroma-statefulset.yaml` from the new F5 measurements (e.g. request ≈ p50 usage, limit ≈ max × 1.5), and leave a short comment in each manifest pointing to the measurement file.

### Part G: Report

- [ ] Correct Table 2 (five qualities). Remove "Superseded docs: 0 orphan chunks" until the A2 deleted-document file exists, and then cite it. Remove the unmeasured "Prometheus scrape error = 0%". Replace "Typo noise 0.0000 drop" with the real deltas (`recall@3 +0.0952`, `recall@5 0.0000`, `MRR +0.0897`, `nDCG@5 +0.0676`). Replace "480 skipped" with the real "15 documents skipped, 0 chunks embedded".
- [ ] Add a Part A results table covering first ingest, unchanged re-run (both batches), changed document, deleted document (chunk count by doc id), superseded/archived counts (active vs superseded chunks), and the rollback demo, each citing its committed file.
- [ ] Correct the Part B table. Make the recall formula match the code (top-k hit rate, or the new multi-page recall). Remove "per 512-token chunk" unless the new measurement uses real chunks. Report all four noise deltas and explain why typos *raised* recall@3/MRR. Make the citation count match the result file (the report says 21/21; `eval_baseline-final` has `citations_checked: 23`). Name the judge model from the result file.
- [ ] Rewrite the stochasticity subsection with every metric's Run 1 / Run 2 / Δ from the final result file. Explain the remaining variation: latency jitter, plus the earlier `eval_baseline-stochasticity_20261122T155008Z.json` run where the llama3.2:3b judge gave a faithfulness Δ of +0.0556 under a fixed seed.
- [ ] Rewrite Part C (Table 6 and the release decision) using the like-for-like C1 comparison file. As it stands, the faithfulness "83.3% → 89.5%" and p95 "−63.3%" claims compare a local LLM-judge run with in-cluster lexical runs. Against `baseline_k8s.json`, faithfulness went 1.0000 → 0.8947 and p95 went 5,881 → 4,438 ms (−24.5%). State exactly what the failing candidate changed (`top_k=1` + `bad_unconstrained_v0`) and justify each threshold with measured numbers.
- [ ] Add a D3 metrics table from the final `traces/metrics_summary_24h.json`: top-1 similarity distribution (histogram/percentiles), abstention rate, cache hit rate, p95 per stage for all 8 stages, and injection attempts by rail. Name the time window.
- [ ] Rewrite D5 as exactly 5 lines about the new wrong-answer trace, using only fields in that trace (chunk id, document id/version, score, `filters_applied`). The current text uses knowledge from outside the trace ("0 mentions of hostels exist in the FAST corpus").
- [ ] Fix Part E. Add the 0.70 threshold justification from `coverage_threshold_analysis.json`. List all 17 pre-expansion uncovered queries grouped by topic, including the 3 `other_uncovered` in-domain queries (L03, L25, L26) that the report omits. List the 6 still-uncovered queries after expansion. Correct the Table 8 "Max Sim After" values to those in `coverage_post_expansion.json` (G27 0.8667, G28 0.8877, G29 0.7664, G30 0.7910, G31 0.8913, G32 0.8900; the report shows 0.7812/0.7645/0.7489/0.7512/0.7924/0.7601).
- [ ] Expand E3 in the report from one sentence to the drift-diff table: per-metric before/after, which questions flipped, and why.
- [ ] Add an F5 table with measured CPU/memory (p50/max) and the chosen request/limit for API, Chroma, indexer Job, and eval Job, citing the measurement file.
- [ ] Add both members' **roll numbers** to the first page of `report/report.html`: `Jaweria Abdul Hameed` (`i243025`) and `Mohsin Khan` (`i243135`) (confirmed from `RAHBAR-Assignment02-i243135-i243025.pdf`).
- [ ] Turn the contribution prose on Page 1 of `report/report.html` into a contribution table (member × parts/files based on git commit history and `docs/AI-USAGE.md`), and rewrite the AI statement (2–3 lines) so it truthfully describes how AI was used, including code/test remediation, report drafting, and any generated artifacts.
- [ ] Do a final cross-check of every number in `report/report.html` against the committed files in `eval/results/` and `traces/`, fix any mismatch, regenerate `report/Report_CS4032_Assignment03.pdf` (and the root copy), and confirm the main body is ≤ 8 pages.

---

## Phase 4 — Your tasks (manual only)

> Only the group members can do these. Take the screenshots last so they show the final runs, then commit and push.

### Part G: Report

- [ ] Visually review Page 1 of `report/report.html` to confirm both members' roll numbers (`Jaweria Abdul Hameed — i243025`, `Mohsin Khan — i243135`), the contribution table, and the 2–3 line AI statement before final submission.

### Submission: Repository, README & Screenshots

- [ ] Replace all 13 PNGs in `screenshots/` with **real terminal captures** from your own cluster runs (command plus full output, uncropped). They are currently rendered by `scripts/generate_screenshots.py` from hardcoded strings, and several values contradict the committed results. A1 shows `added=4 … embedded=4 total_in_store=484`, while `verification_batch_b.json` has `docs_added: 5, chunks_embedded: 6`. B1 shows all noise deltas `+0.0000`, while the result file has `+0.0952 / +0.0897 / +0.0676`. C1 prints lines `release_gate.py` never outputs ("Exited with status code 1 (Deployment blocked)"). This breaks the rule "Screenshots must come from your own cluster and your own runs."
- [ ] Capture the required F screenshot of `kubectl rollout status` and `kubectl rollout undo` **followed by a trace showing the previous collection and embedding version**; the current F4 image does not show these trace fields. Once real captures exist, stop using `scripts/generate_screenshots.py`, and regenerate `report/Report_CS4032_Assignment03.pdf` (and the root copy) if the appendix captures changed.
- [ ] Resolve the uncommitted working-tree state (9 deleted PDFs/HTML/checklists, untracked `assignment_03.md` and `ragops_operating_and_managing_retrieval_augmented_generation_pipelines.md`). Decide what belongs in the submission, commit the real screenshots and final cleanup, and run `git push` to GitHub.
