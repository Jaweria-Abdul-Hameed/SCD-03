# RAHBAR RAGOps: Kubernetes Deployment & Execution Guide

Every manifest lives under `k8s/`. Starting from a fresh minikube cluster, the commands below
(run from the repository root, in this order) bring up a working pipeline and run Parts A–F.
The commands are bash. On Windows PowerShell, replace `$(...)` with a variable
(`$TAG = git rev-parse --short HEAD`) and `\` line continuations with backticks.

| File | Kind | RAGOps responsibility |
|---|---|---|
| `base/api-deployment.yaml` | Deployment `api` (3 replicas, `maxUnavailable: 0`) | query pipeline, read-only on Chroma, traces to stdout + `traces-data` PVC |
| `base/chroma-statefulset.yaml` | StatefulSet `chroma` + PVC | vector store |
| `base/redis.yaml` | Deployment `redis` + PVC | semantic cache |
| `base/corpus-pvc.yaml` | PVC `corpus-data` | data lake: `raw/`, `datalake/`, `quarantine/`, `archive/`, `reports/` |
| `base/ragops-pvcs.yaml` | PVCs `traces-data`, `eval-results` | trace log, evaluation result files |
| `base/indexer-job.yaml` | Job `indexer` | **only writer** to Chroma (ingest → verify → update lake → update index) |
| `base/reindex-cronjob.yaml` | CronJob `reindex` (Sun 03:00) | scheduled re-run of the same ingestion |
| `base/configmap.yaml` | ConfigMap `rahbar-config` | embedding pin, collection name/version, chunking, rails |
| `gate-configmap.yaml` | ConfigMap `rahbar-gate-config` | release-gate thresholds (C2) + eval target |
| `eval-job.yaml` | Job `eval-job` | Part B suite + gate, exits 1 when the gate fails |
| `indexer-batch-b-job.yaml` | Job `indexer-batch-b` | Batch B ingestion (additive) |
| `indexer-candidate-job.yaml` | Job `indexer-candidate` | builds the candidate collection `rahbar_corpus_candidate` |
| `candidate-deployment.yaml` | Deployment + Service `api-candidate` | candidate pipeline with its own collection (F3) |
| `pvc-helper.yaml` | Pod `pvc-helper` | copy documents/baselines in, read traces/results out |
| `base/networkpolicy.yaml` | NetworkPolicies | default-deny; only api/indexer/candidate reach Chroma |

---

## 0. Fresh cluster bring-up

```bash
# Cluster (Calico is required: the default CNI silently ignores NetworkPolicy)
minikube start --driver=docker --cni=calico --memory=6144 --cpus=4
minikube addons enable metrics-server
minikube addons enable ingress

# Models on the host Ollama (the host-gpu-ollama overlay reaches it via host.minikube.internal)
ollama pull llama3.2:3b
ollama pull nomic-embed-text

# Build the four images and load them into the minikube node
TAG=$(git rev-parse --short HEAD)
docker build -t ghcr.io/rahbar/api:$TAG      -t ghcr.io/rahbar/api:local      ./api
docker build -t ghcr.io/rahbar/ui:$TAG       -t ghcr.io/rahbar/ui:local       ./ui
docker build -t ghcr.io/rahbar/indexer:$TAG  -t ghcr.io/rahbar/indexer:local  ./indexer
docker build -t ghcr.io/rahbar/eval:local -f eval/Dockerfile .
for img in api:$TAG api:local ui:$TAG indexer:$TAG indexer:local eval:local; do
  minikube image load ghcr.io/rahbar/$img
done

# Apply the stack. Base manifests carry the placeholder tag `:SHA`, which is
# NEVER applied literally: it is replaced with the git SHA first.
kubectl kustomize k8s/overlays/host-gpu-ollama | sed "s/:SHA/:$TAG/g" | kubectl apply -f -
kubectl apply -f k8s/gate-configmap.yaml -f k8s/pvc-helper.yaml
kubectl rollout status statefulset/chroma -n rahbar --timeout=300s
kubectl wait --for=condition=Ready pod/pvc-helper -n rahbar --timeout=120s
```

> The overlay also creates the `indexer` Job. Its corpus PVC is still empty at this point, so the
> first `indexer` pod may exit with code 2 ("no documents"). Step 1 below deletes it and re-creates it.

---

## 1. Part A — ingest, verify, incremental update

```bash
# Corpus into the data-lake PVC
python scripts/fetch_corpus.py
kubectl exec pvc-helper -n rahbar -- mkdir -p /corpus/raw /corpus/batch_b
kubectl cp corpus/raw/.     rahbar/pvc-helper:/corpus/raw
kubectl cp corpus/batch_b/. rahbar/pvc-helper:/corpus/batch_b

