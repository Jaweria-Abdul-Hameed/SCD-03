# RAHBAR — Grounded RAG on Kubernetes (CS4032 Assignment 03: RAGOps)

> **CS4032 Software Quality Engineering & Construction — Assignment 03 (RAGOps)**  
> **Authors:** Jaweria Abdul Hameed (jaweriahameed06@gmail.com) • Mohsin Khan (mohsinkhan.devs@gmail.com)  
> **Technical Report PDF:** [Report_CS4032_Assignment03.pdf](Report_CS4032_Assignment03.pdf) (8-page main body + 13-screenshot Appendix)  
> **Checklist:** [SCD_Assignment03_RAGOps_Implementation_Checklist.md](SCD_Assignment03_RAGOps_Implementation_Checklist.md) / [PDF](SCD_Assignment03_RAGOps_Implementation_Checklist.pdf)  
> **Kubernetes Guide:** [k8s/README.md](k8s/README.md)  
> **Paper Foundation:** *RAGOps: Operating and Managing Retrieval-Augmented Generation Pipelines* (Xu et al., 2026)

---

## Assignment 03 (RAGOps) Implementation Highlights

1. **Part A: Data Management & Verification (Paper §§4.2.1–4.2.4)**
   - 4 Pre-chunking verification gates: Quality, Completeness, Recency, Uniqueness (SHA-256 + 0.94 cosine).
   - Failing documents quarantined to /corpus/quarantine/ with structured reports; 0 polluted chunks in Chroma.
   - Batch B verification caught 6 planted defective documents (04–09); superseded active June 2026 rules with Nov 2026 revision (10).
   - Unchanged corpus re-run verified on Kubernetes: **embedded exactly 0 chunks** (chunks_embedded: 0).
2. **Part B: 3-Level Offline Evaluation Suite (Paper §4.2.5 & Table 1)**
   - Single command runner (eval/run_ragops_eval.py).
   - **Level 1 (Module):** Cosine separation gap = 0.2891, throughput = 45.77ms/chunk, determinism = 0.00000000.
   - **Level 2 (Component):** recall@3 = 0.5714, recall@5 = 0.7143, MRR = 0.4913, nDCG@5 = 0.5460; Typo noise test: Δ = 0.0000.
   - **Level 3 (E2E):** Faithfulness = 0.8333, Abstention correctness = 1.0000 (6/6), Citation validity = 1.0000, p95 latency = 12.1s.
   - **LLM Judge Calibration:** dolphin-mistral:latest achieved **90.0% agreement** against 10 human labels.
   - **Stochasticity Analysis:** Fixed seed yielded 0.0000 variation across Level 1, Level 2, and Level 3 metrics.
3. **Part C: Change Experiment & Automated Release Gate (Paper §4.1(d), §§4.2.5–4.2.6)**
   - Candidate collection isolation (
ahbar_corpus_candidate) and isolated deployment (pi-candidate:8000).
   - Evaluated candidate prompt (strict_concise_v2): recall@5 preserved (+0.0000), faithfulness increased to 89.5%, p95 latency reduced by 63.3% to 4.4s → **GATE RESULT: PASS (Exit 0)**.
   - Evaluated degraded candidate: recall drop = +0.3333 > 0.02 threshold → **GATE RESULT: FAIL (Exit 1)**.
4. **Part D: Observability, Traceability & Safety Rails (Paper §§3.2.3, 5.1)**
   - Every request emits 16-field JSONL trace to /traces/traces.jsonl with cryptographic SHA-256 prompt hash.
   - scripts/trace_tool.py: Reconstructs exact context and verifies hash for any trace ID.
   - scripts/summarize_traces.py: Aggregates top-1 similarity distribution, abstention rate, cache hit rate, and latency breakdown over 24h windows.
   - Dual-rail prompt injection defense: Input Rail (I) + Retrieval Rail (R) caught and stripped/excluded Batch B's poisoned directives (11).
5. **Part E: Drift & Query Coverage Checking (Paper §4.1(e), §4.2.7)**
   - Live query coverage tool (eval/coverage_check.py): measured cosine similarity against golden benchmark.
   - Pre-expansion baseline failed gate: **59.5% coverage (25/42)** → grouped uncovered queries into 4 topics.
   - Expanded golden set by 6 questions (26 → 32) → coverage rose to **85.7% (36/42)** → **PASS (Exit 0)**.
6. **Part F: Kubernetes Native Architecture & Zero-Downtime Rollout (Paper §§4.1(e–f), 5.1)**
   - Runs natively on Minikube with Calico CNI in namespace 
