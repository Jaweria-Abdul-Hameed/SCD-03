# RAHBAR RAGOps: Kubernetes Deployment & Execution Guide

This directory contains the complete Kubernetes manifests and instructions for deploying and evaluating RAHBAR on Kubernetes (Minikube + Calico CNI) in accordance with the *RAGOps: Operating and Managing Retrieval-Augmented Generation Pipelines* paper (Xu et al., 2026).

---

## 1. Fresh Cluster Quickstart

### Prerequisites
- `minikube` v1.34+ with Docker driver
- `kubectl` v1.31+
- `kustomize` (or `kubectl kustomize`)
- Ollama running on the host (`ollama-host` mode) with the three required models pulled:
  ```bash
  ollama pull llama3.2:3b
  ollama pull nomic-embed-text
  ollama pull dolphin-mistral:latest
  ```

### Step 1: Start Minikube with Calico CNI
```bash
minikube start --driver=docker --cni=calico --memory=6144 --cpus=4
minikube addons enable metrics-server
minikube addons enable ingress
```

### Step 1b: Build and Load Local Images into Minikube
The base/overlay manifests use `:SHA` placeholders, while `k8s/candidate-deployment.yaml`, `k8s/indexer-batch-b-job.yaml`, `k8s/indexer-candidate-job.yaml`, `k8s/rollback-job.yaml`, `k8s/eval-job.yaml`, and `k8s/eval-job-candidate.yaml` reference `:local` images. Build and load all four images (`api`, `ui`, `indexer`, `eval`) into Minikube before applying manifests:

**Using Make:**
```bash
make images-local
```

**Manual (Bash or Windows PowerShell):**
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
*(If you also want a git-SHA tag for the base/overlay workloads, tag and load `:$TAG` with `TAG=$(git rev-parse --short HEAD)` — or simply use `TAG=local` as a single shared tag below.)*

### Step 2: Deploy Base Architecture, Storage & PVC Helper
Never run raw `kubectl apply -k k8s/overlays/host-gpu-ollama`, because it deploys literal `:SHA` image tags and sends pods into `ImagePullBackOff`. Always substitute `:SHA` before applying:

**Bash:**
```bash
TAG=local
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/base/serviceaccounts.yaml
kubectl apply -f k8s/base/ragops-pvcs.yaml
kubectl apply -f k8s/pvc-helper-pod.yaml
kubectl kustomize k8s/overlays/host-gpu-ollama | sed "s/:SHA/:$TAG/g" | kubectl apply -f -
kubectl wait --for=condition=Ready pod/pvc-helper -n rahbar --timeout=120s
```

**Windows PowerShell:**
```powershell
$tag = "local"
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/base/serviceaccounts.yaml
kubectl apply -f k8s/base/ragops-pvcs.yaml
kubectl apply -f k8s/pvc-helper-pod.yaml
(kubectl kustomize k8s/overlays/host-gpu-ollama) -replace ':SHA', ":$tag" | kubectl apply -f -
kubectl wait --for=condition=Ready pod/pvc-helper -n rahbar --timeout=120s
```

### Step 3: Populate Corpus to Cluster PVC
Download the corpus if needed (`python scripts/fetch_corpus.py`), then copy `corpus/raw/` into `/corpus/raw` on the `corpus-data` PVC **before** running the indexer Job:

```bash
# Option A: Using pvc-helper directly (works on Bash and PowerShell)
kubectl exec pvc-helper -n rahbar -- mkdir -p /corpus/raw
kubectl cp corpus/raw/. rahbar/pvc-helper:/corpus/raw/

# Option B: Using Makefile helper (Bash)
# make corpus-to-cluster
```

---

## 2. Part A: Initial Indexing & Verification

Use one deterministic ingest order: **copy corpus → (re)create indexer Job → wait**. Because the kustomize overlay creates `job/indexer` before the corpus is copied (so that initial pod exits `2` on an empty PVC), delete it and re-create it with the substituted `:SHA` tag after Step 3—never apply raw `k8s/base/indexer-job.yaml` without `:SHA` substitution.

**Bash:**
```bash
TAG=local
kubectl delete job indexer -n rahbar --ignore-not-found
sed "s/:SHA/:$TAG/g" k8s/base/indexer-job.yaml | kubectl apply -f -
kubectl wait --for=condition=complete job/indexer -n rahbar --timeout=600s
kubectl logs job/indexer -n rahbar
```

**Windows PowerShell:**
```powershell
$tag = "local"
kubectl delete job indexer -n rahbar --ignore-not-found
(Get-Content k8s/base/indexer-job.yaml) -replace ':SHA', ":$tag" | kubectl apply -f -
kubectl wait --for=condition=complete job/indexer -n rahbar --timeout=600s
kubectl logs job/indexer -n rahbar
```

