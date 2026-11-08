# Project: RAHBAR — Grounded RAG on Kubernetes

## Architecture
RAHBAR is a grounded, cite-or-abstain question-answering system running in the `rahbar` namespace on Kubernetes.
The architecture enforces three core axioms:
1. **"One writer, one reader, one shared pin"**:
   - **Indexer**: Runs strictly as an offline batch `Job` or weekly `CronJob`. It chunks and embeds documents, stores embeddings into ChromaDB, sets model pinning metadata, and invalidates the Redis semantic cache.
   - **API**: A stateless FastAPI deployment (3 to 8 replicas autoscaled by HPA) that performs read-only queries against ChromaDB, checks and writes to the Redis cache, queries LLMs, and verifies citations.
   - **Shared Pin**: Both workloads mount `EMBED_MODEL` ("nomic-embed-text", 768 dimensions) from `ConfigMap/rahbar-config`. API startup halts readiness (`/readyz` returns 503) if Chroma collection metadata does not match the pinned model.
2. **"Fluency is not factuality"**:
   - The API generates answers strictly conforming to the Pydantic `Answer` schema (`reasoning`, `answer`, `citations`, `answered_from_context`, `confidence`).
   - If retrieved chunks do not meet `relevance_floor` (0.64; was 0.35 before the nomic task prefixes - see docs/PIPELINE.md), the system abstains (`answered_from_context: false`).
   - All citations must match retrieved document chunk IDs.
3. **"Secure, observable, resilient infrastructure"**:
   - Chroma is deployed as a 1-replica `StatefulSet` with `volumeClaimTemplates` (5Gi RWO PVC).
   - Redis is deployed with a persistent PVC (2Gi RWO).
   - NetworkPolicy enforces default deny with precise ingress/egress allowances.
   - All workloads run as non-root (UID 10001), drop all capabilities, use read-only root filesystems, and set explicit CPU/memory requests and limits.