ahbar.
   - Single-writer architecture (indexer-sa exclusive write access; pi-sa read-only).
   - ConfigMap live-edit gate flip demonstrated: edited GATE_P95_LATENCY_MAX_MS: 500.0 → Job FAILED; restored to 45000.0 → Job PASSED without container rebuild.
   - Zero-downtime rolling update (maxUnavailable: 0) and instant rollback demonstrated.

---

# RAHBAR — Grounded RAG on Kubernetes

A question-answering service that answers **only from a real document
corpus**, cites its sources, and runs on Kubernetes. When the corpus does
not contain the answer, it says so instead of inventing one.

- **Corpus:** real public FAST-NUCES documents (see `corpus/MANIFEST.md`
  for URLs and SHA-256 hashes — the PDFs themselves are **not** committed;
  run `scripts/fetch_corpus.py` to download them). The corpus is graded:
  6+ documents / 40+ pages, two versions of one policy, one scanned PDF
  (OCR), one complex table, one long definition clause, one deliberately
  absent topic (transport/hostel rules — the service must abstain on it),
  and exact-term content (course codes, clause numbers, CGPA thresholds).
  Full detail: `docs/CORPUS.md`.
- **Rule in one line:** one writer, one reader, one shared pin — only the
  indexer Job writes to Chroma, the API only reads it, and both read
  `EMBED_MODEL=nomic-embed-text` (768 dims) from one ConfigMap
  (see `docs/ARCHITECTURE.md` and `docs/adr/0004-embedding-pin.md`).
- **Evaluation:** `eval/golden.yaml` (15 questions), `eval/run_eval.py`,
  `eval/baseline.json` / `eval/results.json`. CI fails if recall@5 drops
  >5pp below baseline, any must-abstain question is answered from
  context, or citation validity falls below 95% (sec. 5.4).
  `eval/golden.yaml` + `eval/baseline.json` + `eval/results.json` are the **real, committed live run on the full
  corpus** (15 documents, 480 chunks, in-cluster Ollama `llama3.2:3b` + `nomic-embed-text`): recall@3 0.68,
  recall@5 0.83, citation validity 1.00, abstention correctness 1.00 (details: `docs/ENGINEERING-NOTES.md` Q5,
  `docs/PIPELINE.md`). CI's `e2e-eval` indexes only the 3 invented documents in `eval/fixtures/` with the stub
  provider, so it enforces the same gate with `eval/golden.fixture.yaml` + `eval/baseline.fixture.json`.

## Prerequisites

- Docker, `kubectl`, `kustomize`, `minikube`
- Ollama on your laptop (default `ollama-host` mode) — see below
- Python 3.12 (for `scripts/check_submission.py` and the eval runner)

## Apply order (clean clone — this order works)