Verify idempotent re-indexing and ingest Batch B:
```bash
# Verify unchanged re-run embeds exactly 0 chunks
kubectl create job --from=cronjob/reindex reindex-unchanged-1 -n rahbar
kubectl wait --for=condition=complete job/reindex-unchanged-1 -n rahbar --timeout=300s
kubectl logs job/reindex-unchanged-1 -n rahbar | grep "chunks_embedded: 0"

# Ingest Batch B (with planted defects & version superseding)
kubectl cp corpus/batch_b/. rahbar/pvc-helper:/corpus/batch_b
kubectl apply -f k8s/indexer-batch-b-job.yaml
kubectl wait --for=condition=complete job/indexer-batch-b -n rahbar --timeout=180s
kubectl logs job/indexer-batch-b -n rahbar
```

---

## 3. Part B & C: 3-Level Offline Evaluation & Automated Release Gate

### Seed the Gate Baseline on the PVC (`/results/baseline_k8s.json`)
`eval-job.yaml` and `eval-job-candidate.yaml` read `EVAL_BASELINE_FILE=/results/baseline_k8s.json` from `rahbar-gate-config` and pass `--baseline` only if that file exists on `eval-results`. Seed it once against the live `api` Service so the `recall@5_max_drop_vs_baseline` and `abstention_correctness_vs_baseline` gate rules are active:

**Bash:**
```bash
kubectl apply -f k8s/gate-configmap.yaml
kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"EVAL_LABEL":"baseline"}}'
kubectl delete job eval-job -n rahbar --ignore-not-found
kubectl apply -f k8s/eval-job.yaml
kubectl wait --for=condition=complete job/eval-job -n rahbar --timeout=600s
kubectl exec pvc-helper -n rahbar -- sh -c 'cp "$(ls -t /results/eval_baseline_*.json | head -n1)" /results/baseline_k8s.json'
kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"EVAL_LABEL":"k8s-eval"}}'
kubectl exec pvc-helper -n rahbar -- ls -l /results/baseline_k8s.json
```

**Windows PowerShell:**
```powershell
kubectl apply -f k8s/gate-configmap.yaml
kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"EVAL_LABEL":"baseline"}}'
kubectl delete job eval-job -n rahbar --ignore-not-found
kubectl apply -f k8s/eval-job.yaml
kubectl wait --for=condition=complete job/eval-job -n rahbar --timeout=600s
kubectl exec pvc-helper -n rahbar -- sh -c 'cp "$(ls -t /results/eval_baseline_*.json | head -n1)" /results/baseline_k8s.json'
kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"EVAL_LABEL":"k8s-eval"}}'
kubectl exec pvc-helper -n rahbar -- ls -l /results/baseline_k8s.json
```

### Run Live & Candidate Evaluation Jobs (Calibrated 7B LLM Judge)
Both `k8s/eval-job.yaml` and `k8s/eval-job-candidate.yaml` pass `--llm-judge --judge-model "$EVAL_JUDGE_MODEL"` (`dolphin-mistral` in `k8s/gate-configmap.yaml`):

```bash
# 1. Evaluate the live api Service against /results/baseline_k8s.json
kubectl delete job eval-job -n rahbar --ignore-not-found
kubectl apply -f k8s/eval-job.yaml
kubectl wait --for=condition=complete job/eval-job -n rahbar --timeout=600s
kubectl logs job/eval-job -n rahbar

# 2. Index candidate collection & deploy isolated api-candidate
kubectl apply -f k8s/indexer-candidate-job.yaml
kubectl wait --for=condition=complete job/indexer-candidate -n rahbar --timeout=600s
kubectl apply -f k8s/candidate-deployment.yaml
kubectl rollout status deployment/api-candidate -n rahbar --timeout=180s

# 3. Evaluate candidate (sets EVAL_TARGET_API=http://api-candidate:8000 and EVAL_LABEL=candidate via pod env)
kubectl delete job eval-job-candidate -n rahbar --ignore-not-found
kubectl apply -f k8s/eval-job-candidate.yaml
kubectl wait --for=condition=complete job/eval-job-candidate -n rahbar --timeout=600s
kubectl logs job/eval-job-candidate -n rahbar
```
To test a degraded candidate that fails the release gate (Job exits `1`), apply `k8s/candidate-fail-config.yaml`, restart `deployment/api-candidate`, and re-run `k8s/eval-job-candidate.yaml`.

---

## 4. Part D: Observability, Trace Tool & Extracting Cluster Artifacts