```
                                  [ User ]
                                     │
                                     ▼
                            [ Ingress (Host) ]
                       /                          \
             path: / ┌                             ┐ path: /api
                     ▼                             ▼
            [ UI: Deployment x1 ]         [ API: Deployment x3-8 ]
            - nginx chat UI               - FastAPI (HPA: 3-8, CPU 70%)
                                          - Probes: startup, liveness, readiness
                                           │       │               │
                            cache check    │       │ reads only    │ generate
                                           ▼       │               ▼
                             [ Redis: Deploy+PVC ] │     [ LLM Provider ]
                             - Semantic cache      │     - ollama-host (default)
                                                   ▼     - hosted (Groq/OpenRouter)
                                      [ Chroma: StatefulSet x1 ]
                                      - Vector Store + PVC (chroma-data)
                                      - ClusterIP Service
                                                   ▲
                                                   │ writes only
                                      [ Indexer: Job / CronJob ]
                                      - On-demand Job & weekly CronJob
                                      - Invalidates Redis on completion
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Raw Corpus Ingestion | Acquisition & ingestion of FAST-NUCES policies/schedules/curricula | M3 | survey |
| 2 | Corpus Cleaner & Normalizer | Strips HTML, normalizes unicode/newlines, preserves Markdown structure | M3 | survey |
| 3 | Deterministic Chunker | Chunk size 512, overlap 64 tokens, heading-aware chunking | M3 | survey |
| 4 | Chunk Metadata Generator | Generates doc_id, chunk_id, source_url, title, section headers | M3 | survey |
| 5 | Embedding Generation | Batched embedding using pinned nomic-embed-text (768 dims) | M3 | survey |
| 6 | Chroma Vector Store Writer | Indexer writes vectors, texts, and metadata into Chroma collection | M3 | survey |
| 7 | Chroma Model Pin Metadata | Stores model name and dimension in collection metadata for verification | M3 | survey |
| 8 | Corpus Manifest & Checksums | Generates/verifies corpus/MANIFEST.md with valid SHA-256 hashes | M3 | survey |
| 9 | Cache Invalidation Trigger | Indexer connects to Redis upon completion to flush semantic cache | M3 | survey |
| 10 | Query Embedding | API embeds user query using identical model and dimension | M2 | survey |
| 11 | Chroma Vector Reader | API performs cosine similarity search retrieving top_k (5) chunks | M2 | survey |
| 12 | Relevance Floor Filter | Discards chunks with similarity below relevance_floor (0.64) | M2 | survey |
| 13 | Grounded Abstention | Returns answered_from_context: false when no chunks pass relevance floor | M2 | survey |
| 14 | Redis Semantic Cache Check | Checks query embedding similarity >= 0.92 against cached queries | M2 | survey |
| 15 | Redis Semantic Cache Write | Stores query vector and generated Answer upon cache miss | M2 | survey |
| 16 | Grounded Prompt Builder | Formats prompt with retrieved chunks, citations instructions, refusal rule | M2 | survey |
| 17 | LLM Provider - Ollama Host | Connects to host Ollama instance via host.minikube.internal / host gateway | M2 | survey |
| 18 | LLM Provider - Hosted | Connects to Groq/OpenRouter with secret-mounted API keys | M2 | survey |
| 19 | Pydantic Answer Validation | Enforces Answer schema: reasoning, answer, citations, answered_from_context | M2 | survey |
| 20 | Citation Exact Matching | Validates that every citation in answer exactly matches retrieved chunk IDs | M2 | survey |
| 21 | Hallucination Fallback | Retries or falls back to refusal if LLM output fails schema validation | M2 | survey |
| 22 | Endpoint `/chat` | Main query endpoint returning ChatResponse wrapping Answer | M2 | survey |
| 23 | Endpoint `/healthz` | Process liveness probe checking FastAPI process health | M2 | survey |
| 24 | Endpoint `/readyz` | Readiness probe checking Chroma count, Redis ping, and model pin match | M2 | survey |
| 25 | Endpoint `/metrics` | Prometheus metrics text format with 7 required metric families | M2 | survey |
| 26 | Endpoint `/` & docs | Static root and OpenAPI documentation endpoints | M2 | survey |
| 27 | Structured JSON Logging | Machine-readable JSON logs to stdout with correlation IDs | M2 | survey |
| 28 | Chroma StatefulSet Manifest | StatefulSet x1, volumeClaimTemplates for chroma-data 5Gi RWO | M1 | survey |
| 29 | Redis Deployment Manifest | Deployment x1 with persistent PVC redis-data 2Gi RWO | M1 | survey |
| 30 | API Deployment Manifest | 3 replicas, rollingUpdate, probes, securityContext, requests/limits | M1 | survey |
| 31 | UI Deployment Manifest | 1 replica serving nginx chat frontend | M1 | survey |
| 32 | Ingress Manifest | Ingress routing / to UI and /api to API service | M1 | survey |
| 33 | ClusterIP Services | All services strictly ClusterIP (no NodePort or LoadBalancer) | M1 | survey |
| 34 | Dedicated ServiceAccounts | Separate ServiceAccounts per component with automount token disabled | M1 | survey |
| 35 | ConfigMap Manifest | All RAG configuration parameters and model pins in ConfigMap | M1 | survey |
| 36 | Secret Manifest Template | rahbar-secret with placeholder base64 keys, strictly gitignored | M1 | survey |
| 37 | NetworkPolicy Default Deny | rahbar-default-deny blocking unlisted ingress and egress | M1 | survey |
| 38 | NetworkPolicy DNS Selector Fix | Prevent Kustomize commonLabels from mutating kube-dns egress selector | M1 | survey |
| 39 | NetworkPolicy Indexer-Redis | Allow indexer egress and Redis ingress on port 6379 for invalidation | M1 | survey |
| 40 | HorizontalPodAutoscaler | Scales API from 3 to 8 replicas based on 70% CPU utilization | M1 | survey |
| 41 | Zero-Downtime Rollout Strategy | maxSurge: 1, maxUnavailable: 0 with preStop sleep hook | M1 | survey |
| 42 | Golden Dataset | eval/golden.yaml with >= 15 questions across all 5 mandatory types | E2E | survey |
| 43 | Automated Evaluation Pipeline | eval/run_eval.py computing retrieval & generation metrics | E2E | survey |
| 44 | Live Response Parsing Alignment | Align eval/run_eval.py and cd.yml with ChatResponse.answer structure | M2 | survey |
| 45 | CI Workflow (ci.yml) | GitHub Actions workflow: lint, test, kubeconform, build, trivy, eval | M2 | survey |
| 46 | CD Workflow (cd.yml) | GitHub Actions workflow: test, build-push by SHA, deploy, smoke test | M1 | survey |
| 47 | Submission Verification | 12 automated checks in scripts/check_submission.py passing 100% | M_Final | survey |
| 48 | Architecture Docs & Evidence | Complete ADRs 0001-0004, 7 engineering notes, evidence templates | M4 | survey |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | K8s Manifests & Infrastructure | Fix Kustomize DNS selector trap, add indexer-redis NetworkPolicy rule, modernize Kustomize resources, verify manifest rendering | none | DONE |
| M2 | API Service & Evaluation Alignment | Fix ChatResponse schema unwrapping in eval & CD, fix typing errors in chat.py for mypy, resolve ruff lint and formatting errors | none | DONE |
| M3 | Indexer Pipeline & Corpus Integrity | Fix cross-platform test sorting in pipeline tests, verify Chroma model pinning metadata & Redis invalidation, audit corpus manifest | none | DONE |
| M4 | Documentation, ADRs & Evidence | Complete ADRs 0001-0004, answer all 7 engineering questions, generate evidence templates & validation logs | M1, M2, M3 | DONE |
| E2E | Opaque-Box E2E Testing Track | Requirement-driven test suite (Tiers 1-4: features, boundaries, combinations, realistic golden workloads), produce TEST_READY.md | none | DONE |
| M_Final | Final Verification & Submission Gate | Phase 1: 100% E2E test pass across Tiers 1-4; Phase 2: Adversarial coverage hardening (Tier 5); Full submission checker clean run | M1, M2, M3, M4, E2E | DONE |

## Interface Contracts
### API ↔ ChromaDB
- **Protocol**: HTTP / Chroma REST Client (`http://chroma.rahbar.svc.cluster.local:8000`)
- **Collection Name**: `rahbar_corpus`
- **Metadata Contract**:
  - `collection.metadata["model_name"]` must equal `EMBED_MODEL` ("nomic-embed-text")
  - `collection.metadata["dimension"]` must equal `EMBED_DIMENSION` (768)