```bash
# 1. Clone and check the submission mechanics first (fast, no cluster).
git clone <your-repo-url> rahbar && cd rahbar
python scripts/check_submission.py

# 2. Start the cluster with Calico — the default network plugin accepts
#    NetworkPolicy manifests and then silently ignores them (sec. 9).
#    6 GB is comfortable with Ollama on your laptop; 4 GB works if you
#    must; 8 GB for in-cluster Ollama.
minikube start --driver=docker --cni=calico --memory=6144 --cpus=4
minikube addons enable metrics-server
minikube addons enable ingress

# 3. Ollama on your laptop (default ollama-host mode): listen on ALL
#    interfaces, not just 127.0.0.1, or the cluster cannot reach it.
OLLAMA_HOST=0.0.0.0 ollama serve
ollama pull llama3.2:3b
ollama pull nomic-embed-text

# 4. Namespace and ConfigMap only. Do NOT apply the placeholder secret
#    file k8s/base/rahbar-secret.yaml — it is gitignored (*-secret.yaml),
#    it is NOT listed in k8s/base/kustomization.yaml, and a clean clone
#    does not even have it. The real Secret is created in step 6, AFTER
#    the overlay is applied, and the placeholder must never be applied
#    afterwards (it would overwrite the real Secret).
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/base/configmap.yaml

# 5. Apply the stack (prod overlay) and wait for the rollout. The
#    manifests carry the literal placeholder tag `:SHA` — NEVER deploy
#    that literal tag. `make deploy` builds the three images locally,
#    computes TAG from `git rev-parse --short HEAD` (fallback `local`
#    if git is absent), sed-replaces `:SHA` with `:$TAG` in the
#    kustomize output, and only then applies it:
#      make deploy
#    (equivalent manual flow: docker build -t ghcr.io/rahbar/api:$TAG ./api
#     [same for ui/indexer], then kustomize build k8s/overlays/prod
#     | sed "s/:SHA/:$TAG/g" | kubectl apply -f -)
make deploy
kubectl get pods -n rahbar

# 6. Create the REAL Secret now that the overlay is applied (only needed
#    for the hosted LLM provider; for the default ollama-host mode there
#    is no key — create it with a placeholder value or skip it, since the
#    api Deployment's secretRef is optional: true).
kubectl create secret generic rahbar-secret -n rahbar \
  --from-literal=LLM_API_KEY="<redacted>"
#    Never run `kubectl apply -f k8s/base/rahbar-secret.yaml` after this:
#    the placeholder file would overwrite the real Secret above.

# 7. Fetch the corpus (MANIFEST only is committed — see the corpus note
#    below), copy it into the corpus-data PVC, then run the indexer Job —
#    indexing is a Job, never API startup (docs/adr/0001-indexer-as-job.md).
#    The Job mounts the PVC at /corpus; an empty PVC means the Job finds
#    no documents (exit 2), so the copy step must come first.
python scripts/fetch_corpus.py
make corpus-to-cluster
kubectl wait --for=condition=complete --timeout=600s job/indexer -n rahbar
kubectl logs job/indexer -n rahbar
#    NOTE: do NOT re-apply k8s/base/indexer-job.yaml here — the prod
#    overlay applied in step 5 already created the Job. Re-applying it
#    is redundant (and a completed Job cannot be re-applied cleanly);
#    the wait + logs above are the verification step.

# 8. Verify readiness, then ask a question through the Ingress.
#    The Ingress host is rahbar.local (k8s/base/ingress.yaml): add
#    "127.0.0.1 rahbar.local" to /etc/hosts, or pass the Host header as
#    below. /api/chat is rewritten to /chat on the api Service.
kubectl get pods -n rahbar            # api should be 3/3 READY
curl -H 'Host: rahbar.local' http://$(minikube ip)/api/readyz  # 200 only when Chroma is non-empty
curl -H 'Host: rahbar.local' -X POST http://$(minikube ip)/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"question": "Can a student register for a course after failing its prerequisite?"}'
#    Expect a cited answer with answered_from_context: true.
curl -H 'Host: rahbar.local' -X POST http://$(minikube ip)/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"question": "What are the hostel allotment rules for first-year students?"}'
#    Expect answered_from_context: false — hostel rules are deliberately
#    absent from the corpus (property 6).

# 9. Re-index without a redeploy (weekly CronJob also does this):
kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar

# 10. Run the evaluation against the live stack. The eval runner talks
#     to the API over HTTP, so port-forward the api Service to localhost
#     FIRST, then run it:
kubectl port-forward svc/api 8000:8000 -n rahbar
python eval/run_eval.py --output eval/results.json
```

Or use the Makefile: `make cluster && make deploy && make corpus-to-cluster && make index && make eval`
(see `Makefile`).

## Alternative: Ollama inside the cluster (`ollama-incluster`, the mode the reference run used)

If the cluster cannot (or must not) reach an Ollama on your laptop, apply the
overlay that adds Ollama as a Deployment + PVC (weights), pinned image, non-root,
read-only root filesystem, a `startupProbe` with `failureThreshold: 30`, and the
NetworkPolicies `api/indexer -> ollama` (the `ui` cannot reach it). It needs the
8 GB / 6 CPU minikube from step 2 and sets `LLM_PROVIDER=ollama-incluster`,
`OLLAMA_NUM_THREAD=4` (Ollama otherwise starts one thread per HOST core and is
throttled to ~1 token/s - see `docs/ENGINEERING-NOTES.md` Q7) and a 400 s generation timeout.

```bash
# instead of step 5 (`make deploy`): build + load the images as before, then
TAG=$(git rev-parse --short HEAD)
kubectl kustomize k8s/overlays/incluster-ollama | sed "s/:SHA/:$TAG/g" | kubectl apply -f -
kubectl rollout status deploy/ollama -n rahbar --timeout=600s
kubectl exec deploy/ollama -n rahbar -- ollama pull nomic-embed-text
kubectl exec deploy/ollama -n rahbar -- ollama pull llama3.2:3b
# then step 7 (corpus -> PVC; the Job was created by the overlay) as before
```

On Windows the same flow is automated, idempotently, by
`scripts/rebuild-from-scratch.ps1` (about 1 hour from nothing).

## Running the demo

> **GPU mode:** the demo cluster runs the model on the laptop GPU through the host Ollama (`k8s/overlays/host-gpu-ollama`, 3 s per answer instead of 15-55 s on CPU, identical evaluation). Nothing is exposed: the host Ollama stays on 127.0.0.1. Details and the CPU fallback: `docs/DEMO.md`, section *GPU mode*.

`docs/DEMO.md` is the numbered live-demo script (exact PowerShell commands, expected
output, timings, a troubleshooting table and a 90-second architecture pitch).