# A1+A2: first ingestion with verification (the only writer to Chroma)
kubectl delete job indexer -n rahbar --ignore-not-found
kubectl kustomize k8s/overlays/host-gpu-ollama | sed "s/:SHA/:$TAG/g" \
  | kubectl apply -f - -l app=indexer
kubectl wait --for=condition=complete job/indexer -n rahbar --timeout=900s
kubectl logs job/indexer -n rahbar

# A2: unchanged corpus re-run -> chunks_embedded: 0
kubectl create job --from=cronjob/reindex reindex-unchanged-1 -n rahbar
kubectl wait --for=condition=complete job/reindex-unchanged-1 -n rahbar --timeout=600s
kubectl logs job/reindex-unchanged-1 -n rahbar | grep -E '"chunks_embedded": 0|index_done'

# Batch B (planted problems): per-document pass/fail report, quarantine
kubectl apply -f k8s/indexer-batch-b-job.yaml
kubectl wait --for=condition=complete job/indexer-batch-b -n rahbar --timeout=600s
kubectl logs job/indexer-batch-b -n rahbar
kubectl exec pvc-helper -n rahbar -- ls /corpus/quarantine /corpus/archive /corpus/reports

# Unseen documents at the demo: copy them into the lake and run the ingestion Job again
kubectl cp <folder-with-new-docs>/. rahbar/pvc-helper:/corpus/raw
kubectl create job --from=cronjob/reindex ingest-unseen-1 -n rahbar
kubectl wait --for=condition=complete job/ingest-unseen-1 -n rahbar --timeout=900s
kubectl logs job/ingest-unseen-1 -n rahbar
```

A2 changed / deleted / superseded / rollback is shown end to end by
`python scripts/a2_incremental_demo.py`: it runs the real pipeline code with real
`nomic-embed-text` embeddings into a separate local Chroma, so the cluster's index has
only one writer. Its result file is in `eval/results/a2_incremental_demo_*.json`.
The rollback CLI is `python -m pipeline.rollback --doc-id <id> --to-version <ver>`.

---

## 2. Part B / C2 / F2 — evaluation Job + release gate

```bash
# Seed the baseline the gate compares against (once)
kubectl cp eval/results/baseline_k8s.json rahbar/pvc-helper:/results/baseline_k8s.json

kubectl delete job eval-job -n rahbar --ignore-not-found
kubectl apply -f k8s/eval-job.yaml
kubectl wait --for=condition=complete job/eval-job -n rahbar --timeout=1800s \
  || kubectl wait --for=condition=failed job/eval-job -n rahbar --timeout=10s
kubectl logs job/eval-job -n rahbar
kubectl exec pvc-helper -n rahbar -- ls -l /results          # timestamped result files
kubectl cp rahbar/pvc-helper:/results ./eval/results/k8s     # commit them
```

### F2: threshold change flips the gate without rebuilding the image

```bash
kubectl patch configmap rahbar-gate-config -n rahbar --type merge \
  -p '{"data":{"GATE_P95_LATENCY_MAX_MS":"500.0"}}'
kubectl delete job eval-job -n rahbar && kubectl apply -f k8s/eval-job.yaml
kubectl wait --for=condition=failed job/eval-job -n rahbar --timeout=1800s
kubectl logs job/eval-job -n rahbar | grep -A 8 "RELEASE GATE"      # GATE RESULT: FAIL

kubectl patch configmap rahbar-gate-config -n rahbar --type merge \
  -p '{"data":{"GATE_P95_LATENCY_MAX_MS":"45000.0"}}'
kubectl delete job eval-job -n rahbar && kubectl apply -f k8s/eval-job.yaml
kubectl wait --for=condition=complete job/eval-job -n rahbar --timeout=1800s
kubectl logs job/eval-job -n rahbar | grep -A 8 "RELEASE GATE"      # GATE RESULT: PASS
```

---

## 3. Part C3 / F3 — controlled release

```bash
# Candidate collection (built by an indexer Job) + candidate Deployment/Service
kubectl apply -f k8s/indexer-candidate-job.yaml
kubectl wait --for=condition=complete job/indexer-candidate -n rahbar --timeout=900s
kubectl apply -f k8s/candidate-deployment.yaml
kubectl rollout status deployment/api-candidate -n rahbar