- **API `/readyz` Invariant**: Checks `chroma_client.heartbeat()` and verifies metadata match. If mismatched or empty, returns HTTP 503.

### API ↔ Redis Semantic Cache
- **Protocol**: Redis protocol (`redis://redis.rahbar.svc.cluster.local:6379/0`)
- **Keys**: `cache:query:<sha256(normalized_query)>` -> JSON `{ "embedding": [...], "answer": Answer.model_dump() }`
- **Cache Match**: Cosine similarity >= `CACHE_THRESHOLD` (0.92).
- **Cache Invalidation**: On re-indexing, Indexer calls `redis.flushdb()`.

### API ↔ Frontend / Evaluator / CD Client
- **Route**: `POST /chat`
- **Request Body**: `ChatRequest(query: str, request_id: Optional[str] = None)`
- **Response Body**:
  ```json
  {
    "answer": {
      "reasoning": "...",
      "answer": "...",
      "citations": ["doc_id#chunk_id", ...],
      "answered_from_context": true/false,
      "confidence": 0.0-1.0
    },
    "request_id": "...",
    "cache_hit": true/false,
    "latency_ms": 123.4
  }
  ```
- **Unwrapping Contract**: Clients reading `citations` or `answered_from_context` must check `resp.get("answer", {}).get("citations")` or `resp.get("citations")` if flattened.