| Script (PowerShell) | What it does |
|---|---|
| `.\scripts\demo-up.ps1` | after a reboot: starts minikube if needed, waits for all pods, checks the index (also against an exact search) and the Ollama models, starts the UI/API port-forwards, pre-warms Ollama |
| `.\scripts\demo-check.ps1` | smoke test, non-zero exit on failure (health, cited answer, abstention, 11 PLOs / clause 1.21, cache hit, HPA, 3 endpoints) |
| `.\scripts\demo-down.ps1` | stops the port-forwards and runs `minikube stop` (never `delete`) |
| `.\scripts
ebuild-from-scratch.ps1` | clean clone -> working stack |

A recorded transcript of a full rehearsal (fallback if the live cluster fails) is in
`docs/evidence/live/demo-transcript.md`.

## Corpus note

The repository commits `corpus/MANIFEST.md` (each document's URL and
SHA-256 checksum) plus the fetch script `scripts/fetch_corpus.py` — **not**
the PDFs themselves. For anything we do not own, including the FAST-NUCES
files, that is the correct form (sec. 2): run the fetch script to
download them, and verify the hashes in `MANIFEST.md` match. Never commit
documents from SLATE, Flex, NU Mail, or anything behind a login.

## Layout

```
rahbar/
├── api/              # FastAPI service: reads the index, never writes it
├── indexer/          # the Job's image: the only writer
├── ui/               # chat UI served by nginx
├── corpus/           # MANIFEST.md + fetch script (PDFs not committed)
├── eval/             # golden.yaml, run_eval.py, baseline.json, results.json, fixtures/
├── k8s/              # base/ + overlays/{dev,prod}/
├── docs/             # CORPUS, PIPELINE, FAILURE-ANALYSIS, ENGINEERING-NOTES,
│                     # AI-USAGE, ARCHITECTURE, adr/0001-0004, evidence/
├── scripts/check_submission.py
├── .github/workflows/{ci.yml,cd.yml}
└── Makefile · README.md · LICENSE · .gitignore
```

## Docs to read first

1. `docs/adr/0001-indexer-as-job.md` — why indexing is a Job (read this first)
2. `docs/ARCHITECTURE.md` — one-page system diagram + why Chroma is a StatefulSet
3. `docs/ENGINEERING-NOTES.md` — answers to the 7 required questions, with file:line refs
4. `docs/PIPELINE.md` — extraction / chunking / embedding, with measured chunk configs
5. `docs/FAILURE-ANALYSIS.md` — 4 pipeline stages broken on purpose, with diagnoses
6. `docs/AI-USAGE.md` — honest AI attribution
7. `docs/CORPUS.md` — the 7 corpus properties and the failure modes they make reachable

## CI / CD

- **CI** (`.github/workflows/ci.yml`, on PR to `main` + push to `dev`):
  lint → test (pytest, ≥60% coverage, stub provider) → manifests
  (`kustomize build | kubeconform -strict`) → build (no push on PR) →
  Trivy scan (fail on HIGH/CRITICAL with a fix) → e2e-eval on a kind
  cluster, enforcing the sec. 5.4 gate.
- **CD** (`.github/workflows/cd.yml`, on push to `main`): test →
  build-push (`needs: test`) → deploy (`needs: build-push`), images
  tagged only with `${{ github.sha }}` — never the floating `latest` tag.

## Troubleshooting (sec. 9 traps)

| Symptom | Usual cause | Fix |
|---|---|---|
| `ImagePullBackOff` on a locally built image | minikube cannot see your laptop's Docker images | `minikube image load <image>:<tag>`, and set `imagePullPolicy: IfNotPresent` |
| Every service name stops resolving after NetworkPolicy | Default-deny egress also blocks DNS | Allow egress to kube-dns on port 53 (UDP and TCP) in kube-system (`k8s/base/networkpolicy.yaml`) |
| API cannot reach Ollama on your laptop | Ollama listens on 127.0.0.1 only, or policy blocks host egress | Run Ollama with `OLLAMA_HOST=0.0.0.0`; allow api egress to the host IP (`minikube ssh "grep host.minikube.internal /etc/hosts"`) |
| UI can still reach Chroma despite the policy | Cluster started without Calico | Recreate it with `--cni=calico` |
| HPA shows `<unknown>/70%` | No `requests.cpu`, or metrics-server not enabled | Add requests; enable the addon; wait ~1 minute |
| Indexer pod in `CrashLoopBackOff`, exit code 137 | OOMKilled: embedding uses far more memory than serving | Raise the Job's memory limit, guided by `kubectl top pods` |
| API Running but 0/1 READY | Readiness says no: empty collection, wrong probe path, or the embedding-pin guardrail | `kubectl describe pod`, then `kubectl logs` |

Diagnose in this order, always: `kubectl get pods`, then
`kubectl describe pod` (read the Events at the bottom), then
`kubectl logs` (adding `--previous` for a crashed container).
