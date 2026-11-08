# docs/evidence - index of every artifact

Every file here is raw output of a real command or run; the first line of each `live/*.txt` capture is the
command. Nothing is hand-written except this index. Captured 2026-11-07/08 on the reference machine
(Windows 11, minikube v1.39, docker driver, Calico, 8 GB / 6 CPUs, in-cluster Ollama).

## Automated checks (re-run 2026-11-08)

| File | What it shows |
|---|---|
| `submission_check.txt` | `python scripts/check_submission.py` - 12/12 PASS |
| `pytest_suite.txt` | `pytest -v api/tests eval indexer/tests` - 150 passed |
| `kustomize_validation.txt` | `kubectl kustomize` renders base, dev, prod and incluster-ollama |
| `eval_dry_run.txt` | gate evaluation of the committed `eval/results.json` against `eval/baseline.json` (PASSED) + eval tests |
| `ci_cd_green_runs.md` | links to the green CI and CD runs and the root cause of every pipeline failure fixed on the way |
| `pr-gate-failing.txt`, `pr-gate-green.txt` | the PR gate demo (spec sec. 6): `gh pr checks` / `mergeStateStatus` with `GATE FAILED`, then green |

## Live stack (`live/`)

**Indexing and data**

| File | What it shows |
|---|---|
| `index_done.txt`, `indexer-final-run.log` | final full index: 15 documents, 480 chunks, amplification 1.071, `scanned_pages` / `ocr_applied` per document |
| `kubectl-top-during-index.txt` | `kubectl top pods --containers` every 4 s during a full index (450 samples): indexer peak 298 Mi / 595 m |
| `kubectl-top-during-index-run1.txt` | the first full index (12 PDFs, 473 chunks, before HTML support): indexer peak 289 Mi / 450 m |
| `chunking-experiment/` | the four (size, overlap) configurations: `index_done_*.json` and `recall_probe_*.json` (recall@3/@5, by type, per question) |
| `golden_chunk_map.json` | text quote -> chunk ids resolved by `scripts/map_golden_to_chunks.py` |
| `cache-threshold-probe.json` | 13 question pairs, cosine per pair and false/true hits per threshold (ADR 0002) |

**Evaluation**

| File | What it shows |
|---|---|
| `../../eval/results.json`, `../../eval/baseline.json` | the committed live evaluation and its baseline |
| `eval-run-raw.json` | the raw output of `eval/run_eval.py` of that run (before the gate verdict was recomputed against the baseline) |
| `eval-gpu-host-llama3.2-3b.json`, `eval-gpu-host-qwen2.5-7b-rejected.json` | live evaluation with the model on the host GPU: llama3.2:3b matches the committed baseline (31 s run); qwen2.5:7b fails the citation gate (0.857) and is rejected |
| `demo-1-grounded-answer.json` ... `demo-6-prompt-injection.json` | questions through the **Ingress** (`Host: rahbar.local`): grounded cited answer, cache hit, must-abstain (hostel), EE PLOs (11), attendance (clause 1.21), prompt injection |

**Cluster behaviour (spec sec. 4)**

| File | What it shows |
|---|---|
| `kubectl-get-all.txt`, `kubectl-get-pods-wide.txt` | every object in namespace `rahbar`; pods and nodes |
| `hpa.txt` | `kubectl get hpa` (`cpu: N%/70%`, a real value) and `describe` |
| `kubectl-top-idle.txt`, `kubectl-top-during-eval.txt` | idle and under-load resource use of every container (basis of every request/limit; ENGINEERING-NOTES Q4) |
| `scale-endpoints.txt` | scale to 4: `kubectl get endpoints api` lists 4 IPs, back to 3 |
| `rollout-set-image-undo.txt` | `kubectl set image` -> `rollout status` -> page title changes -> `rollout undo` -> old version serving |
| `resilience-delete-api-pod.txt` | an api pod deleted during a 60-request loop through the Ingress: 0 failures |
| `embedding-pin-demo.txt` | `EMBED_MODEL` changed in the ConfigMap + api restart: new pod `0/1`, `embedding_pin_mismatch` log, `/readyz` 503 body, then restored (Q6) |
| `manual-reindex-job.txt` | `kubectl create job --from=cronjob/reindex`: completes in ~4 min, cache 1 -> 0 keys, api stays Ready |
| `observability.txt` | `/healthz`, `/readyz`, `/metrics` samples, one JSON request log line (request_id, top_k, chunk ids, scores, abstention) |
| `networkpolicy-live-test.txt`, `networkpolicy-live-test-ollama.txt` | ui -> chroma / redis / ollama blocked, api -> chroma / redis / ollama allowed (Calico enforcing) |
| `security-evidence.txt` | non-root, read-only root filesystem, dropped capabilities, ServiceAccount per workload, ClusterIP only, no secret patterns in Git |

**Failure analysis (`docs/FAILURE-ANALYSIS.md`)**

| File | What it shows |
|---|---|
| `failure-A-no-ocr.json` | scanned PDFs extracted with and without OCR |
| `failure-analysis-measurements.txt` | stages E, D, F: retrieval with the superseded filter off, prompt without the context instruction, temperature 1.2 |
| (`chunking-experiment/`) | stage B (100/0) and the chunk-size table; stage C (`TOP_K`) is in FAILURE-ANALYSIS.md with the probe command |

**Demo**

| File | What it shows |
|---|---|
| `demo-transcript.md` | full recorded output of the rehearsed live demo (`docs/DEMO.md`), the fallback if the live cluster fails |

## Screenshots (`screenshots/`)

| File | What it shows |
|---|---|
| `pr2-merge-box-FAILING-e2e-eval-merge-blocked.png` | PR #2: `CI / e2e-eval` failing, "Merging is blocked", merge button greyed out |
| `pr2-overview-demo-failing-gate-do-not-merge.png` | PR #2 overview with the "do not merge" note and the red commit status |
| `pr2-merge-box-GREEN-6-checks-passed.png` | PR #2 after the revert: "All checks have passed" (6 successful checks); only the 1-review rule still blocks the merge |

## Not in this directory

* A Docker Hub screenshot and a video: none was recorded.