## Code Layout
```
c:\Users\mohsi\Desktop\SCD-02\
├── .github/
│   └── workflows/
│       ├── ci.yml                 # CI workflow (lint, test, kubeconform, trivy, eval)
│       └── cd.yml                 # CD workflow (test, build-push, deploy, smoke)
├── api/                           # FastAPI service (read-only query engine)
│   ├── app/
│   │   ├── config.py              # Configuration & env var parsing
│   │   ├── main.py                # FastAPI app initialization & probe routes
│   │   ├── metrics.py             # Prometheus metric families
│   │   ├── schemas.py             # Pydantic schemas (Answer, ChatRequest, ChatResponse)
│   │   ├── providers/             # LLM provider implementations (Ollama, hosted)
│   │   ├── retrieval/             # Chroma retriever & Redis semantic cache
│   │   ├── routes/                # Endpoint handlers (/chat, /healthz, /readyz, /metrics)
│   │   └── services/              # Chat orchestration & citation verification
│   ├── tests/                     # Unit tests for API
│   ├── Dockerfile                 # Multi-stage non-root container build
│   └── requirements.txt
├── indexer/                       # Batch Indexer Job / CronJob
│   ├── pipeline/                  # 5-stage pipeline: extract, clean, chunk, embed, store
│   ├── tests/                     # Unit tests for indexing pipeline
│   ├── Dockerfile
│   └── requirements.txt
├── corpus/                        # Document corpus
│   ├── raw/                       # Markdown / PDF policy and curriculum files
│   └── MANIFEST.md                # SHA-256 document manifest
├── eval/                          # Evaluation framework & golden dataset
│   ├── golden.yaml                # 15+ questions across 5 mandatory categories
│   ├── baseline.json              # Baseline retrieval and generation metrics
│   ├── run_eval.py                # Offline and live evaluation runner & CI gate
│   └── test_run_eval.py           # Unit tests for evaluator
├── k8s/                           # Kubernetes manifests
│   ├── base/                      # 16 base manifests in namespace rahbar
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── api-deployment.yaml
│   │   ├── chroma-statefulset.yaml
│   │   ├── redis.yaml
│   │   ├── indexer-job.yaml
│   │   ├── reindex-cronjob.yaml
│   │   ├── services.yaml
│   │   ├── ingress.yaml
│   │   ├── configmap.yaml
│   │   ├── rahbar-secret.yaml
│   │   ├── networkpolicy.yaml
│   │   ├── hpa.yaml
│   │   ├── serviceaccounts.yaml
│   │   └── corpus-pvc.yaml
│   └── overlays/
│       ├── dev/
│       └── prod/
├── ui/                            # Web frontend (nginx chat UI)
│   ├── Dockerfile
│   └── html/
├── docs/                          # Architecture documentation, ADRs, evidence
│   ├── ARCHITECTURE.md
│   ├── CORPUS.md
│   ├── PIPELINE.md
│   ├── FAILURE-ANALYSIS.md
│   ├── ENGINEERING-NOTES.md
│   ├── AI-USAGE.md
│   ├── adr/
│   │   ├── 0001-indexer-as-job.md
│   │   ├── 0002-semantic-cache-redis.md
│   │   ├── 0003-llm-provider-pluggable.md
│   │   └── 0004-embedding-pin.md
│   └── evidence/                  # Verification evidence artifacts
├── scripts/
│   ├── check_submission.py        # Submission invariant checker (12 checks)
│   └── fetch_corpus.py            # Corpus fetcher & manifest generator
└── Makefile                       # Build, deploy, test, lint automation
```