# (a) A bad candidate is stopped by the gate and never rolled out
kubectl patch configmap rahbar-candidate-config -n rahbar --type merge \
  -p '{"data":{"TOP_K":"1","PROMPT_TEMPLATE":"bad_unconstrained_v0","COLLECTION_VERSION":"candidate-fail-v0"}}'
kubectl rollout restart deployment/api-candidate -n rahbar
kubectl rollout status deployment/api-candidate -n rahbar
kubectl patch configmap rahbar-gate-config -n rahbar --type merge \
  -p '{"data":{"EVAL_TARGET_API":"http://api-candidate:8000","EVAL_LABEL":"candidate-fail"}}'
kubectl delete job eval-job -n rahbar --ignore-not-found && kubectl apply -f k8s/eval-job.yaml
kubectl wait --for=condition=failed job/eval-job -n rahbar --timeout=1800s   # gate FAIL -> stop here
kubectl rollout history deployment/api -n rahbar                              # api unchanged

# (b) The good candidate passes the gate ...
kubectl patch configmap rahbar-candidate-config -n rahbar --type merge \
  -p '{"data":{"TOP_K":"5","PROMPT_TEMPLATE":"strict_concise_v2","COLLECTION_VERSION":"candidate-v2"}}'
kubectl rollout restart deployment/api-candidate -n rahbar
kubectl rollout status deployment/api-candidate -n rahbar
kubectl patch configmap rahbar-gate-config -n rahbar --type merge \
  -p '{"data":{"EVAL_LABEL":"candidate-pass"}}'
kubectl delete job eval-job -n rahbar && kubectl apply -f k8s/eval-job.yaml
kubectl wait --for=condition=complete job/eval-job -n rahbar --timeout=1800s  # gate PASS

# ... and is released to the live Deployment with a rolling update (maxUnavailable: 0)
kubectl set env deployment/api -n rahbar \
  CHROMA_COLLECTION=rahbar_corpus_candidate COLLECTION_VERSION=candidate-v2 PROMPT_TEMPLATE=strict_concise_v2
kubectl rollout status deployment/api -n rahbar

# (c) A bad release reversed with rollout undo; a NEW trace shows the previous collection
kubectl rollout undo deployment/api -n rahbar
kubectl rollout status deployment/api -n rahbar
kubectl port-forward svc/api 8000:8000 -n rahbar &
TRACE_ID=$(curl -s -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"question":"What is the attendance requirement for a course?","follow_up":true}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['trace_id'])")
kubectl logs -l app=api -n rahbar --tail=500 | grep "$TRACE_ID" \
  | python -c "import sys,json; r=json.loads(sys.stdin.readline()); print({k:r[k] for k in ('trace_id','collection_name','collection_version','embedding_model','embedding_version')})"
#   -> collection_name rahbar_corpus, collection_version v1, embedding nomic-embed-text:v1.5
python scripts/trace_tool.py "$TRACE_ID" --trace-file - < <(kubectl exec pvc-helper -n rahbar -- cat /traces/traces.jsonl)

# Point the eval Job back at the live api
kubectl patch configmap rahbar-gate-config -n rahbar --type merge \
  -p '{"data":{"EVAL_TARGET_API":"http://api:8000","EVAL_LABEL":"k8s-eval"}}'
```

---

## 4. Part D / F4 — traces and metrics on the cluster

```bash
kubectl logs deployment/api -n rahbar | grep ragops_trace | tail -1       # JSON line on stdout
kubectl exec pvc-helper -n rahbar -- tail -n 1 /traces/traces.jsonl       # same record on the PVC
kubectl cp rahbar/pvc-helper:/traces/traces.jsonl traces/traces.jsonl

python scripts/trace_tool.py <trace_id> --trace-file traces/traces.jsonl  # D2: exact context + prompt
python scripts/summarize_traces.py --trace-file traces/traces.jsonl --window 24h   # D3

kubectl port-forward svc/api 8000:8000 -n rahbar &
curl -s localhost:8000/metrics | grep -E '^(top1_retrieval_similarity|abstentions_total|cache_(hits|misses)_total|stage_latency_seconds|injection_attempts_flagged_total)'
```

---

## 5. Part E — coverage

```bash
python eval/coverage_check.py --live-queries eval/live_queries.jsonl --golden eval/golden.jsonl \
  --sim-threshold 0.70 --coverage-threshold 0.85        # exit 1 when coverage < 85 %
```

---

## 6. Part F5 — resource measurements

```bash
kubectl top pods -n rahbar            # idle, during the indexer Job, and during the eval Job
```
The measured numbers and the requests/limits taken from them are in the report (Part F5).
