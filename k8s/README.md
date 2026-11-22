# RAHBAR RAGOps: Kubernetes Deployment & Execution Guide

This directory contains the complete Kubernetes manifests and instructions for deploying and evaluating RAHBAR on Kubernetes (Minikube + Calico CNI) in accordance with the *RAGOps: Operating and Managing Retrieval-Augmented Generation Pipelines* paper (Xu et al., 2026).

---

## 1. Fresh Cluster Quickstart

### Prerequisites
- `minikube` v1.34+ with Docker driver
- `kubectl` v1.31+
- `kustomize`
- Ollama running on the host (`ollama-host` mode, binding to `0.0.0.0:11434`)
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

### Step 2: Deploy Base Architecture & Storage
```bash
# Apply namespace, service accounts, and PVCs
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/base/serviceaccounts.yaml
kubectl apply -f k8s/base/ragops-pvcs.yaml
kubectl apply -k k8s/overlays/host-gpu-ollama
```

### Step 3: Populate Corpus to Cluster PVC
```bash
# Populate FAST-NUCES raw corpus into /corpus/raw on the corpus-data PVC
make corpus-to-cluster
```

---

## 2. Part A: Initial Indexing & Verification
```bash
# Run one-shot single-writer indexer Job
kubectl apply -f k8s/base/indexer-job.yaml
kubectl wait --for=condition=complete job/indexer -n rahbar --timeout=300s
kubectl logs job/indexer -n rahbar

# Verify unchanged re-run embeds exactly 0 chunks
kubectl create job --from=cronjob/reindex reindex-unchanged-1 -n rahbar
kubectl wait --for=condition=complete job/reindex-unchanged-1 -n rahbar --timeout=300s
kubectl logs job/reindex-unchanged-1 -n rahbar | grep "chunks_embedded: 0"

# Ingest Batch B (with planted defects & version superseding)
kubectl cp corpus/batch_b rahbar/pvc-helper:/corpus/batch_b
kubectl apply -f k8s/indexer-batch-b-job.yaml
kubectl wait --for=condition=complete job/indexer-batch-b -n rahbar --timeout=180s
kubectl logs job/indexer-batch-b -n rahbar
```

---

## 3. Part B & C: 3-Level Offline Evaluation & Automated Release Gate
```bash
# Run in-cluster 3-level offline evaluation suite & release gate
kubectl apply -f k8s/gate-configmap.yaml
kubectl apply -f k8s/eval-job.yaml
kubectl wait --for=condition=complete job/eval-job -n rahbar --timeout=360s
kubectl logs job/eval-job -n rahbar
```

---

## 4. Part D: Observability, Trace Tool & Dual-Rail Defense
```bash
# Query the live service via port-forward
kubectl port-forward svc/api 8000:8000 -n rahbar &

# Inspect traces emitted to PVC
kubectl exec pvc-helper -n rahbar -- tail -n 5 /traces/traces.jsonl

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

## 6. Part F: ConfigMap Live Edit & Zero-Downtime Rollout/Rollback
```bash
# Flip release gate threshold without rebuilding container images
kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"GATE_P95_LATENCY_MAX_MS":"500.0"}}'
kubectl delete job eval-job -n rahbar && kubectl apply -f k8s/eval-job.yaml
# Gate fails: latency > 500ms

# Restore threshold
kubectl patch configmap rahbar-gate-config -n rahbar --type merge -p '{"data":{"GATE_P95_LATENCY_MAX_MS":"45000.0"}}'
kubectl delete job eval-job -n rahbar && kubectl apply -f k8s/eval-job.yaml
# Gate passes

# Zero-downtime rolling update & instant rollback
kubectl set env deployment/api PROMPT_TEMPLATE=strict_concise_v2 -n rahbar
kubectl rollout status deployment/api -n rahbar

# Rollback demonstration
kubectl set image deployment/api api=ghcr.io/rahbar/api:broken-v99 -n rahbar
kubectl rollout status deployment/api -n rahbar --timeout=8s
kubectl rollout undo deployment/api -n rahbar
kubectl rollout status deployment/api -n rahbar
```