```bash
# Query the live service via port-forward
kubectl port-forward svc/api 8000:8000 -n rahbar

# Inspect live RAGOps Prometheus metrics (in a second terminal while port-forward is active)
# PowerShell note: use curl.exe instead of curl (curl is an Invoke-WebRequest alias in PowerShell)
curl localhost:8000/metrics

# Inspect live structured JSONL traces emitted to API pod stdout
kubectl logs deploy/api -n rahbar --tail=3
# (Filter across all API replicas for ragops_trace records)
kubectl logs deploy/api -n rahbar --all-pods=true --tail=50 | grep '"record_type": "ragops_trace"' | tail -n 3

# Inspect traces emitted to PVC
kubectl exec pvc-helper -n rahbar -- tail -n 5 /traces/traces.jsonl

# Copy traces and eval results from the PVCs into the local repo
kubectl cp rahbar/pvc-helper:/traces/traces.jsonl traces/traces.jsonl
kubectl cp rahbar/pvc-helper:/results eval/results

# Reconstruct exact context & verify prompt hash for a trace ID
python scripts/trace_tool.py <trace_id> --trace-file traces/traces.jsonl

# Generate 24-hour telemetry metrics summary
python scripts/summarize_traces.py --trace-file traces/traces.jsonl --window 24h
```

---

## 5. Part E: Drift & Live Query Coverage Checker
```bash
# Check baseline live query coverage against golden dataset
python eval/coverage_check.py --live-queries eval/live_queries.jsonl --golden eval/golden.jsonl --sim-threshold 0.70 --coverage-threshold 0.85
```

---

## 6. Part F: ConfigMap Live Edit, Manifest-Committed Promotion & Rollback

### Live Threshold Flip (No Image Rebuild)
```bash
# Flip release gate threshold without rebuilding container images
kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"GATE_P95_LATENCY_MAX_MS":"500.0"}}'
kubectl delete job eval-job -n rahbar --ignore-not-found
kubectl apply -f k8s/eval-job.yaml
# Gate fails: latency > 500ms

# Restore threshold
kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"GATE_P95_LATENCY_MAX_MS":"45000.0"}}'
kubectl delete job eval-job -n rahbar --ignore-not-found
kubectl apply -f k8s/eval-job.yaml
# Gate passes
```

### Zero-Downtime Promotion & Instant Rollback
`k8s/base/api-deployment.yaml` pins `CHROMA_COLLECTION`, `COLLECTION_VERSION`, `EMBED_VERSION`, and `PROMPT_TEMPLATE` directly in the Pod template so every promotion or rollback is tracked in ReplicaSet revisions. Promote the gate-passing candidate using the committed patch file (rather than imperative `kubectl set env`):

```bash
# Promote passing candidate (PROMPT_TEMPLATE=strict_concise_v2) with maxUnavailable: 0
kubectl patch deployment/api -n rahbar --patch-file k8s/patches/promote-candidate.yaml
kubectl rollout status deployment/api -n rahbar --timeout=300s

# Rollback demonstration (broken image or bad revision)
kubectl set image deployment/api api=ghcr.io/rahbar/api:broken-v99 -n rahbar
kubectl rollout status deployment/api -n rahbar --timeout=8s
kubectl rollout undo deployment/api -n rahbar
kubectl rollout status deployment/api -n rahbar --timeout=300s
```
Running `kubectl rollout undo deployment/api -n rahbar` also restores the previous `CHROMA_COLLECTION`, `COLLECTION_VERSION`, `EMBED_VERSION`, and `PROMPT_TEMPLATE` values stored on the prior ReplicaSet revision.

---

## 7. Single-Writer Access & Isolation Model

- **Network isolation (Calico NetworkPolicy):** `k8s/base/networkpolicy.yaml` applies `rahbar-default-deny` and allows TCP port `8000` ingress to `chroma` only from pods labeled `app: api`, `app: api-candidate`, and `app: indexer` (`allow-chroma`). The `ui`, `eval`, `pvc-helper`, and external pods cannot reach Chroma at all.
- **What ServiceAccounts do and do not control:** Dedicated `ServiceAccount`s (`indexer-sa`, `api-sa`, `chroma-sa`, `redis-sa`, `ui-sa`, `eval-sa` in `k8s/base/serviceaccounts.yaml`, all with `automountServiceAccountToken: false`) isolate Kubernetes API identity, but Kubernetes `ServiceAccount`s do **not** authenticate or authorize HTTP calls to ChromaDB, and ChromaDB runs in-cluster without HTTP authentication.
- **Honest enforcement mechanism:** Because `allow-api` permits `api -> chroma:8000` for vector queries, single-writer behavior is enforced by **application code and workload separation**: `api/app/retrieval/retriever.py` only opens `get_collection` and issues read-only `collection.query(...)` calls, while all Chroma writes (`upsert`, `delete`, version superseding, and rollback) live exclusively in the `indexer` Job and `reindex` CronJob (`concurrencyPolicy: Forbid`).
